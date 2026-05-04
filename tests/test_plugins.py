from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.main import create_app
from ragrig.plugins import (
    Capability,
    PluginConfigValidationError,
    PluginManifest,
    PluginRegistry,
    PluginStatus,
    PluginTier,
    get_plugin_registry,
)
from ragrig.plugins.contract import _is_valid_docs_reference, assert_registry_contracts

REPO_ROOT = Path(__file__).resolve().parents[1]


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def _create_file_session_factory(database_path: Path) -> Callable[[], Session]:
    engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)

    def _factory() -> Session:
        return Session(engine, expire_on_commit=False)

    return _factory


def test_registry_registers_builtin_plugins_and_official_stubs() -> None:
    registry = get_plugin_registry()
    manifests = registry.list()
    manifest_ids = {manifest.plugin_id for manifest in manifests}

    assert len(manifests) == 30
    assert {
        "source.local",
        "parser.markdown",
        "parser.text",
        "chunker.character_window",
        "embedding.deterministic_local",
        "model.ollama",
        "model.lm_studio",
        "embedding.bge",
        "reranker.bge",
        "vector.pgvector",
        "sink.jsonl",
        "preview.markdown",
    } <= manifest_ids
    assert registry.get("source.local").tier is PluginTier.BUILTIN
    assert registry.get("vector.pgvector").status is PluginStatus.READY
    assert registry.get("model.ollama").tier is PluginTier.OFFICIAL
    assert registry.get("model.ollama").status is PluginStatus.READY
    assert registry.get("embedding.bge").tier is PluginTier.OFFICIAL
    assert registry.get("embedding.bge").status is PluginStatus.READY
    assert registry.get("source.s3").tier is PluginTier.OFFICIAL
    assert registry.get("source.s3").status is PluginStatus.UNAVAILABLE


def test_manifest_rejects_unknown_capabilities_for_documented_plugin_types() -> None:
    with pytest.raises(ValueError, match="capabilities"):
        PluginManifest(
            plugin_id="source.invalid",
            display_name="Invalid Source",
            description="broken",
            plugin_type="source",
            family="invalid",
            version="0.1.0",
            owner="ragrig-core",
            tier="builtin",
            status="ready",
            capabilities=[Capability.VECTOR_WRITE],
            docs_reference="README.md",
        )


def test_manifest_rejects_invalid_plugin_id_manifest_version_and_orphan_example_config() -> None:
    valid = PluginManifest(
        manifest_version=1,
        plugin_id="source.valid",
        display_name="Valid Source",
        description="valid",
        plugin_type="source",
        family="valid",
        version="0.1.0",
        owner="ragrig-core",
        tier="builtin",
        status="ready",
        capabilities=[Capability.READ],
        docs_reference="README.md",
    )

    assert valid.manifest_version == 1

    with pytest.raises(ValueError, match="plugin_id"):
        PluginManifest(
            plugin_id="Source Invalid",
            display_name="Invalid Plugin Id",
            description="broken",
            plugin_type="source",
            family="invalid",
            version="0.1.0",
            owner="ragrig-core",
            tier="builtin",
            status="ready",
            capabilities=[Capability.READ],
            docs_reference="README.md",
        )

    with pytest.raises(ValueError, match="manifest_version"):
        PluginManifest(
            manifest_version=2,
            plugin_id="source.invalid",
            display_name="Invalid Manifest Version",
            description="broken",
            plugin_type="source",
            family="invalid",
            version="0.1.0",
            owner="ragrig-core",
            tier="builtin",
            status="ready",
            capabilities=[Capability.READ],
            docs_reference="README.md",
        )

    with pytest.raises(ValueError, match="example_config requires a config_model"):
        PluginManifest(
            plugin_id="source.invalid",
            display_name="Invalid Example Config",
            description="broken",
            plugin_type="source",
            family="invalid",
            version="0.1.0",
            owner="ragrig-core",
            tier="builtin",
            status="ready",
            capabilities=[Capability.READ],
            docs_reference="README.md",
            example_config={"root_path": "/tmp/docs"},
        )


def test_registry_rejects_duplicate_registration_and_non_configurable_payloads() -> None:
    registry = PluginRegistry()
    manifest = PluginManifest(
        plugin_id="preview.example",
        display_name="Example Preview",
        description="preview plugin",
        plugin_type="preview",
        family="example",
        version="0.1.0",
        owner="ragrig-core",
        tier="builtin",
        status="ready",
        capabilities=[Capability.PREVIEW_READ],
        docs_reference="README.md",
    )

    registry.register(manifest)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(manifest)

    with pytest.raises(PluginConfigValidationError, match="not configurable"):
        registry.validate_config("preview.example", {"draft": True})


