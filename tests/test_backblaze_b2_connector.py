from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from ragrig.db.models import PipelineRun, Source
from ragrig.plugins import PluginConfigValidationError, build_plugin_registry
from ragrig.plugins.sources.backblaze_b2.connector import _resolve_env_ref
from ragrig.plugins.sources.backblaze_b2.errors import (
    BackblazeB2AuthError,
    BackblazeB2ConfigError,
)
from ragrig.plugins.sources.s3.client import FakeS3Client, FakeS3Object

pytestmark = pytest.mark.unit


def _source_config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "region": "us-west-004",
        "key_id": "env:B2_APPLICATION_KEY_ID",
        "application_key": "env:B2_APPLICATION_KEY",
        "bucket": "docs",
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
        "region": "us-west-004",
        "key_id": "env:B2_APPLICATION_KEY_ID",
        "application_key": "env:B2_APPLICATION_KEY",
        "bucket": "exports",
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


def test_b2_source_config_validation_rejects_empty_region() -> None:
    registry = build_plugin_registry()

    with pytest.raises(PluginConfigValidationError):
        registry.validate_config("source.backblaze_b2", _source_config(region=""))


def test_b2_source_config_validation_rejects_invalid_region_pattern() -> None:
    registry = build_plugin_registry()

    with pytest.raises(PluginConfigValidationError, match="region must match pattern"):
        registry.validate_config("source.backblaze_b2", _source_config(region="us-east-1"))


def test_b2_source_config_validation_accepts_valid_regions() -> None:
    registry = build_plugin_registry()

    for region in ("us-west-004", "eu-central-003"):
        validated = registry.validate_config("source.backblaze_b2", _source_config(region=region))
        assert validated["region"] == region


def test_b2_source_config_validation_rejects_empty_bucket() -> None:
    registry = build_plugin_registry()

    with pytest.raises(PluginConfigValidationError, match="bucket must not be empty"):
        registry.validate_config("source.backblaze_b2", _source_config(bucket="   "))


def test_b2_source_config_validation_rejects_undeclared_secrets() -> None:
    registry = build_plugin_registry()

    with pytest.raises(PluginConfigValidationError, match="undeclared secret"):
        registry.validate_config(
            "source.backblaze_b2",
            _source_config(application_key="env:NOT_DECLARED"),
        )


def test_b2_endpoint_url_construction() -> None:
    region = "us-west-004"
    endpoint = f"https://s3.{region}.backblazeb2.com"
    assert endpoint == "https://s3.us-west-004.backblazeb2.com"

    region = "eu-central-003"
    endpoint = f"https://s3.{region}.backblazeb2.com"
    assert endpoint == "https://s3.eu-central-003.backblazeb2.com"


def test_b2_resolve_env_ref_raises_auth_error_for_missing_var() -> None:
    with pytest.raises(BackblazeB2AuthError, match="B2_APPLICATION_KEY_ID"):
        _resolve_env_ref("env:B2_APPLICATION_KEY_ID", {}, "B2_APPLICATION_KEY_ID")


def test_b2_resolve_env_ref_raises_config_error_for_non_env_ref() -> None:
    with pytest.raises(BackblazeB2ConfigError, match="must use env: references"):
        _resolve_env_ref("plaintext-key", {"B2_APPLICATION_KEY_ID": "val"}, "B2_APPLICATION_KEY_ID")


def test_b2_resolve_env_ref_resolves_correctly() -> None:
    result = _resolve_env_ref(
        "env:B2_APPLICATION_KEY_ID", {"B2_APPLICATION_KEY_ID": "mykey"}, "B2_APPLICATION_KEY_ID"
    )
    assert result == "mykey"


