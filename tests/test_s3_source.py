from __future__ import annotations

import sys
import types
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from ragrig.db.models import Document, DocumentVersion, PipelineRun, PipelineRunItem, Source
from ragrig.plugins import PluginConfigValidationError, PluginStatus, build_plugin_registry
from ragrig.plugins.sources.s3.client import FakeS3Client, FakeS3Object, build_boto3_client
from ragrig.plugins.sources.s3.connector import (
    _download_with_retries,
    _resolve_secrets,
    _source_uri,
    ingest_s3_source,
)
from ragrig.plugins.sources.s3.errors import (
    S3ConfigError,
    S3CredentialError,
    S3PermanentError,
    S3RetryableError,
)
from ragrig.plugins.sources.s3.scanner import scan_objects

pytestmark = pytest.mark.integration


def _config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "bucket": "docs",
        "prefix": "team-a",
        "endpoint_url": "http://localhost:9000",
        "region": "us-east-1",
        "use_path_style": True,
        "verify_tls": True,
        "access_key": "env:AWS_ACCESS_KEY_ID",
        "secret_key": "env:AWS_SECRET_ACCESS_KEY",
        "include_patterns": ["*.md", "*.txt"],
        "exclude_patterns": [],
        "max_object_size_mb": 1,
        "page_size": 1,
        "max_retries": 2,
        "connect_timeout_seconds": 5,
        "read_timeout_seconds": 10,
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


def test_s3_plugin_config_validation_forbids_unknown_fields_and_undeclared_secrets() -> None:
    registry = build_plugin_registry()

    validated = registry.validate_config(
        "source.s3",
        _config(session_token="env:AWS_SESSION_TOKEN"),
    )

    assert validated["session_token"] == "env:AWS_SESSION_TOKEN"

    with pytest.raises(PluginConfigValidationError, match="extra_forbidden"):
        registry.validate_config("source.s3", _config(unexpected=True))

    with pytest.raises(PluginConfigValidationError, match="undeclared secret"):
        registry.validate_config(
            "source.s3",
            _config(secret_key="env:NOT_DECLARED"),
        )


def test_s3_plugin_config_validation_rejects_invalid_bucket_and_patterns() -> None:
    registry = build_plugin_registry()

    with pytest.raises(PluginConfigValidationError, match="bucket must not be empty"):
        registry.validate_config("source.s3", _config(bucket="   "))

    with pytest.raises(PluginConfigValidationError, match="bucket must not contain '/'"):
        registry.validate_config("source.s3", _config(bucket="bad/bucket"))

    with pytest.raises(PluginConfigValidationError, match="glob patterns must be relative"):
        registry.validate_config("source.s3", _config(include_patterns=["/absolute/*.md"]))


def test_s3_plugin_readiness_depends_on_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("ragrig.plugins.guards.is_dependency_available", lambda import_name: False)
    unavailable_registry = build_plugin_registry()
    unavailable_manifest = unavailable_registry.get("source.s3")
    unavailable_discovery = {
        item["plugin_id"]: item for item in unavailable_registry.list_discovery()
    }["source.s3"]

    assert unavailable_manifest.status is PluginStatus.UNAVAILABLE
    assert unavailable_discovery["status"] == "unavailable"
    assert unavailable_discovery["missing_dependencies"] == ["boto3"]

    monkeypatch.setattr("ragrig.plugins.guards.is_dependency_available", lambda import_name: True)
    ready_registry = build_plugin_registry()
    ready_manifest = ready_registry.get("source.s3")

    assert ready_manifest.status is PluginStatus.READY
    assert [capability.value for capability in ready_manifest.capabilities] == [
        "read",
        "incremental_sync",
    ]


