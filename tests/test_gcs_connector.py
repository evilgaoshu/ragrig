from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from ragrig.db.models import PipelineRun, Source
from ragrig.plugins import PluginConfigValidationError, build_plugin_registry
from ragrig.plugins.sources.gcs.connector import _GCS_ENDPOINT_URL, _resolve_env_ref
from ragrig.plugins.sources.gcs.errors import GcsAuthError, GcsConfigError
from ragrig.plugins.sources.s3.client import FakeS3Client, FakeS3Object

pytestmark = pytest.mark.unit


def _source_config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "access_key": "env:GCS_ACCESS_KEY",
        "secret_key": "env:GCS_SECRET_KEY",
        "bucket": "my-gcs-bucket",
        "prefix": "team-a",
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
        "access_key": "env:GCS_ACCESS_KEY",
        "secret_key": "env:GCS_SECRET_KEY",
        "bucket": "my-gcs-exports",
        "prefix": "team-a",
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


# ---- Config Validation Tests ----


def test_gcs_source_config_validation_accepts_valid_config() -> None:
    registry = build_plugin_registry()
    validated = registry.validate_config("source.gcs", _source_config())
    assert validated["bucket"] == "my-gcs-bucket"
    assert validated["access_key"] == "env:GCS_ACCESS_KEY"


def test_gcs_source_config_validation_rejects_empty_bucket() -> None:
    registry = build_plugin_registry()
    with pytest.raises(PluginConfigValidationError, match="bucket must not be empty"):
        registry.validate_config("source.gcs", _source_config(bucket="   "))


def test_gcs_source_config_validation_rejects_bucket_with_slash() -> None:
    registry = build_plugin_registry()
    with pytest.raises(PluginConfigValidationError, match="bucket must not contain"):
        registry.validate_config("source.gcs", _source_config(bucket="bad/bucket"))


def test_gcs_source_config_normalizes_prefix() -> None:
    registry = build_plugin_registry()
    validated = registry.validate_config("source.gcs", _source_config(prefix="/team-a/"))
    assert validated["prefix"] == "team-a"


def test_gcs_source_config_validation_rejects_undeclared_secrets() -> None:
    registry = build_plugin_registry()
    with pytest.raises(PluginConfigValidationError, match="undeclared secret"):
        registry.validate_config("source.gcs", _source_config(access_key="env:NOT_DECLARED"))


def test_gcs_source_config_validation_accepts_optional_project_id() -> None:
    registry = build_plugin_registry()
    validated = registry.validate_config("source.gcs", _source_config(project_id="my-gcp-project"))
    assert validated["project_id"] == "my-gcp-project"


# ---- Helper Function Tests ----


def test_gcs_resolve_env_ref_resolves_correctly() -> None:
    result = _resolve_env_ref("env:GCS_ACCESS_KEY", {"GCS_ACCESS_KEY": "mykey"}, "GCS_ACCESS_KEY")
    assert result == "mykey"


def test_gcs_resolve_env_ref_raises_auth_error_for_missing_var() -> None:
    with pytest.raises(GcsAuthError, match="GCS_ACCESS_KEY"):
        _resolve_env_ref("env:GCS_ACCESS_KEY", {}, "GCS_ACCESS_KEY")


def test_gcs_resolve_env_ref_raises_config_error_for_non_env_ref() -> None:
    with pytest.raises(GcsConfigError, match="must use env: references"):
        _resolve_env_ref("plaintext-key", {"GCS_ACCESS_KEY": "val"}, "GCS_ACCESS_KEY")


def test_gcs_uses_correct_endpoint_url() -> None:
    assert _GCS_ENDPOINT_URL == "https://storage.googleapis.com"


# ---- Ingestion Tests ----


def test_ingest_gcs_source_discovers_and_persists(sqlite_session) -> None:
    from ragrig.plugins.sources.gcs.connector import ingest_gcs_source

    report = ingest_gcs_source(
        session=sqlite_session,
        knowledge_base_name="fixture-gcs",
        config=_source_config(),
        env={
            "GCS_ACCESS_KEY": "test-access-key",
            "GCS_SECRET_KEY": "test-secret-key",
        },
        client=FakeS3Client(
            objects=[
                _object("team-a/guide.md", b"# Guide\n\nAlpha\n", etag="etag-guide"),
                _object("team-a/notes.txt", b"plain text\n", etag="etag-notes"),
            ]
        ),
    )

    source = sqlite_session.scalars(select(Source)).one()
    run = sqlite_session.scalars(select(PipelineRun)).one()

    assert report.created_documents == 2
    assert report.created_versions == 2
    assert report.skipped_count == 0
    assert report.failed_count == 0
    assert source.kind == "gcs"
    assert run.run_type == "gcs_ingest"
    assert run.status == "completed"


