from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from ragrig.db.models import (
    Document,
    DocumentVersion,
    KnowledgeBase,
    PipelineRun,
    PipelineRunItem,
    Source,
)
from ragrig.plugins import Capability, PluginStatus, get_plugin_registry
from ragrig.plugins.registry import PluginConfigValidationError
from ragrig.plugins.sources.s3.client import (
    Boto3S3Client,
    FakeS3Client,
    FakeS3Object,
    ListObjectsPage,
    MissingDependencyError,
    PermanentObjectError,
    RetryableObjectError,
    S3ObjectMetadata,
    _translate_client_error,
)
from ragrig.plugins.sources.s3.config import (
    S3SourceConfig,
    redact_s3_config,
    resolve_s3_credentials,
)
from ragrig.plugins.sources.s3.connector import ingest_s3_source
from ragrig.plugins.sources.s3.errors import S3ConfigError, S3CredentialError
from ragrig.plugins.sources.s3.scanner import scan_objects


def _ts(day: int) -> datetime:
    return datetime(2026, 5, day, 12, 0, 0, tzinfo=timezone.utc)


def _config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "bucket": "docs",
        "prefix": "team",
        "endpoint_url": "http://127.0.0.1:9000",
        "region": "us-east-1",
        "use_path_style": True,
        "verify_tls": False,
        "access_key": "env:AWS_ACCESS_KEY_ID",
        "secret_key": "env:AWS_SECRET_ACCESS_KEY",
        "session_token": "env:AWS_SESSION_TOKEN",
        "include_patterns": ["*.md", "*.txt"],
        "exclude_patterns": ["team/archive/*"],
        "max_object_size_mb": 1,
        "page_size": 1,
        "max_retries": 2,
        "connect_timeout_seconds": 5,
        "read_timeout_seconds": 5,
    }
    config.update(overrides)
    return config


def _env() -> dict[str, str]:
    return {
        "AWS_ACCESS_KEY_ID": "local-access",
        "AWS_SECRET_ACCESS_KEY": "local-secret",
        "AWS_SESSION_TOKEN": "local-session",
    }


def test_source_s3_manifest_exposes_effective_readiness_and_secret_requirements(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "ragrig.plugins.official.is_dependency_available", lambda name: name != "boto3"
    )
    registry = get_plugin_registry()
    manifest = registry.get("source.s3")
    discovery = {item["plugin_id"]: item for item in registry.list_discovery()}["source.s3"]

    assert manifest.capabilities == (Capability.READ, Capability.INCREMENTAL_SYNC)
    assert manifest.docs_reference == "docs/specs/ragrig-s3-source-plugin-spec.md"
    assert manifest.status is PluginStatus.UNAVAILABLE
    assert discovery["missing_dependencies"] == ["boto3"]
    assert discovery["secret_requirements"] == [
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
    ]


def test_source_s3_config_validation_forbids_unknown_fields_and_requires_declared_env_refs() -> (
    None
):
    registry = get_plugin_registry()

    validated = registry.validate_config("source.s3", _config())
    assert validated["bucket"] == "docs"
    assert validated["page_size"] == 1

    with pytest.raises(PluginConfigValidationError, match="extra_forbidden"):
        registry.validate_config("source.s3", _config(unexpected=True))

    with pytest.raises(PluginConfigValidationError, match="undeclared secret"):
        registry.validate_config(
            "source.s3",
            _config(secret_key="env:UNDECLARED_SECRET"),
        )

    with pytest.raises(PluginConfigValidationError, match="secret values must use env"):
        registry.validate_config("source.s3", _config(access_key="plain-text"))


