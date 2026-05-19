from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from ragrig.db.models import PipelineRun, Source
from ragrig.plugins import PluginConfigValidationError, build_plugin_registry
from ragrig.plugins.sources.cloudflare_r2.connector import _build_r2_endpoint, _resolve_env_ref
from ragrig.plugins.sources.cloudflare_r2.errors import (
    CloudflareR2AuthError,
    CloudflareR2ConfigError,
)
from ragrig.plugins.sources.s3.client import FakeS3Client, FakeS3Object

pytestmark = pytest.mark.unit


def _source_config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "account_id": "abc123def456",
        "access_key_id": "env:CF_R2_ACCESS_KEY_ID",
        "secret_access_key": "env:CF_R2_SECRET_ACCESS_KEY",
        "bucket": "docs",
        "prefix": "team-a",
        "jurisdiction": None,
        "include_patterns": ["*.md", "*.txt"],
        "exclude_patterns": [],
        "max_object_size_mb": 1,
        "page_size": 1000,
        "max_retries": 2,
    }
    config.update(overrides)
    return config


def _sink_config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "account_id": "abc123def456",
        "access_key_id": "env:CF_R2_ACCESS_KEY_ID",
        "secret_access_key": "env:CF_R2_SECRET_ACCESS_KEY",
        "bucket": "exports",
        "prefix": "team-a",
        "jurisdiction": None,
        "path_template": "{knowledge_base}/{run_id}/{artifact}.{format}",
        "overwrite": False,
        "dry_run": False,
        "include_retrieval_artifact": True,
        "include_markdown_summary": True,
        "parquet_export": False,
        "max_retries": 2,
        "connect_timeout_seconds": 5,
        "read_timeout_seconds": 10,
        "object_metadata": {},
    }
    config.update(overrides)
    return config


def _object(
    key: str,
    body: bytes,
    *,
    etag: str,
    last_modified: datetime | None = None,
    content_type: str = "text/plain",
) -> FakeS3Object:
    return FakeS3Object(
        key=key,
        body=body,
        etag=etag,
        last_modified=last_modified or datetime(2026, 5, 4, tzinfo=timezone.utc),
        content_type=content_type,
    )


def test_r2_source_config_validation_rejects_missing_account_id() -> None:
    registry = build_plugin_registry()

    with pytest.raises(PluginConfigValidationError):
        registry.validate_config("source.cloudflare_r2", _source_config(account_id=""))


def test_r2_source_config_validation_rejects_empty_bucket() -> None:
    registry = build_plugin_registry()

    with pytest.raises(PluginConfigValidationError, match="bucket must not be empty"):
        registry.validate_config("source.cloudflare_r2", _source_config(bucket="   "))


def test_r2_source_config_validation_rejects_bucket_with_slash() -> None:
    registry = build_plugin_registry()

    with pytest.raises(PluginConfigValidationError, match="bucket must not contain"):
        registry.validate_config("source.cloudflare_r2", _source_config(bucket="bad/bucket"))


def test_r2_source_config_validation_rejects_invalid_jurisdiction() -> None:
    registry = build_plugin_registry()

    with pytest.raises(PluginConfigValidationError, match="jurisdiction"):
        registry.validate_config("source.cloudflare_r2", _source_config(jurisdiction="us"))


def test_r2_source_config_validation_accepts_valid_jurisdictions() -> None:
    registry = build_plugin_registry()

    for jurisdiction in (None, "eu", "fedramp"):
        validated = registry.validate_config(
            "source.cloudflare_r2", _source_config(jurisdiction=jurisdiction)
        )
        assert validated["jurisdiction"] == jurisdiction


def test_r2_source_config_validation_rejects_undeclared_secrets() -> None:
    registry = build_plugin_registry()

    with pytest.raises(PluginConfigValidationError, match="undeclared secret"):
        registry.validate_config(
            "source.cloudflare_r2",
            _source_config(secret_access_key="env:NOT_DECLARED"),
        )