def test_ingest_gcs_source_skips_oversized_objects(sqlite_session) -> None:
    from ragrig.plugins.sources.gcs.connector import ingest_gcs_source

    report = ingest_gcs_source(
        session=sqlite_session,
        knowledge_base_name="fixture-gcs",
        config=_source_config(max_object_size_mb=0.00001),
        env={
            "GCS_ACCESS_KEY": "test-access-key",
            "GCS_SECRET_KEY": "test-secret-key",
        },
        client=FakeS3Client(
            objects=[
                _object("team-a/large.md", b"x" * (2 * 1024 * 1024), etag="etag-large"),
            ]
        ),
    )

    assert report.skipped_count == 1
    assert report.created_versions == 0


def test_ingest_gcs_source_raises_auth_error_for_missing_env(sqlite_session) -> None:
    from ragrig.plugins.sources.gcs.connector import ingest_gcs_source

    with pytest.raises(GcsAuthError, match="GCS_ACCESS_KEY"):
        ingest_gcs_source(
            session=sqlite_session,
            knowledge_base_name="fixture-gcs",
            config=_source_config(),
            env={},
        )


def test_ingest_gcs_source_raises_config_error_for_non_env_ref(sqlite_session) -> None:
    from ragrig.plugins.sources.gcs.connector import ingest_gcs_source

    with pytest.raises(GcsConfigError, match="must use env: references"):
        ingest_gcs_source(
            session=sqlite_session,
            knowledge_base_name="fixture-gcs",
            config=_source_config(access_key="plaintext-key"),
            env={
                "GCS_ACCESS_KEY": "test-access-key",
                "GCS_SECRET_KEY": "test-secret-key",
            },
        )


def test_ingest_gcs_source_stores_gcs_source_kind(sqlite_session) -> None:
    from ragrig.plugins.sources.gcs.connector import ingest_gcs_source

    ingest_gcs_source(
        session=sqlite_session,
        knowledge_base_name="fixture-gcs",
        config=_source_config(),
        env={
            "GCS_ACCESS_KEY": "test-access-key",
            "GCS_SECRET_KEY": "test-secret-key",
        },
        client=FakeS3Client(objects=[]),
    )

    source = sqlite_session.scalars(select(Source)).one()
    assert source.kind == "gcs"


# ---- Sink Tests ----


def test_export_to_gcs_uploads_artifacts(sqlite_session) -> None:
    from ragrig.plugins.object_storage.client import FakeObjectStorageClient
    from ragrig.plugins.sinks.gcs.connector import export_to_gcs
    from ragrig.repositories import get_or_create_knowledge_base

    get_or_create_knowledge_base(sqlite_session, "fixture-gcs-sink")
    sqlite_session.commit()

    client = FakeObjectStorageClient()
    report = export_to_gcs(
        sqlite_session,
        knowledge_base_name="fixture-gcs-sink",
        config=_sink_config(),
        env={
            "GCS_ACCESS_KEY": "test-access-key",
            "GCS_SECRET_KEY": "test-secret-key",
        },
        client=client,
    )

    source = sqlite_session.scalars(select(Source).where(Source.kind == "gcs_sink")).one()
    run = sqlite_session.scalars(
        select(PipelineRun).where(PipelineRun.run_type == "gcs_export")
    ).one()

    assert report.uploaded_count >= 1
    assert report.failed_count == 0
    assert source.kind == "gcs_sink"
    assert run.run_type == "gcs_export"
    assert run.status == "completed"


def test_export_to_gcs_dry_run_does_not_upload(sqlite_session) -> None:
    from ragrig.plugins.sinks.gcs.connector import export_to_gcs
    from ragrig.repositories import get_or_create_knowledge_base

    get_or_create_knowledge_base(sqlite_session, "fixture-gcs-sink")
    sqlite_session.commit()

    report = export_to_gcs(
        sqlite_session,
        knowledge_base_name="fixture-gcs-sink",
        config=_sink_config(dry_run=True),
        env={
            "GCS_ACCESS_KEY": "test-access-key",
            "GCS_SECRET_KEY": "test-secret-key",
        },
    )

    assert report.dry_run is True
    assert report.uploaded_count == 0


def test_export_to_gcs_raises_auth_error_for_missing_env(sqlite_session) -> None:
    from ragrig.plugins.sinks.gcs.connector import export_to_gcs
    from ragrig.repositories import get_or_create_knowledge_base

    get_or_create_knowledge_base(sqlite_session, "fixture-gcs-sink")
    sqlite_session.commit()

    with pytest.raises(GcsAuthError, match="GCS_ACCESS_KEY"):
        export_to_gcs(
            sqlite_session,
            knowledge_base_name="fixture-gcs-sink",
            config=_sink_config(),
            env={},
        )


def test_gcs_sink_config_validation_accepts_declared_secrets() -> None:
    registry = build_plugin_registry()
    validated = registry.validate_config("sink.gcs", _sink_config())
    assert validated["access_key"] == "env:GCS_ACCESS_KEY"
    assert validated["secret_key"] == "env:GCS_SECRET_KEY"


def test_gcs_sink_config_validation_rejects_undeclared_secrets() -> None:
    registry = build_plugin_registry()
    with pytest.raises(PluginConfigValidationError, match="undeclared secret"):
        registry.validate_config(
            "sink.gcs",
            _sink_config(access_key="env:NOT_DECLARED"),
        )