def test_source_s3_config_normalizes_optional_values_and_rejects_edge_cases() -> None:
    config = S3SourceConfig.model_validate(
        _config(prefix="/team/docs/", endpoint_url=" ", region=" ", session_token=None)
    )

    assert config.prefix == "team/docs"
    assert config.endpoint_url is None
    assert config.region is None
    assert config.session_token is None

    with pytest.raises(PluginConfigValidationError, match="bucket must not be empty"):
        get_plugin_registry().validate_config("source.s3", _config(bucket=" "))

    with pytest.raises(PluginConfigValidationError, match="path separators"):
        get_plugin_registry().validate_config("source.s3", _config(bucket="docs/team"))

    with pytest.raises(PluginConfigValidationError, match="prefix must not be '.'"):
        get_plugin_registry().validate_config("source.s3", _config(prefix="."))

    with pytest.raises(PluginConfigValidationError, match="http:// or https://"):
        get_plugin_registry().validate_config("source.s3", _config(endpoint_url="ftp://example"))

    with pytest.raises(PluginConfigValidationError, match="patterns must not be empty"):
        get_plugin_registry().validate_config("source.s3", _config(include_patterns=[""]))

    config = S3SourceConfig.model_validate(_config(endpoint_url=None, region=None))
    assert config.endpoint_url is None
    assert config.region is None


def test_s3_secret_resolution_and_redaction_helpers_cover_optional_and_error_paths() -> None:
    config = S3SourceConfig.model_validate(_config(session_token=None))
    credentials = resolve_s3_credentials(config, env=_env())
    assert credentials.session_token is None

    assert redact_s3_config(
        {"access_key": "plain", "secret_key": "plain2", "session_token": "plain3"}
    ) == {
        "access_key": "[redacted]",
        "secret_key": "[redacted]",
        "session_token": "[redacted]",
    }

    with pytest.raises(S3ConfigError, match="is empty"):
        resolve_s3_credentials(
            config,
            env={"AWS_ACCESS_KEY_ID": "", "AWS_SECRET_ACCESS_KEY": "x"},
        )


def test_scan_objects_supports_pagination_include_exclude_and_oversized_skip() -> None:
    client = FakeS3Client(
        [
            FakeS3Object("team/guide.md", b"# Guide\n", etag="etag-1", last_modified=_ts(1)),
            FakeS3Object("team/archive/old.md", b"# Old\n", etag="etag-2", last_modified=_ts(1)),
            FakeS3Object("team/notes.txt", b"notes\n", etag="etag-3", last_modified=_ts(2)),
            FakeS3Object(
                "team/large.txt",
                b"x" * (2 * 1024 * 1024),
                etag="etag-4",
                last_modified=_ts(2),
            ),
            FakeS3Object("team/image.png", b"png", etag="etag-5", last_modified=_ts(2)),
        ]
    )

    result = scan_objects(
        client=client,
        bucket="docs",
        prefix="team",
        include_patterns=["*.md", "*.txt"],
        exclude_patterns=["team/archive/*"],
        max_object_size_bytes=1024 * 1024,
        page_size=2,
    )

    assert [item.object_metadata.key for item in result.discovered] == [
        "team/guide.md",
        "team/notes.txt",
    ]
    assert [(item.object_metadata.key, item.reason) for item in result.skipped] == [
        ("team/archive/old.md", "excluded"),
        ("team/image.png", "unsupported_extension"),
        ("team/large.txt", "object_too_large"),
    ]


def test_scan_objects_skips_directory_placeholders_and_uses_default_patterns() -> None:
    client = FakeS3Client(
        [
            FakeS3Object("team/folder/", b"", etag="etag-dir", last_modified=_ts(1)),
            FakeS3Object("team/readme.text", b"hello\n", etag="etag-text", last_modified=_ts(1)),
        ]
    )

    result = scan_objects(
        client=client,
        bucket="docs",
        prefix="team",
        include_patterns=None,
        exclude_patterns=None,
        max_object_size_bytes=1024,
        page_size=100,
    )

    assert [item.object_metadata.key for item in result.discovered] == ["team/readme.text"]
    assert result.skipped == []