def test_config_validation_forbids_unknown_fields_and_undeclared_secret_references() -> None:
    registry = get_plugin_registry()

    with pytest.raises(PluginConfigValidationError, match="extra_forbidden"):
        registry.validate_config(
            "source.local",
            {"root_path": "/tmp/docs", "unexpected": True},
        )

    with pytest.raises(PluginConfigValidationError, match="undeclared secret"):
        registry.validate_config(
            "source.s3",
            {
                "bucket": "docs",
                "access_key": "env:AWS_ACCESS_KEY_ID",
                "secret_key": "env:UNDECLARED_SECRET",
            },
        )


def test_secret_reference_scan_handles_nested_lists() -> None:
    registry = PluginRegistry()
    manifest = PluginManifest(
        plugin_id="sink.nested",
        display_name="Nested Sink",
        description="sink plugin",
        plugin_type="sink",
        family="nested",
        version="0.1.0",
        owner="ragrig-core",
        tier="builtin",
        status="ready",
        capabilities=[Capability.WRITE],
        docs_reference="README.md",
        secret_requirements=[
            {"name": "DECLARED_SECRET", "description": "declared"},
        ],
    )

    assert registry._collect_secret_references(
        {"nested": ["env:DECLARED_SECRET", {"value": "env:ANOTHER_SECRET"}]}
    ) == ["DECLARED_SECRET", "ANOTHER_SECRET"]

    with pytest.raises(PluginConfigValidationError, match="undeclared secret"):
        registry._validate_secret_references(
            manifest,
            {"nested": ["env:DECLARED_SECRET", {"value": "env:ANOTHER_SECRET"}]},
        )


def test_registry_discovery_reports_status_dependencies_and_secret_requirements(
    monkeypatch,
) -> None:
    registry = get_plugin_registry()

    def _fake_dependency_check(import_name: str) -> bool:
        return import_name not in {"FlagEmbedding", "boto3", "googleapiclient"}

    monkeypatch.setattr("ragrig.plugins.guards.is_dependency_available", _fake_dependency_check)

    discovery = {item["plugin_id"]: item for item in registry.list_discovery()}

    assert discovery["source.local"]["status"] == "ready"
    assert discovery["source.local"]["configurable"] is True
    assert discovery["source.local"]["missing_dependencies"] == []
    assert discovery["model.ollama"]["status"] == "ready"
    assert discovery["model.ollama"]["missing_dependencies"] == []
    assert discovery["model.lm_studio"]["status"] == "ready"
    assert discovery["model.lm_studio"]["configurable"] is True
    assert discovery["embedding.bge"]["status"] == "unavailable"
    assert discovery["embedding.bge"]["missing_dependencies"] == ["FlagEmbedding"]
    assert discovery["source.s3"]["status"] == "unavailable"
    assert discovery["source.s3"]["missing_dependencies"] == ["boto3"]
    assert discovery["source.s3"]["secret_requirements"] == [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    ]
    assert discovery["source.google_workspace"]["missing_dependencies"] == ["googleapiclient"]


def test_registry_contract_checks_cover_manifests_docs_and_validation() -> None:
    assert_registry_contracts(get_plugin_registry(), repo_root=REPO_ROOT)


def test_docs_reference_check_accepts_https_and_rejects_missing_local_paths() -> None:
    assert _is_valid_docs_reference("https://example.com/spec", repo_root=REPO_ROOT) is True
    assert _is_valid_docs_reference("docs/specs/does-not-exist.md", repo_root=REPO_ROOT) is False


@pytest.mark.anyio
async def test_plugins_endpoint_exposes_registry_status(tmp_path) -> None:
    app = create_app(
        check_database=lambda: None,
        session_factory=_create_file_session_factory(tmp_path / "plugins-api.db"),
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/plugins")

    assert response.status_code == 200
    payload = response.json()
    assert {item["plugin_id"] for item in payload["items"]} >= {
        "source.local",
        "vector.pgvector",
        "source.s3",
    }
    source_s3 = next(item for item in payload["items"] if item["plugin_id"] == "source.s3")
    assert source_s3["status"] == "unavailable"
    assert source_s3["configurable"] is True
    assert "AWS_ACCESS_KEY_ID" in source_s3["secret_requirements"]