def test_ingest_s3_source_paginates_downloads_and_persists_metadata(sqlite_session) -> None:
    report = ingest_s3_source(
        session=sqlite_session,
        knowledge_base_name="fixture-s3",
        config=_config(),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
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

    documents = sqlite_session.scalars(select(Document).order_by(Document.uri)).all()
    versions = sqlite_session.scalars(
        select(DocumentVersion).order_by(DocumentVersion.version_number)
    ).all()
    run = sqlite_session.scalars(select(PipelineRun)).one()
    items = sqlite_session.scalars(
        select(PipelineRunItem).order_by(PipelineRunItem.started_at.asc())
    ).all()
    source = sqlite_session.scalars(select(Source)).one()

    assert report.created_documents == 2
    assert report.created_versions == 2
    assert report.skipped_count == 0
    assert report.failed_count == 0
    assert source.kind == "s3"
    assert source.uri == "s3://docs/team-a"
    assert source.config_json["access_key"] == "env:AWS_ACCESS_KEY_ID"
    assert run.run_type == "s3_ingest"
    assert run.status == "completed"
    assert run.total_items == 2
    assert [document.uri for document in documents] == [
        "s3://docs/team-a/guide.md",
        "s3://docs/team-a/notes.txt",
    ]
    assert [version.parser_config_json["plugin_id"] for version in versions] == [
        "parser.markdown",
        "parser.text",
    ]
    assert documents[0].metadata_json["object_key"] == "team-a/guide.md"
    assert documents[0].metadata_json["parser_metadata"]["extension"] == ".md"
    assert versions[0].metadata_json["object_snapshot"] == (
        "etag-guide-v1:2026-05-04T00:00:00+00:00:15"
    )
    assert items[0].metadata_json["object_key"] == "team-a/guide.md"
    assert items[0].metadata_json["version_number"] == 1


def test_ingest_s3_source_skips_unchanged_objects_without_new_version(sqlite_session) -> None:
    client = FakeS3Client(
        objects=[
            _object(
                "team-a/guide.md",
                b"# Guide\n",
                etag="etag-guide-v1",
                content_type="text/markdown",
            )
        ]
    )

    first_report = ingest_s3_source(
        session=sqlite_session,
        knowledge_base_name="fixture-s3",
        config=_config(),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=client,
    )
    second_report = ingest_s3_source(
        session=sqlite_session,
        knowledge_base_name="fixture-s3",
        config=_config(),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=client,
    )

    versions = sqlite_session.scalars(select(DocumentVersion)).all()
    items = sqlite_session.scalars(
        select(PipelineRunItem).order_by(PipelineRunItem.started_at.asc())
    ).all()

    assert first_report.created_versions == 1
    assert second_report.created_versions == 0
    assert second_report.skipped_count == 1
    assert len(versions) == 1
    assert items[-1].status == "skipped"
    assert items[-1].metadata_json["skip_reason"] == "unchanged"


def test_ingest_s3_source_skips_unsupported_binary_and_oversized_objects(sqlite_session) -> None:
    report = ingest_s3_source(
        session=sqlite_session,
        knowledge_base_name="fixture-s3",
        config=_config(max_object_size_mb=0.00001),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=FakeS3Client(
            objects=[
                _object("team-a/archive.pdf", b"%PDF", etag="etag-pdf"),
                _object("team-a/binary.txt", b"abc\x00def", etag="etag-binary"),
                _object("team-a/large.md", b"x" * (2 * 1024 * 1024), etag="etag-large"),
            ]
        ),
    )

    items = sqlite_session.scalars(
        select(PipelineRunItem).order_by(PipelineRunItem.started_at.asc())
    ).all()

    assert report.created_versions == 0
    assert report.skipped_count == 3
    assert sorted(item.metadata_json["skip_reason"] for item in items) == [
        "binary_file",
        "object_too_large",
        "unsupported_extension",
    ]


def test_ingest_s3_source_retries_retryable_download_errors(sqlite_session) -> None:
    report = ingest_s3_source(
        session=sqlite_session,
        knowledge_base_name="fixture-s3",
        config=_config(max_retries=2),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=FakeS3Client(
            objects=[
                _object(
                    "team-a/guide.md",
                    b"# Guide\n",
                    etag="etag-guide-v1",
                    content_type="text/markdown",
                )
            ],
            download_failures={
                "team-a/guide.md": [S3RetryableError("temporary outage")],
            },
        ),
    )

    item = sqlite_session.scalars(select(PipelineRunItem)).one()

    assert report.created_versions == 1
    assert report.failed_count == 0
    assert item.status == "success"


def test_ingest_s3_source_records_permanent_object_failures(sqlite_session) -> None:
    report = ingest_s3_source(
        session=sqlite_session,
        knowledge_base_name="fixture-s3",
        config=_config(),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=FakeS3Client(
            objects=[
                _object(
                    "team-a/good.md",
                    b"# Good\n",
                    etag="etag-good-v1",
                    content_type="text/markdown",
                ),
                _object(
                    "team-a/bad.md",
                    b"# Bad\n",
                    etag="etag-bad-v1",
                    content_type="text/markdown",
                ),
            ],
            download_failures={
                "team-a/bad.md": [S3PermanentError("object read forbidden")],
            },
        ),
    )

    run = sqlite_session.scalars(select(PipelineRun)).one()
    items = sqlite_session.scalars(
        select(PipelineRunItem).order_by(PipelineRunItem.status.asc())
    ).all()

    assert report.created_versions == 1
    assert report.failed_count == 1
    assert run.status == "completed_with_failures"
    failed_item = next(item for item in items if item.status == "failed")
    assert failed_item.metadata_json["failure_reason"] == "object_read_failed"


def test_ingest_s3_source_records_parse_failures(sqlite_session) -> None:
    report = ingest_s3_source(
        session=sqlite_session,
        knowledge_base_name="fixture-s3",
        config=_config(),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=FakeS3Client(
            objects=[
                _object(
                    "team-a/bad.txt",
                    b"\xff\xfe\xfd",
                    etag="etag-bad-v1",
                    content_type="text/plain",
                )
            ]
        ),
    )

    item = sqlite_session.scalars(select(PipelineRunItem)).one()

    assert report.failed_count == 1
    assert item.metadata_json["failure_reason"] == "parse_failed"


def test_ingest_s3_source_fails_run_on_credential_error_without_leaking_secret(
    sqlite_session,
) -> None:
    with pytest.raises(S3CredentialError, match="credentials"):
        ingest_s3_source(
            session=sqlite_session,
            knowledge_base_name="fixture-s3",
            config=_config(),
            env={
                "AWS_ACCESS_KEY_ID": "test-access-key",
                "AWS_SECRET_ACCESS_KEY": "super-secret-value",
            },
            client=FakeS3Client(
                objects=[],
                list_error=S3CredentialError("credentials rejected for super-secret-value"),
            ),
        )

    run = sqlite_session.scalars(select(PipelineRun)).one()

    assert run.status == "failed"
    assert run.error_message is not None
    assert "super-secret-value" not in run.error_message


def test_ingest_s3_source_fails_run_on_download_credential_error(sqlite_session) -> None:
    with pytest.raises(S3CredentialError, match="credentials"):
        ingest_s3_source(
            session=sqlite_session,
            knowledge_base_name="fixture-s3",
            config=_config(),
            env={
                "AWS_ACCESS_KEY_ID": "test-access-key",
                "AWS_SECRET_ACCESS_KEY": "top-secret-value",
            },
            client=FakeS3Client(
                objects=[
                    _object(
                        "team-a/guide.md",
                        b"# Guide\n",
                        etag="etag-guide-v1",
                        content_type="text/markdown",
                    )
                ],
                download_failures={
                    "team-a/guide.md": [
                        S3CredentialError("credentials rejected for top-secret-value")
                    ]
                },
            ),
        )

    run = sqlite_session.scalars(select(PipelineRun)).one()

    assert run.status == "failed"
    assert run.error_message is not None
    assert "top-secret-value" not in run.error_message


def test_s3_scanner_excludes_matching_objects() -> None:
    result = scan_objects(
        FakeS3Client(
            objects=[
                _object("team-a/keep.md", b"# Keep\n", etag="etag-keep"),
                _object("team-a/skip.md", b"# Skip\n", etag="etag-skip"),
            ]
        ),
        config=_config(exclude_patterns=["*skip.md"]),
    )

    assert [item.object_metadata.key for item in result.discovered] == ["team-a/keep.md"]
    assert [item.reason for item in result.skipped] == ["excluded"]


def test_s3_helpers_cover_secret_resolution_download_fallback_and_source_uri() -> None:
    secrets = _resolve_secrets(
        _config(session_token=None),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        },
    )

    assert secrets.session_token is None
    assert _source_uri("docs", "") == "s3://docs"

    with pytest.raises(S3ConfigError, match="missing required secret reference"):
        _resolve_secrets({**_config(), "access_key": None}, env={})

    with pytest.raises(S3ConfigError, match="must use env: references"):
        _resolve_secrets({**_config(), "access_key": "plaintext"}, env={})

    with pytest.raises(S3ConfigError, match="missing required secret env"):
        _resolve_secrets(_config(), env={})

    with pytest.raises(S3PermanentError, match="object read failed"):
        _download_with_retries(
            FakeS3Client(objects=[]),
            bucket="docs",
            key="missing.txt",
            max_retries=-1,
        )

    with pytest.raises(S3RetryableError, match="still retryable"):
        _download_with_retries(
            FakeS3Client(
                objects=[],
                download_failures={
                    "retry.txt": [S3RetryableError("still retryable")],
                },
            ),
            bucket="docs",
            key="retry.txt",
            max_retries=0,
        )


