from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from ragrig.db.models import PipelineRun, Source
from ragrig.plugins import PluginConfigValidationError, build_plugin_registry
from ragrig.plugins.sources.azure_blob.connector import (
    FakeAzureBlobClient,
    _resolve_account_key,
    _source_uri,
)
from ragrig.plugins.sources.azure_blob.errors import AzureBlobAuthError, AzureBlobConfigError

pytestmark = pytest.mark.unit


def _source_config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "account_name": "mystorageaccount",
        "account_key": "env:AZURE_STORAGE_ACCOUNT_KEY",
        "container": "docs",
        "prefix": "team-a",
        "include_patterns": ["*.md", "*.txt"],
        "exclude_patterns": [],
        "max_object_size_mb": 1,
        "page_size": 1000,
    }
    config.update(overrides)
    return config


def _sink_config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "account_name": "mystorageaccount",
        "account_key": "env:AZURE_STORAGE_ACCOUNT_KEY",
        "container": "exports",
        "prefix": "team-a",
        "path_template": "{knowledge_base}/{run_id}/{artifact}.{format}",
        "overwrite": False,
        "dry_run": False,
        "include_retrieval_artifact": True,
        "include_markdown_summary": True,
        "parquet_export": False,
        "max_retries": 2,
        "object_metadata": {},
    }
    config.update(overrides)
    return config


def _blob(
    key: str,
    body: bytes,
    *,
    etag: str,
    last_modified: datetime | None = None,
    content_type: str | None = "text/plain",
) -> tuple[str, bytes, str, datetime, str | None]:
    return (
        key,
        body,
        etag,
        last_modified or datetime(2026, 5, 4, tzinfo=timezone.utc),
        content_type,
    )


# ---- Config Validation Tests ----


def test_azure_blob_source_config_validation_accepts_valid_config() -> None:
    registry = build_plugin_registry()
    validated = registry.validate_config("source.azure_blob", _source_config())
    assert validated["account_name"] == "mystorageaccount"
    assert validated["container"] == "docs"


def test_azure_blob_source_config_validation_rejects_empty_account_name() -> None:
    registry = build_plugin_registry()
    with pytest.raises(PluginConfigValidationError):
        registry.validate_config("source.azure_blob", _source_config(account_name=""))


def test_azure_blob_source_config_validation_rejects_empty_container() -> None:
    registry = build_plugin_registry()
    with pytest.raises(PluginConfigValidationError, match="container must not be empty"):
        registry.validate_config("source.azure_blob", _source_config(container="   "))


def test_azure_blob_source_config_validation_rejects_container_with_slash() -> None:
    registry = build_plugin_registry()
    with pytest.raises(PluginConfigValidationError, match="container must not contain"):
        registry.validate_config("source.azure_blob", _source_config(container="bad/container"))


def test_azure_blob_source_config_validation_rejects_undeclared_secrets() -> None:
    registry = build_plugin_registry()
    with pytest.raises(PluginConfigValidationError, match="undeclared secret"):
        registry.validate_config(
            "source.azure_blob",
            _source_config(account_key="env:NOT_DECLARED"),
        )


def test_azure_blob_source_config_normalizes_prefix() -> None:
    registry = build_plugin_registry()
    validated = registry.validate_config("source.azure_blob", _source_config(prefix="/team-a/"))
    assert validated["prefix"] == "team-a"


# ---- Helper Function Tests ----


def test_resolve_account_key_resolves_env_ref() -> None:
    result = _resolve_account_key(
        "env:AZURE_STORAGE_ACCOUNT_KEY",
        {"AZURE_STORAGE_ACCOUNT_KEY": "my-secret-key"},
    )
    assert result == "my-secret-key"


def test_resolve_account_key_raises_auth_error_for_missing_var() -> None:
    with pytest.raises(AzureBlobAuthError, match="AZURE_STORAGE_ACCOUNT_KEY"):
        _resolve_account_key("env:AZURE_STORAGE_ACCOUNT_KEY", {})


def test_resolve_account_key_raises_config_error_for_non_env_ref() -> None:
    with pytest.raises(AzureBlobConfigError, match="must use env: references"):
        _resolve_account_key("plaintext-key", {"AZURE_STORAGE_ACCOUNT_KEY": "val"})


def test_source_uri_without_prefix() -> None:
    assert _source_uri("mycontainer", "") == "azure-blob://mycontainer"