def test_r2_endpoint_url_default() -> None:
    assert _build_r2_endpoint("abc123", None) == "https://abc123.r2.cloudflarestorage.com"


def test_r2_endpoint_url_eu_jurisdiction() -> None:
    assert _build_r2_endpoint("abc123", "eu") == "https://abc123.eu.r2.cloudflarestorage.com"


def test_r2_endpoint_url_fedramp_jurisdiction() -> None:
    assert (
        _build_r2_endpoint("abc123", "fedramp") == "https://abc123.fedramp.r2.cloudflarestorage.com"
    )


def test_r2_resolve_env_ref_raises_auth_error_for_missing_var() -> None:
    with pytest.raises(CloudflareR2AuthError, match="CF_R2_ACCESS_KEY_ID"):
        _resolve_env_ref("env:CF_R2_ACCESS_KEY_ID", {}, "CF_R2_ACCESS_KEY_ID")


def test_r2_resolve_env_ref_raises_config_error_for_non_env_ref() -> None:
    with pytest.raises(CloudflareR2ConfigError, match="must use env: references"):
        _resolve_env_ref("plaintext-key", {"CF_R2_ACCESS_KEY_ID": "val"}, "CF_R2_ACCESS_KEY_ID")


def test_r2_resolve_env_ref_resolves_correctly() -> None:
    result = _resolve_env_ref(
        "env:CF_R2_ACCESS_KEY_ID", {"CF_R2_ACCESS_KEY_ID": "mykey"}, "CF_R2_ACCESS_KEY_ID"
    )
    assert result == "mykey"


def test_ingest_cloudflare_r2_source_discovers_and_persists(sqlite_session) -> None:
    from ragrig.plugins.sources.cloudflare_r2.connector import ingest_cloudflare_r2_source

    report = ingest_cloudflare_r2_source(
        session=sqlite_session,
        knowledge_base_name="fixture-r2",
        config=_source_config(),
        env={
            "CF_R2_ACCESS_KEY_ID": "test-access-key",
            "CF_R2_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=FakeS3Client(
            objects=[
                _object(
                    "team-a/guide.md",
                    b"# Guide\n\nAlpha\n",
                    etag="etag-guide-v1",
                    content_type="text/markdown",
                ),
                _object(
                    "team-a/notes.txt",
                    b"plain text\n",
                    etag="etag-notes-v1",
                    content_type="text/plain",
                ),
            ]
        ),
    )

    source = sqlite_session.scalars(select(Source)).one()
    run = sqlite_session.scalars(select(PipelineRun)).one()

    assert report.created_documents == 2
    assert report.created_versions == 2
    assert report.skipped_count == 0
    assert report.failed_count == 0
    assert source.kind == "cloudflare_r2"
    assert run.run_type == "r2_ingest"
    assert run.status == "completed"


def test_ingest_cloudflare_r2_source_skips_oversized_objects(sqlite_session) -> None:
    from ragrig.plugins.sources.cloudflare_r2.connector import ingest_cloudflare_r2_source

    report = ingest_cloudflare_r2_source(
        session=sqlite_session,
        knowledge_base_name="fixture-r2",
        config=_source_config(max_object_size_mb=0.00001),
        env={
            "CF_R2_ACCESS_KEY_ID": "test-access-key",
            "CF_R2_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=FakeS3Client(
            objects=[
                _object("team-a/large.md", b"x" * (2 * 1024 * 1024), etag="etag-large"),
            ]
        ),
    )

    assert report.skipped_count == 1
    assert report.created_versions == 0