def test_fake_s3_client_list_error_is_propagated() -> None:
    client = FakeS3Client([], list_error=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        client.list_objects(bucket="docs", prefix="", continuation_token=None, page_size=10)


def test_ingest_s3_source_persists_documents_versions_run_items_and_skips_unchanged(
    sqlite_session,
) -> None:
    client = FakeS3Client(
        [
            FakeS3Object(
                "team/guide.md",
                b"# Guide\n\nAlpha\n",
                etag="etag-guide-v1",
                last_modified=_ts(1),
                content_type="text/markdown",
            ),
            FakeS3Object(
                "team/notes.txt",
                b"plain text\n",
                etag="etag-notes-v1",
                last_modified=_ts(1),
                content_type="text/plain",
            ),
            FakeS3Object(
                "team/skip.txt",
                b"\x00\x01binary",
                etag="etag-bin",
                last_modified=_ts(1),
                content_type="application/octet-stream",
            ),
        ]
    )

    first = ingest_s3_source(
        sqlite_session,
        knowledge_base_name="default",
        config=_config(exclude_patterns=[]),
        client=client,
        env=_env(),
    )
    second = ingest_s3_source(
        sqlite_session,
        knowledge_base_name="default",
        config=_config(exclude_patterns=[]),
        client=client,
        env=_env(),
    )

    documents = sqlite_session.scalars(select(Document).order_by(Document.uri)).all()
    versions = sqlite_session.scalars(
        select(DocumentVersion).order_by(
            DocumentVersion.document_id, DocumentVersion.version_number
        )
    ).all()
    runs = sqlite_session.scalars(select(PipelineRun).order_by(PipelineRun.started_at)).all()
    run_items = sqlite_session.scalars(
        select(PipelineRunItem).order_by(PipelineRunItem.started_at, PipelineRunItem.status)
    ).all()
    source = sqlite_session.scalars(select(Source)).one()

    assert first.created_documents == 3
    assert first.created_versions == 2
    assert first.skipped_count == 1
    assert first.failed_count == 0
    assert second.created_versions == 0
    assert second.skipped_count == 3
    assert source.kind == "s3"
    assert source.uri == "s3://docs/team"
    assert source.config_json["access_key"] == "env:AWS_ACCESS_KEY_ID"
    assert [document.uri for document in documents] == [
        "s3://docs/team/guide.md",
        "s3://docs/team/notes.txt",
        "s3://docs/team/skip.txt",
    ]
    assert len(versions) == 2
    assert versions[0].parser_config_json["plugin_id"] in {"parser.markdown", "parser.text"}
    assert documents[0].metadata_json["object_key"] == "team/guide.md"
    assert documents[0].metadata_json["parser_metadata"]["extension"] == ".md"
    assert documents[2].metadata_json["skip_reason"] == "binary_file"
    assert [run.run_type for run in runs] == ["s3_ingest", "s3_ingest"]
    assert sorted(item.status for item in run_items) == [
        "skipped",
        "skipped",
        "skipped",
        "skipped",
        "success",
        "success",
    ]
    unchanged_items = [
        item for item in run_items if item.metadata_json.get("skip_reason") == "unchanged"
    ]
    assert len(unchanged_items) == 3


def test_ingest_s3_source_creates_new_version_when_snapshot_changes(sqlite_session) -> None:
    initial_client = FakeS3Client(
        [
            FakeS3Object(
                "team/guide.md",
                b"# Guide\n\nAlpha\n",
                etag="etag-guide-v1",
                last_modified=_ts(1),
                content_type="text/markdown",
            )
        ]
    )
    updated_client = FakeS3Client(
        [
            FakeS3Object(
                "team/guide.md",
                b"# Guide\n\nUpdated\n",
                etag="etag-guide-v2",
                last_modified=_ts(2),
                content_type="text/markdown",
            )
        ]
    )

    ingest_s3_source(
        sqlite_session,
        knowledge_base_name="default",
        config=_config(exclude_patterns=[]),
        client=initial_client,
        env=_env(),
    )
    report = ingest_s3_source(
        sqlite_session,
        knowledge_base_name="default",
        config=_config(exclude_patterns=[]),
        client=updated_client,
        env=_env(),
    )

    versions = sqlite_session.scalars(
        select(DocumentVersion).order_by(DocumentVersion.version_number)
    ).all()
    assert report.created_versions == 1
    assert [version.version_number for version in versions] == [1, 2]
    assert versions[-1].metadata_json["etag"] == "etag-guide-v2"


def test_ingest_s3_source_retries_retryable_failures_and_records_permanent_failure(
    sqlite_session,
) -> None:
    client = FakeS3Client(
        [
            FakeS3Object(
                "team/retry.txt",
                b"retry success\n",
                etag="etag-retry",
                last_modified=_ts(1),
                download_errors=[
                    RetryableObjectError("temporary"),
                    RetryableObjectError("temporary"),
                ],
            ),
            FakeS3Object(
                "team/fail.txt",
                b"never used\n",
                etag="etag-fail",
                last_modified=_ts(1),
                download_errors=[PermanentObjectError("permanent failure")],
            ),
        ]
    )

    report = ingest_s3_source(
        sqlite_session,
        knowledge_base_name="default",
        config=_config(exclude_patterns=[]),
        client=client,
        env=_env(),
    )

    items = sqlite_session.scalars(select(PipelineRunItem).order_by(PipelineRunItem.status)).all()
    failed_item = next(item for item in items if item.status == "failed")
    success_item = next(item for item in items if item.status == "success")
    run = sqlite_session.scalars(select(PipelineRun)).one()

    assert report.created_versions == 1
    assert report.failed_count == 1
    assert run.status == "completed_with_failures"
    assert success_item.metadata_json["object_key"] == "team/retry.txt"
    assert failed_item.metadata_json["failure_reason"] == "permanent failure"
    assert failed_item.error_message == "permanent failure"


def test_ingest_s3_source_fails_whole_run_for_config_or_credential_errors(sqlite_session) -> None:
    with pytest.raises(S3ConfigError, match="Missing required secret reference"):
        ingest_s3_source(
            sqlite_session,
            knowledge_base_name="default",
            config=_config(),
            client=FakeS3Client([]),
            env={"AWS_ACCESS_KEY_ID": "only-one-secret"},
        )

    runs = sqlite_session.scalars(select(PipelineRun)).all()
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert "AWS_SECRET_ACCESS_KEY" in runs[0].error_message


def test_ingest_s3_source_records_scan_level_skip_and_empty_prefix_uri(sqlite_session) -> None:
    client = FakeS3Client(
        [
            FakeS3Object("ignored.bin", b"\x01", etag="etag-bin", last_modified=_ts(1)),
            FakeS3Object("notes.md", b"# Notes\n", etag="etag-notes", last_modified=_ts(1)),
        ]
    )

    first = ingest_s3_source(
        sqlite_session,
        knowledge_base_name="default",
        config=_config(prefix="", include_patterns=["*.md"], exclude_patterns=[]),
        client=client,
        env=_env(),
    )
    second = ingest_s3_source(
        sqlite_session,
        knowledge_base_name="default",
        config=_config(prefix="", include_patterns=["*.md"], exclude_patterns=[]),
        client=client,
        env=_env(),
    )

    source = sqlite_session.scalars(select(Source)).one()
    skipped_document = sqlite_session.scalars(
        select(Document).where(Document.uri == "s3://docs/ignored.bin")
    ).one()

    assert source.uri == "s3://docs"
    assert first.created_documents == 2
    assert second.created_documents == 0
    assert skipped_document.metadata_json["skip_reason"] == "unsupported_extension"


def test_ingest_s3_source_sanitizes_scan_errors_and_handles_retry_exhaustion(sqlite_session) -> None:
    failing_client = FakeS3Client([], list_error=S3CredentialError("local-secret was rejected"))

    with pytest.raises(S3CredentialError, match="rejected"):
        ingest_s3_source(
            sqlite_session,
            knowledge_base_name="default",
            config=_config(),
            client=failing_client,
            env=_env(),
        )

    failed_run = sqlite_session.scalars(select(PipelineRun).order_by(PipelineRun.started_at)).first()
    assert failed_run is not None
    assert failed_run.error_message == "[redacted] was rejected"

    retry_client = FakeS3Client(
        [
            FakeS3Object(
                "team/retry.txt",
                b"never used",
                etag="etag-retry",
                last_modified=_ts(2),
                download_errors=[
                    RetryableObjectError("try-1"),
                    RetryableObjectError("try-2"),
                    RetryableObjectError("try-3"),
                ],
            )
        ]
    )
    report = ingest_s3_source(
        sqlite_session,
        knowledge_base_name="default-retry",
        config=_config(exclude_patterns=[]),
        client=retry_client,
        env=_env(),
    )
    retry_run = sqlite_session.execute(
        select(PipelineRun)
        .join(KnowledgeBase, KnowledgeBase.id == PipelineRun.knowledge_base_id)
        .where(KnowledgeBase.name == "default-retry")
    ).scalar_one()

    assert report.failed_count == 1
    assert retry_run is not None
    assert retry_run.status == "completed_with_failures"


def test_boto3_client_missing_dependency_guard_raises_clean_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "ragrig.plugins.sources.s3.client.import_module",
        lambda name: (_ for _ in ()).throw(ModuleNotFoundError(name)),
    )

    with pytest.raises(MissingDependencyError, match=r"ragrig\[s3\]"):
        Boto3S3Client(
            config=S3SourceConfig.model_validate(_config()),
            credentials=object(),  # type: ignore[arg-type]
        )