def test_source_uri_with_prefix() -> None:
    assert _source_uri("mycontainer", "team-a") == "azure-blob://mycontainer/team-a"


# ---- Ingestion Tests ----


def test_ingest_azure_blob_source_discovers_and_persists(sqlite_session) -> None:
    from ragrig.plugins.sources.azure_blob.connector import ingest_azure_blob_source

    report = ingest_azure_blob_source(
        session=sqlite_session,
        knowledge_base_name="fixture-azure",
        config=_source_config(),
        env={"AZURE_STORAGE_ACCOUNT_KEY": "test-account-key"},
        client=FakeAzureBlobClient(
            blobs=[
                _blob("team-a/guide.md", b"# Guide\n\nAlpha\n", etag="etag-guide"),
                _blob("team-a/notes.txt", b"plain text\n", etag="etag-notes"),
            ]
        ),
    )

    source = sqlite_session.scalars(select(Source)).one()
    run = sqlite_session.scalars(select(PipelineRun)).one()

    assert report.created_documents == 2
    assert report.created_versions == 2
    assert report.skipped_count == 0
    assert report.failed_count == 0
    assert source.kind == "azure_blob"
    assert run.run_type == "azure_blob_ingest"
    assert run.status == "completed"


def test_ingest_azure_blob_source_skips_oversized_objects(sqlite_session) -> None:
    from ragrig.plugins.sources.azure_blob.connector import ingest_azure_blob_source

    report = ingest_azure_blob_source(
        session=sqlite_session,
        knowledge_base_name="fixture-azure",
        config=_source_config(max_object_size_mb=0.00001),
        env={"AZURE_STORAGE_ACCOUNT_KEY": "test-account-key"},
        client=FakeAzureBlobClient(
            blobs=[
                _blob("team-a/large.md", b"x" * (2 * 1024 * 1024), etag="etag-large"),
            ]
        ),
    )

    assert report.skipped_count == 1
    assert report.created_versions == 0


def test_ingest_azure_blob_source_skips_excluded_patterns(sqlite_session) -> None:
    from ragrig.plugins.sources.azure_blob.connector import ingest_azure_blob_source

    report = ingest_azure_blob_source(
        session=sqlite_session,
        knowledge_base_name="fixture-azure",
        config=_source_config(exclude_patterns=["*.md"]),
        env={"AZURE_STORAGE_ACCOUNT_KEY": "test-account-key"},
        client=FakeAzureBlobClient(
            blobs=[
                _blob("team-a/guide.md", b"# Guide\n", etag="etag-guide"),
                _blob("team-a/notes.txt", b"notes\n", etag="etag-notes"),
            ]
        ),
    )

    assert report.skipped_count == 1
    assert report.created_versions == 1


def test_ingest_azure_blob_source_skips_unsupported_extensions(sqlite_session) -> None:
    from ragrig.plugins.sources.azure_blob.connector import ingest_azure_blob_source

    report = ingest_azure_blob_source(
        session=sqlite_session,
        knowledge_base_name="fixture-azure",
        config=_source_config(include_patterns=["*.md"]),
        env={"AZURE_STORAGE_ACCOUNT_KEY": "test-account-key"},
        client=FakeAzureBlobClient(
            blobs=[
                _blob("team-a/guide.md", b"# Guide\n", etag="etag-guide"),
                _blob("team-a/notes.xyz", b"unknown format\n", etag="etag-xyz"),
            ]
        ),
    )

    assert report.skipped_count == 1
    assert report.created_versions == 1


def test_ingest_azure_blob_source_raises_auth_error_for_missing_env(sqlite_session) -> None:
    from ragrig.plugins.sources.azure_blob.connector import ingest_azure_blob_source

    with pytest.raises(AzureBlobAuthError, match="AZURE_STORAGE_ACCOUNT_KEY"):
        ingest_azure_blob_source(
            session=sqlite_session,
            knowledge_base_name="fixture-azure",
            config=_source_config(),
            env={},
        )


def test_ingest_azure_blob_source_stores_source_uri_with_azure_blob_scheme(
    sqlite_session,
) -> None:
    from ragrig.plugins.sources.azure_blob.connector import ingest_azure_blob_source

    ingest_azure_blob_source(
        session=sqlite_session,
        knowledge_base_name="fixture-azure",
        config=_source_config(),
        env={"AZURE_STORAGE_ACCOUNT_KEY": "test-account-key"},
        client=FakeAzureBlobClient(blobs=[]),
    )

    source = sqlite_session.scalars(select(Source)).one()
    assert source.uri.startswith("azure-blob://")