def test_ingest_cloudflare_r2_source_uses_eu_endpoint_in_source_kind(sqlite_session) -> None:
    from ragrig.plugins.sources.cloudflare_r2.connector import ingest_cloudflare_r2_source

    report = ingest_cloudflare_r2_source(
        session=sqlite_session,
        knowledge_base_name="fixture-r2-eu",
        config=_source_config(jurisdiction="eu"),
        env={
            "CF_R2_ACCESS_KEY_ID": "test-access-key",
            "CF_R2_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=FakeS3Client(objects=[]),
    )

    source = sqlite_session.scalars(select(Source)).one()
    assert source.kind == "cloudflare_r2"
    assert report.created_versions == 0


def test_ingest_cloudflare_r2_source_raises_auth_error_for_missing_env(sqlite_session) -> None:
    from ragrig.plugins.sources.cloudflare_r2.connector import ingest_cloudflare_r2_source

    with pytest.raises(CloudflareR2AuthError, match="CF_R2_ACCESS_KEY_ID"):
        ingest_cloudflare_r2_source(
            session=sqlite_session,
            knowledge_base_name="fixture-r2",
            config=_source_config(),
            env={},
        )


def test_export_to_cloudflare_r2_uploads_artifacts(sqlite_session) -> None:
    from ragrig.plugins.object_storage.client import FakeObjectStorageClient
    from ragrig.plugins.sinks.cloudflare_r2.connector import export_to_cloudflare_r2
    from ragrig.repositories import get_or_create_knowledge_base

    get_or_create_knowledge_base(sqlite_session, "fixture-r2-sink")
    sqlite_session.commit()

    client = FakeObjectStorageClient()
    report = export_to_cloudflare_r2(
        sqlite_session,
        knowledge_base_name="fixture-r2-sink",
        config=_sink_config(),
        env={
            "CF_R2_ACCESS_KEY_ID": "test-access-key",
            "CF_R2_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=client,
    )

    source = sqlite_session.scalars(select(Source).where(Source.kind == "cloudflare_r2_sink")).one()
    run = sqlite_session.scalars(
        select(PipelineRun).where(PipelineRun.run_type == "r2_export")
    ).one()

    assert report.uploaded_count >= 1
    assert report.failed_count == 0
    assert source.kind == "cloudflare_r2_sink"
    assert run.run_type == "r2_export"
    assert run.status == "completed"


def test_export_to_cloudflare_r2_dry_run_does_not_upload(sqlite_session) -> None:
    from ragrig.plugins.sinks.cloudflare_r2.connector import export_to_cloudflare_r2
    from ragrig.repositories import get_or_create_knowledge_base

    get_or_create_knowledge_base(sqlite_session, "fixture-r2-sink")
    sqlite_session.commit()

    report = export_to_cloudflare_r2(
        sqlite_session,
        knowledge_base_name="fixture-r2-sink",
        config=_sink_config(dry_run=True),
        env={
            "CF_R2_ACCESS_KEY_ID": "test-access-key",
            "CF_R2_SECRET_ACCESS_KEY": "test-secret-key",
        },
    )

    assert report.dry_run is True
    assert report.uploaded_count == 0


def test_export_to_cloudflare_r2_raises_auth_error_for_missing_env(sqlite_session) -> None:
    from ragrig.plugins.sinks.cloudflare_r2.connector import export_to_cloudflare_r2
    from ragrig.repositories import get_or_create_knowledge_base

    get_or_create_knowledge_base(sqlite_session, "fixture-r2-sink")
    sqlite_session.commit()

    with pytest.raises(CloudflareR2AuthError, match="CF_R2_ACCESS_KEY_ID"):
        export_to_cloudflare_r2(
            sqlite_session,
            knowledge_base_name="fixture-r2-sink",
            config=_sink_config(),
            env={},
        )


def test_r2_sink_config_validation_accepts_declared_secrets() -> None:
    registry = build_plugin_registry()

    validated = registry.validate_config("sink.cloudflare_r2", _sink_config())
    assert validated["access_key_id"] == "env:CF_R2_ACCESS_KEY_ID"
    assert validated["secret_access_key"] == "env:CF_R2_SECRET_ACCESS_KEY"


def test_r2_sink_config_validation_rejects_undeclared_secrets() -> None:
    registry = build_plugin_registry()

    with pytest.raises(PluginConfigValidationError, match="undeclared secret"):
        registry.validate_config(
            "sink.cloudflare_r2",
            _sink_config(secret_access_key="env:NOT_DECLARED"),
        )