def test_ingest_backblaze_b2_source_discovers_and_persists(sqlite_session) -> None:
    from ragrig.plugins.sources.backblaze_b2.connector import ingest_backblaze_b2_source

    report = ingest_backblaze_b2_source(
        session=sqlite_session,
        knowledge_base_name="fixture-b2",
        config=_source_config(),
        env={
            "B2_APPLICATION_KEY_ID": "test-key-id",
            "B2_APPLICATION_KEY": "test-app-key",
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
    assert source.kind == "backblaze_b2"
    assert run.run_type == "b2_ingest"
    assert run.status == "completed"


def test_ingest_backblaze_b2_source_skips_oversized_objects(sqlite_session) -> None:
    from ragrig.plugins.sources.backblaze_b2.connector import ingest_backblaze_b2_source

    report = ingest_backblaze_b2_source(
        session=sqlite_session,
        knowledge_base_name="fixture-b2",
        config=_source_config(max_object_size_mb=0.00001),
        env={
            "B2_APPLICATION_KEY_ID": "test-key-id",
            "B2_APPLICATION_KEY": "test-app-key",
        },
        client=FakeS3Client(
            objects=[
                _object("team-a/large.md", b"x" * (2 * 1024 * 1024), etag="etag-large"),
            ]
        ),
    )

    assert report.skipped_count == 1
    assert report.created_versions == 0


def test_ingest_backblaze_b2_source_raises_auth_error_for_missing_env(sqlite_session) -> None:
    from ragrig.plugins.sources.backblaze_b2.connector import ingest_backblaze_b2_source

    with pytest.raises(BackblazeB2AuthError, match="B2_APPLICATION_KEY_ID"):
        ingest_backblaze_b2_source(
            session=sqlite_session,
            knowledge_base_name="fixture-b2",
            config=_source_config(),
            env={},
        )


def test_export_to_backblaze_b2_uploads_artifacts(sqlite_session) -> None:
    from ragrig.plugins.object_storage.client import FakeObjectStorageClient
    from ragrig.plugins.sinks.backblaze_b2.connector import export_to_backblaze_b2
    from ragrig.repositories import get_or_create_knowledge_base

    get_or_create_knowledge_base(sqlite_session, "fixture-b2-sink")
    sqlite_session.commit()

    client = FakeObjectStorageClient()
    report = export_to_backblaze_b2(
        sqlite_session,
        knowledge_base_name="fixture-b2-sink",
        config=_sink_config(),
        env={
            "B2_APPLICATION_KEY_ID": "test-key-id",
            "B2_APPLICATION_KEY": "test-app-key",
        },
        client=client,
    )

    source = sqlite_session.scalars(select(Source).where(Source.kind == "backblaze_b2_sink")).one()
    run = sqlite_session.scalars(
        select(PipelineRun).where(PipelineRun.run_type == "b2_export")
    ).one()

    assert report.uploaded_count >= 1
    assert report.failed_count == 0
    assert source.kind == "backblaze_b2_sink"
    assert run.run_type == "b2_export"
    assert run.status == "completed"


def test_export_to_backblaze_b2_dry_run_does_not_upload(sqlite_session) -> None:
    from ragrig.plugins.sinks.backblaze_b2.connector import export_to_backblaze_b2
    from ragrig.repositories import get_or_create_knowledge_base

    get_or_create_knowledge_base(sqlite_session, "fixture-b2-sink")
    sqlite_session.commit()

    report = export_to_backblaze_b2(
        sqlite_session,
        knowledge_base_name="fixture-b2-sink",
        config=_sink_config(dry_run=True),
        env={
            "B2_APPLICATION_KEY_ID": "test-key-id",
            "B2_APPLICATION_KEY": "test-app-key",
        },
    )

    assert report.dry_run is True
    assert report.uploaded_count == 0


def test_export_to_backblaze_b2_raises_auth_error_for_missing_env(sqlite_session) -> None:
    from ragrig.plugins.sinks.backblaze_b2.connector import export_to_backblaze_b2
    from ragrig.repositories import get_or_create_knowledge_base

    get_or_create_knowledge_base(sqlite_session, "fixture-b2-sink")
    sqlite_session.commit()

    with pytest.raises(BackblazeB2AuthError, match="B2_APPLICATION_KEY_ID"):
        export_to_backblaze_b2(
            sqlite_session,
            knowledge_base_name="fixture-b2-sink",
            config=_sink_config(),
            env={},
        )


def test_b2_sink_config_validation_accepts_declared_secrets() -> None:
    registry = build_plugin_registry()

    validated = registry.validate_config("sink.backblaze_b2", _sink_config())
    assert validated["key_id"] == "env:B2_APPLICATION_KEY_ID"
    assert validated["application_key"] == "env:B2_APPLICATION_KEY"


def test_b2_sink_config_validation_rejects_undeclared_secrets() -> None:
    registry = build_plugin_registry()

    with pytest.raises(PluginConfigValidationError, match="undeclared secret"):
        registry.validate_config(
            "sink.backblaze_b2",
            _sink_config(application_key="env:NOT_DECLARED"),
        )