def test_ingest_azure_blob_source_skips_unchanged_objects(sqlite_session) -> None:
    from ragrig.plugins.sources.azure_blob.connector import ingest_azure_blob_source

    blob_content = _blob("team-a/guide.md", b"# Guide\n", etag="etag-v1")
    client = FakeAzureBlobClient(blobs=[blob_content])

    report1 = ingest_azure_blob_source(
        session=sqlite_session,
        knowledge_base_name="fixture-azure",
        config=_source_config(),
        env={"AZURE_STORAGE_ACCOUNT_KEY": "test-account-key"},
        client=client,
    )

    report2 = ingest_azure_blob_source(
        session=sqlite_session,
        knowledge_base_name="fixture-azure",
        config=_source_config(),
        env={"AZURE_STORAGE_ACCOUNT_KEY": "test-account-key"},
        client=client,
    )

    assert report1.created_versions == 1
    assert report2.skipped_count == 1
    assert report2.created_versions == 0


# ---- Sink Tests ----


def test_export_to_azure_blob_uploads_artifacts(sqlite_session) -> None:
    from ragrig.plugins.object_storage.client import FakeObjectStorageClient
    from ragrig.plugins.sinks.azure_blob.connector import export_to_azure_blob
    from ragrig.repositories import get_or_create_knowledge_base

    get_or_create_knowledge_base(sqlite_session, "fixture-azure-sink")
    sqlite_session.commit()

    client = FakeObjectStorageClient()
    report = export_to_azure_blob(
        sqlite_session,
        knowledge_base_name="fixture-azure-sink",
        config=_sink_config(),
        env={"AZURE_STORAGE_ACCOUNT_KEY": "test-account-key"},
        client=client,
    )

    source = sqlite_session.scalars(select(Source).where(Source.kind == "azure_blob_sink")).one()
    run = sqlite_session.scalars(
        select(PipelineRun).where(PipelineRun.run_type == "azure_blob_export")
    ).one()

    assert report.uploaded_count >= 1
    assert report.failed_count == 0
    assert source.kind == "azure_blob_sink"
    assert run.run_type == "azure_blob_export"
    assert run.status == "completed"


def test_export_to_azure_blob_dry_run_does_not_upload(sqlite_session) -> None:
    from ragrig.plugins.sinks.azure_blob.connector import export_to_azure_blob
    from ragrig.repositories import get_or_create_knowledge_base

    get_or_create_knowledge_base(sqlite_session, "fixture-azure-sink")
    sqlite_session.commit()

    report = export_to_azure_blob(
        sqlite_session,
        knowledge_base_name="fixture-azure-sink",
        config=_sink_config(dry_run=True),
        env={"AZURE_STORAGE_ACCOUNT_KEY": "test-account-key"},
    )

    assert report.dry_run is True
    assert report.uploaded_count == 0


def test_export_to_azure_blob_raises_auth_error_for_missing_env(sqlite_session) -> None:
    from ragrig.plugins.sinks.azure_blob.connector import export_to_azure_blob
    from ragrig.repositories import get_or_create_knowledge_base

    get_or_create_knowledge_base(sqlite_session, "fixture-azure-sink")
    sqlite_session.commit()

    with pytest.raises(AzureBlobAuthError, match="AZURE_STORAGE_ACCOUNT_KEY"):
        export_to_azure_blob(
            sqlite_session,
            knowledge_base_name="fixture-azure-sink",
            config=_sink_config(),
            env={},
        )


def test_azure_blob_sink_config_validation_accepts_declared_secrets() -> None:
    registry = build_plugin_registry()
    validated = registry.validate_config("sink.azure_blob", _sink_config())
    assert validated["account_key"] == "env:AZURE_STORAGE_ACCOUNT_KEY"


def test_azure_blob_sink_config_validation_rejects_undeclared_secrets() -> None:
    registry = build_plugin_registry()
    with pytest.raises(PluginConfigValidationError, match="undeclared secret"):
        registry.validate_config(
            "sink.azure_blob",
            _sink_config(account_key="env:NOT_DECLARED"),
        )