def test_fake_s3_client_raises_for_missing_object() -> None:
    client = FakeS3Client(objects=[])

    with pytest.raises(S3PermanentError, match="object not found"):
        client.download_object(bucket="docs", key="missing.txt")


@pytest.mark.parametrize(
    ("operation", "scenario", "expected_exception"),
    [
        ("list", "success", None),
        ("list", "no_credentials", S3CredentialError),
        ("list", "invalid_credentials", S3CredentialError),
        ("list", "client_error", S3PermanentError),
        ("list", "botocore_error", S3RetryableError),
        ("download", "success", None),
        ("download", "no_credentials", S3CredentialError),
        ("download", "invalid_credentials", S3CredentialError),
        ("download", "retryable_client_error", S3RetryableError),
        ("download", "client_error", S3PermanentError),
        ("download", "botocore_error", S3RetryableError),
    ],
)
def test_build_boto3_client_maps_sdk_errors(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    scenario: str,
    expected_exception: type[Exception] | None,
) -> None:
    class FakeNoCredentialsError(Exception):
        pass

    class FakeBotoCoreError(Exception):
        pass

    class FakeClientError(Exception):
        def __init__(self, code: str):
            super().__init__(code)
            self.response = {"Error": {"Code": code}}

    class FakeBody:
        def read(self) -> bytes:
            return b"payload"

    class FakeSdkClient:
        def list_objects_v2(self, **kwargs):
            del kwargs
            if scenario == "no_credentials":
                raise FakeNoCredentialsError()
            if scenario == "invalid_credentials":
                raise FakeClientError("InvalidAccessKeyId")
            if scenario == "client_error":
                raise FakeClientError("Boom")
            if scenario == "botocore_error":
                raise FakeBotoCoreError()
            return {
                "Contents": [
                    {
                        "Key": "team-a/guide.md",
                        "ETag": '"etag-guide"',
                        "LastModified": datetime(2026, 5, 4, tzinfo=timezone.utc),
                        "Size": 7,
                        "ContentType": "text/markdown",
                    }
                ],
                "NextContinuationToken": "next-token",
            }

        def get_object(self, **kwargs):
            del kwargs
            if scenario == "no_credentials":
                raise FakeNoCredentialsError()
            if scenario == "invalid_credentials":
                raise FakeClientError("AccessDenied")
            if scenario == "retryable_client_error":
                raise FakeClientError("SlowDown")
            if scenario == "client_error":
                raise FakeClientError("Boom")
            if scenario == "botocore_error":
                raise FakeBotoCoreError()
            return {"Body": FakeBody()}

    fake_sdk_client = FakeSdkClient()
    captured: dict[str, object] = {}

    class FakeSession:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def client(self, *args, **kwargs):
            captured["client_args"] = args
            captured["client_kwargs"] = kwargs
            return fake_sdk_client

    fake_boto3 = types.ModuleType("boto3")
    fake_boto3.session = types.SimpleNamespace(Session=FakeSession)

    fake_botocore = types.ModuleType("botocore")
    fake_config_module = types.ModuleType("botocore.config")
    fake_config_module.Config = lambda **kwargs: kwargs
    fake_exceptions_module = types.ModuleType("botocore.exceptions")
    fake_exceptions_module.BotoCoreError = FakeBotoCoreError
    fake_exceptions_module.ClientError = FakeClientError
    fake_exceptions_module.NoCredentialsError = FakeNoCredentialsError

    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setitem(sys.modules, "botocore", fake_botocore)
    monkeypatch.setitem(sys.modules, "botocore.config", fake_config_module)
    monkeypatch.setitem(sys.modules, "botocore.exceptions", fake_exceptions_module)

    client = build_boto3_client(
        {
            "access_key": "access",
            "secret_key": "secret",
            "session_token": "token",
            "region": "us-east-1",
            "endpoint_url": "http://localhost:9000",
            "verify_tls": False,
            "use_path_style": True,
            "max_retries": 2,
            "connect_timeout_seconds": 5,
            "read_timeout_seconds": 10,
        }
    )

    assert captured["aws_access_key_id"] == "access"
    assert captured["aws_secret_access_key"] == "secret"
    assert captured["aws_session_token"] == "token"
    assert captured["region_name"] == "us-east-1"

    if expected_exception is not None:
        with pytest.raises(expected_exception):
            if operation == "list":
                client.list_objects(
                    bucket="docs",
                    prefix="team-a",
                    continuation_token="token-1",
                    max_keys=10,
                )
            else:
                client.download_object(bucket="docs", key="team-a/guide.md")
        return

    if operation == "list":
        result = client.list_objects(
            bucket="docs",
            prefix="team-a",
            continuation_token="token-1",
            max_keys=10,
        )
        assert result.next_token == "next-token"
        assert result.objects[0].etag == "etag-guide"
    else:
        assert client.download_object(bucket="docs", key="team-a/guide.md") == b"payload"