def test_boto3_client_success_and_error_translation_paths(monkeypatch, tmp_path) -> None:
    class FakeNoCredentialsError(Exception):
        pass

    class FakePartialCredentialsError(Exception):
        pass

    class FakeClientError(Exception):
        def __init__(self, code: str):
            self.response = {"Error": {"Code": code}}

    class FakeConfig:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeRuntimeClient:
        def __init__(self):
            self.downloaded: list[tuple[str, str, str]] = []

        def list_objects_v2(self, **kwargs):
            assert kwargs["Bucket"] == "docs"
            return {
                "Contents": [
                    {
                        "Key": "team/readme.md",
                        "ETag": '"etag-1"',
                        "LastModified": _ts(3),
                        "Size": 7,
                        "ContentType": "text/markdown",
                    }
                ],
                "NextContinuationToken": "next-token",
            }

        def download_file(self, bucket, key, destination):
            self.downloaded.append((bucket, key, destination))
            Path(destination).write_text("hello\n", encoding="utf-8")

    fake_runtime_client = FakeRuntimeClient()

    class FakeSession:
        def client(self, *_args, **_kwargs):
            return fake_runtime_client

    fake_boto3 = SimpleNamespace(session=SimpleNamespace(Session=lambda: FakeSession()))
    fake_config_module = SimpleNamespace(Config=FakeConfig)
    fake_exceptions = SimpleNamespace(
        NoCredentialsError=FakeNoCredentialsError,
        PartialCredentialsError=FakePartialCredentialsError,
        ClientError=FakeClientError,
    )

    def fake_import_module(name: str):
        if name == "boto3":
            return fake_boto3
        if name == "botocore.config":
            return fake_config_module
        if name == "botocore.exceptions":
            return fake_exceptions
        raise AssertionError(name)

    monkeypatch.setattr("ragrig.plugins.sources.s3.client.import_module", fake_import_module)

    config = S3SourceConfig.model_validate(_config())
    credentials = resolve_s3_credentials(config, env=_env())
    client = Boto3S3Client(config=config, credentials=credentials)
    page = client.list_objects(bucket="docs", prefix="team", continuation_token=None, page_size=10)
    destination = tmp_path / "download.txt"
    client.download_object(bucket="docs", key="team/readme.md", destination=destination)

    assert isinstance(page, ListObjectsPage)
    assert page.continuation_token == "next-token"
    assert page.objects == [
        S3ObjectMetadata(
            key="team/readme.md",
            etag="etag-1",
            last_modified=_ts(3),
            size=7,
            content_type="text/markdown",
        )
    ]
    assert destination.read_text(encoding="utf-8") == "hello\n"

    class NoCredentialsClient(FakeRuntimeClient):
        def list_objects_v2(self, **kwargs):
            raise FakeNoCredentialsError()

    class PartialCredentialsListClient(FakeRuntimeClient):
        def list_objects_v2(self, **kwargs):
            raise FakePartialCredentialsError()

    class PartialCredentialsClient(FakeRuntimeClient):
        def download_file(self, bucket, key, destination):
            raise FakePartialCredentialsError()

    class NoCredentialsDownloadClient(FakeRuntimeClient):
        def download_file(self, bucket, key, destination):
            raise FakeNoCredentialsError()

    client._client = NoCredentialsClient()
    with pytest.raises(S3CredentialError, match="invalid or missing"):
        client.list_objects(bucket="docs", prefix="team", continuation_token=None, page_size=10)

    client._client = PartialCredentialsListClient()
    with pytest.raises(S3CredentialError, match="incomplete"):
        client.list_objects(bucket="docs", prefix="team", continuation_token=None, page_size=10)

    class ClientErrorListClient(FakeRuntimeClient):
        def list_objects_v2(self, **kwargs):
            raise FakeClientError("SlowDown")

    client._client = ClientErrorListClient()
    with pytest.raises(RetryableObjectError, match="bucket listing"):
        client.list_objects(bucket="docs", prefix="team", continuation_token=None, page_size=10)

    client._client = PartialCredentialsClient()
    with pytest.raises(S3CredentialError, match="incomplete"):
        client.download_object(bucket="docs", key="team/readme.md", destination=destination)

    client._client = NoCredentialsDownloadClient()
    with pytest.raises(S3CredentialError, match="invalid or missing"):
        client.download_object(bucket="docs", key="team/readme.md", destination=destination)

    class ClientErrorDownloadClient(FakeRuntimeClient):
        def download_file(self, bucket, key, destination):
            raise FakeClientError("Other")

    client._client = ClientErrorDownloadClient()
    with pytest.raises(PermanentObjectError, match="team/readme.md"):
        client.download_object(bucket="docs", key="team/readme.md", destination=destination)

    with pytest.raises(S3CredentialError, match="rejected"):
        _translate_client_error(FakeClientError("InvalidAccessKeyId"), key=None)
    with pytest.raises(S3ConfigError, match="invalid"):
        _translate_client_error(FakeClientError("NoSuchBucket"), key=None)
    with pytest.raises(RetryableObjectError, match="Transient S3 error"):
        _translate_client_error(FakeClientError("SlowDown"), key="team/readme.md")
    with pytest.raises(PermanentObjectError, match="Failed to read team/readme.md"):
        _translate_client_error(FakeClientError("Other"), key="team/readme.md")


def test_ingest_s3_source_builds_real_boto3_client_when_client_not_supplied(
    sqlite_session, monkeypatch
) -> None:
    created: dict[str, object] = {}

    class RecordingClient:
        def __init__(self, *, config, credentials):
            created["config"] = config
            created["credentials"] = credentials

        def list_objects(self, *, bucket, prefix, continuation_token, page_size):
            return ListObjectsPage(objects=[])

        def download_object(self, *, bucket, key, destination):  # pragma: no cover
            raise AssertionError("download should not be called")

    monkeypatch.setattr("ragrig.plugins.sources.s3.connector.Boto3S3Client", RecordingClient)

    report = ingest_s3_source(
        sqlite_session,
        knowledge_base_name="default",
        config=_config(),
        client=None,
        env=_env(),
    )

    assert report.created_versions == 0
    assert created["config"].bucket == "docs"
    assert created["credentials"].access_key == "local-access"
