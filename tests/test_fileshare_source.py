from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from ragrig.db.models import Document, DocumentVersion, PipelineRun, PipelineRunItem, Source
from ragrig.plugins import PluginConfigValidationError, build_plugin_registry
from ragrig.plugins.sources.fileshare.client import FakeFileshareClient, FakeFileshareObject
from ragrig.plugins.sources.fileshare.connector import ingest_fileshare_source
from ragrig.plugins.sources.fileshare.errors import (
    FileshareConfigError,
    FileshareCredentialError,
    FilesharePermanentError,
    FileshareRetryableError,
)
from ragrig.plugins.sources.fileshare.scanner import scan_files


def _config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "protocol": "smb",
        "host": "files.example.internal",
        "share": "team-a",
        "root_path": "/engineering",
        "username": "env:FILESHARE_USERNAME",
        "password": "env:FILESHARE_PASSWORD",
        "include_patterns": ["*.md", "*.txt"],
        "exclude_patterns": [],
        "max_file_size_mb": 10,
        "page_size": 100,
        "max_retries": 2,
        "connect_timeout_seconds": 5,
        "read_timeout_seconds": 10,
        "cursor": None,
    }
    config.update(overrides)
    return config


def test_fileshare_plugin_config_validation_supports_declared_secret_refs() -> None:
    registry = build_plugin_registry()

    validated = registry.validate_config(
        "source.fileshare",
        _config(private_key="env:FILESHARE_PRIVATE_KEY"),
    )

    assert validated["username"] == "env:FILESHARE_USERNAME"
    assert validated["private_key"] == "env:FILESHARE_PRIVATE_KEY"


def test_fileshare_plugin_config_validation_rejects_unknown_fields_and_undeclared_secrets() -> None:
    registry = build_plugin_registry()

    with pytest.raises(PluginConfigValidationError, match="extra_forbidden"):
        registry.validate_config("source.fileshare", _config(unexpected=True))

    with pytest.raises(PluginConfigValidationError, match="undeclared secret"):
        registry.validate_config(
            "source.fileshare",
            _config(password="env:NOT_DECLARED"),
        )


def test_fileshare_plugin_config_validation_rejects_invalid_protocol_and_absolute_globs() -> None:
    registry = build_plugin_registry()

    with pytest.raises(PluginConfigValidationError, match="protocol"):
        registry.validate_config("source.fileshare", _config(protocol="ftp"))

    with pytest.raises(PluginConfigValidationError, match="glob patterns must be relative"):
        registry.validate_config(
            "source.fileshare",
            _config(include_patterns=["/absolute/*.md"]),
        )


def _object(
    path: str,
    body: bytes,
    *,
    modified_at: datetime | None = None,
    content_type: str = "text/plain",
    owner: str = "alice",
    group: str = "engineering",
    permissions: str = "rw-r-----",
) -> FakeFileshareObject:
    return FakeFileshareObject(
        path=path,
        body=body,
        modified_at=modified_at or datetime(2026, 5, 5, tzinfo=timezone.utc),
        content_type=content_type,
        owner=owner,
        group=group,
        permissions=permissions,
    )


def test_fileshare_scanner_applies_filters_cursor_and_delete_detection_placeholder() -> None:
    result = scan_files(
        FakeFileshareClient(
            protocol="smb",
            objects=[
                _object("docs/guide.md", b"# Guide\n", content_type="text/markdown"),
                _object("docs/notes.txt", b"notes\n"),
                _object("docs/archive.pdf", b"%PDF", content_type="application/pdf"),
                _object("docs/binary.txt", b"abc\x00def"),
                _object("docs/large.txt", b"x" * (2 * 1024 * 1024)),
            ],
        ),
        config=_config(
            root_path="/docs",
            page_size=2,
            max_file_size_mb=1,
            cursor="2026-05-04T00:00:00+00:00",
            known_document_uris=[
                "smb://files.example.internal/team-a/docs/deleted.md",
                "smb://files.example.internal/team-a/docs/guide.md",
            ],
        ),
    )

    assert [item.file_metadata.path for item in result.discovered] == [
        "docs/guide.md",
        "docs/notes.txt",
    ]
    assert sorted((item.file_metadata.path, item.reason) for item in result.skipped) == [
        ("docs/archive.pdf", "unsupported_extension"),
        ("docs/binary.txt", "binary_file"),
        ("docs/large.txt", "file_too_large"),
    ]
    assert [item.uri for item in result.deleted] == [
        "smb://files.example.internal/team-a/docs/deleted.md"
    ]
    assert result.next_cursor == "2026-05-05T00:00:00+00:00"


def test_ingest_fileshare_source_persists_documents_versions_and_protocol_metadata(
    sqlite_session,
) -> None:
    report = ingest_fileshare_source(
        session=sqlite_session,
        knowledge_base_name="fixture-fileshare",
        config=_config(),
        env={
            "FILESHARE_USERNAME": "alice",
            "FILESHARE_PASSWORD": "secret-pass",
        },
        client=FakeFileshareClient(
            protocol="smb",
            host="files.example.internal",
            share="team-a",
            objects=[
                _object("guide.md", b"# Guide\n\nAlpha\n", content_type="text/markdown"),
                _object("notes.txt", b"plain text\n"),
            ],
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
    assert source.kind == "fileshare"
    assert source.uri == "smb://files.example.internal/team-a/engineering"
    assert source.config_json["password"] == "env:FILESHARE_PASSWORD"
    assert run.run_type == "fileshare_ingest"
    assert run.status == "completed"
    assert run.config_snapshot_json["protocol"] == "smb"
    assert run.config_snapshot_json["password"] == "[secret]"
    assert [document.uri for document in documents] == [
        "smb://files.example.internal/team-a/engineering/guide.md",
        "smb://files.example.internal/team-a/engineering/notes.txt",
    ]
    assert documents[0].metadata_json["protocol"] == "smb"
    assert documents[0].metadata_json["permission_mapping"] == {
        "owner": "alice",
        "group": "engineering",
        "permissions": "rw-r-----",
        "enforcement": "not_implemented",
    }
    assert versions[0].metadata_json["source_snapshot"]
    assert items[0].metadata_json["remote_path"] == "guide.md"
    assert items[0].metadata_json["version_number"] == 1


def test_ingest_fileshare_source_skips_unchanged_and_records_delete_placeholder(
    sqlite_session,
) -> None:
    client = FakeFileshareClient(
        protocol="smb",
        host="files.example.internal",
        share="team-a",
        objects=[_object("guide.md", b"# Guide\n", content_type="text/markdown")],
    )

    first = ingest_fileshare_source(
        session=sqlite_session,
        knowledge_base_name="fixture-fileshare",
        config=_config(),
        env={
            "FILESHARE_USERNAME": "alice",
            "FILESHARE_PASSWORD": "secret-pass",
        },
        client=client,
    )
    second = ingest_fileshare_source(
        session=sqlite_session,
        knowledge_base_name="fixture-fileshare",
        config=_config(
            known_document_uris=[
                "smb://files.example.internal/team-a/engineering/guide.md",
                "smb://files.example.internal/team-a/engineering/deleted.md",
            ]
        ),
        env={
            "FILESHARE_USERNAME": "alice",
            "FILESHARE_PASSWORD": "secret-pass",
        },
        client=client,
    )

    items = sqlite_session.scalars(
        select(PipelineRunItem).order_by(PipelineRunItem.started_at.asc())
    ).all()

    assert first.created_versions == 1
    assert second.created_versions == 0
    assert second.skipped_count == 2
    assert items[-2].metadata_json["skip_reason"] == "unchanged"
    assert items[-1].metadata_json["skip_reason"] == "deleted_upstream"
    assert items[-1].metadata_json["delete_detection"] == "placeholder"


def test_ingest_fileshare_source_retries_retryable_read_failures(sqlite_session) -> None:
    report = ingest_fileshare_source(
        session=sqlite_session,
        knowledge_base_name="fixture-fileshare",
        config=_config(max_retries=2),
        env={
            "FILESHARE_USERNAME": "alice",
            "FILESHARE_PASSWORD": "secret-pass",
        },
        client=FakeFileshareClient(
            protocol="smb",
            host="files.example.internal",
            share="team-a",
            objects=[_object("guide.md", b"# Guide\n", content_type="text/markdown")],
            read_failures={"guide.md": [FileshareRetryableError("temporary outage")]},
        ),
    )

    item = sqlite_session.scalars(select(PipelineRunItem)).one()

    assert report.created_versions == 1
    assert report.failed_count == 0
    assert item.status == "success"


def test_ingest_fileshare_source_records_permanent_failures(sqlite_session) -> None:
    report = ingest_fileshare_source(
        session=sqlite_session,
        knowledge_base_name="fixture-fileshare",
        config=_config(),
        env={
            "FILESHARE_USERNAME": "alice",
            "FILESHARE_PASSWORD": "secret-pass",
        },
        client=FakeFileshareClient(
            protocol="smb",
            host="files.example.internal",
            share="team-a",
            objects=[_object("bad.md", b"# Bad\n", content_type="text/markdown")],
            read_failures={
                "bad.md": [FilesharePermanentError("permission denied for secret-pass")]
            },
        ),
    )

    run = sqlite_session.scalars(select(PipelineRun)).one()
    item = sqlite_session.scalars(select(PipelineRunItem)).one()

    assert report.failed_count == 1
    assert run.status == "completed_with_failures"
    assert item.status == "failed"
    assert item.metadata_json["failure_reason"] == "read_failed"
    assert "secret-pass" not in item.error_message


def test_ingest_fileshare_source_fails_run_on_credential_error_without_leaking_secret(
    sqlite_session,
) -> None:
    with pytest.raises(FileshareCredentialError, match="credentials"):
        ingest_fileshare_source(
            session=sqlite_session,
            knowledge_base_name="fixture-fileshare",
            config=_config(),
            env={
                "FILESHARE_USERNAME": "alice",
                "FILESHARE_PASSWORD": "top-secret-value",
            },
            client=FakeFileshareClient(
                protocol="smb",
                host="files.example.internal",
                share="team-a",
                objects=[],
                list_error=FileshareCredentialError("credentials rejected for top-secret-value"),
            ),
        )

    run = sqlite_session.scalars(select(PipelineRun)).one()

    assert run.status == "failed"
    assert run.error_message is not None
    assert "top-secret-value" not in run.error_message


def test_ingest_fileshare_source_supports_mounted_nfs_dry_run(sqlite_session, tmp_path) -> None:
    root = tmp_path / "mounted"
    root.mkdir()
    (root / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (root / "ignored.bin").write_bytes(b"\x00bad")

    report = ingest_fileshare_source(
        session=sqlite_session,
        knowledge_base_name="fixture-fileshare",
        config={
            "protocol": "nfs_mounted",
            "root_path": str(root),
            "include_patterns": ["*.md", "*.txt"],
            "exclude_patterns": [],
            "max_file_size_mb": 10,
            "page_size": 100,
            "max_retries": 1,
            "connect_timeout_seconds": 5,
            "read_timeout_seconds": 5,
            "cursor": None,
        },
        dry_run=True,
    )

    assert report.pipeline_run_id == "dry-run"
    assert report.created_documents == 0
    assert report.created_versions == 0
    assert report.skipped_count == 2
    assert report.failed_count == 0


def test_ingest_fileshare_source_rejects_missing_secret_env(sqlite_session) -> None:
    with pytest.raises(FileshareConfigError, match="missing required secret env"):
        ingest_fileshare_source(
            session=sqlite_session,
            knowledge_base_name="fixture-fileshare",
            config=_config(),
            env={"FILESHARE_USERNAME": "alice"},
            client=FakeFileshareClient(
                protocol="smb", host="files.example.internal", share="team-a"
            ),
        )


def test_fileshare_plugin_config_validation_checks_root_path_and_protocol_specific_fields() -> None:
    registry = build_plugin_registry()

    with pytest.raises(PluginConfigValidationError, match="root_path must not be empty"):
        registry.validate_config("source.fileshare", _config(root_path="   "))

    with pytest.raises(PluginConfigValidationError, match="base_url is required"):
        registry.validate_config(
            "source.fileshare",
            _config(protocol="webdav", host=None, share=None, base_url=None),
        )

    with pytest.raises(PluginConfigValidationError, match="host is required"):
        registry.validate_config(
            "source.fileshare",
            _config(protocol="sftp", host=None, share=None),
        )

    with pytest.raises(PluginConfigValidationError, match="share is required"):
        registry.validate_config(
            "source.fileshare",
            _config(protocol="smb", share=None),
        )


def test_fileshare_scanner_marks_excluded_files() -> None:
    result = scan_files(
        FakeFileshareClient(
            protocol="smb",
            objects=[_object("skip.md", b"# Skip\n", content_type="text/markdown")],
        ),
        config=_config(exclude_patterns=["skip.*"]),
    )

    assert result.discovered == []
    assert [item.reason for item in result.skipped] == ["excluded"]


def test_fileshare_helpers_cover_fake_client_and_mounted_path_edges(tmp_path) -> None:
    missing_client = FakeFileshareClient(protocol="smb", objects=[])

    with pytest.raises(FilesharePermanentError, match="file not found"):
        missing_client.read_file(path="missing.txt")

    from ragrig.plugins.sources.fileshare.client import MountedPathClient

    mounted_client = MountedPathClient(root_path=tmp_path / "missing")

    with pytest.raises(FileshareConfigError, match="scan root does not exist"):
        mounted_client.list_files(root_path="ignored", cursor=None, page_size=10)

    mounted_root = tmp_path / "mounted"
    mounted_root.mkdir()
    (mounted_root / "nested").mkdir()
    (mounted_root / "nested" / "guide.md").write_text("# Guide\n", encoding="utf-8")

    listed = MountedPathClient(root_path=mounted_root).list_files(
        root_path="ignored", cursor=None, page_size=10
    )

    assert [item.path for item in listed.files] == ["nested/guide.md"]


def test_ingest_fileshare_source_rejects_plaintext_secret_refs(sqlite_session) -> None:
    with pytest.raises(FileshareConfigError, match="must use env: references"):
        ingest_fileshare_source(
            session=sqlite_session,
            knowledge_base_name="fixture-fileshare",
            config=_config(username="alice"),
            env={"FILESHARE_PASSWORD": "secret-pass"},
            client=FakeFileshareClient(
                protocol="smb", host="files.example.internal", share="team-a"
            ),
        )


def test_ingest_fileshare_source_rejects_missing_secret_reference(sqlite_session) -> None:
    with pytest.raises(FileshareConfigError, match="missing required secret reference"):
        ingest_fileshare_source(
            session=sqlite_session,
            knowledge_base_name="fixture-fileshare",
            config=_config(username=None),
            env={"FILESHARE_PASSWORD": "secret-pass"},
            client=FakeFileshareClient(
                protocol="smb", host="files.example.internal", share="team-a"
            ),
        )


def test_ingest_fileshare_source_builds_default_nfs_client(sqlite_session, tmp_path) -> None:
    root = tmp_path / "mounted"
    root.mkdir()
    (root / "guide.md").write_text("# Guide\n", encoding="utf-8")

    report = ingest_fileshare_source(
        session=sqlite_session,
        knowledge_base_name="fixture-fileshare",
        config={
            "protocol": "nfs_mounted",
            "root_path": str(root),
            "include_patterns": ["*.md", "*.txt"],
            "exclude_patterns": [],
            "max_file_size_mb": 10,
            "page_size": 100,
            "max_retries": 1,
            "connect_timeout_seconds": 5,
            "read_timeout_seconds": 5,
            "cursor": None,
            "known_document_uris": [],
        },
    )

    run = sqlite_session.scalars(select(PipelineRun)).one()

    assert report.created_versions == 1
    assert run.status == "completed"


def test_fileshare_read_retries_raise_expected_errors() -> None:
    from ragrig.plugins.sources.fileshare.connector import _read_with_retries

    retrying_client = FakeFileshareClient(
        protocol="smb",
        read_failures={"retry.txt": [FileshareRetryableError("retry me")]},
    )

    with pytest.raises(FileshareRetryableError, match="retry me"):
        _read_with_retries(retrying_client, path="retry.txt", max_retries=0)

    with pytest.raises(FilesharePermanentError, match="file read failed"):
        _read_with_retries(
            FakeFileshareClient(protocol="smb", objects=[]),
            path="missing.txt",
            max_retries=-1,
        )


def test_fileshare_config_accepts_valid_webdav_and_helpers_cover_remote_paths() -> None:
    registry = build_plugin_registry()
    validated = registry.validate_config(
        "source.fileshare",
        _config(protocol="webdav", host=None, share=None, base_url="https://dav.example.internal"),
    )

    from ragrig.plugins.sources.fileshare.connector import (
        ResolvedFileshareSecrets,
        _build_client,
        _document_uri,
        _normalize_remote_path,
        _source_uri,
    )

    built_client = _build_client(
        _config(protocol="smb"),
        secrets=ResolvedFileshareSecrets(username="alice", password="secret"),
    )

    assert validated["base_url"] == "https://dav.example.internal"
    assert built_client.protocol == "smb"

    webdav_client = _build_client(
        _config(protocol="webdav", base_url="http://dav.example.internal"),
        secrets=ResolvedFileshareSecrets(username="alice", password="secret"),
    )
    assert webdav_client.protocol == "webdav"

    sftp_client = _build_client(
        _config(protocol="sftp", host="sftp.example.internal"),
        secrets=ResolvedFileshareSecrets(
            username="alice", password="secret", private_key="KEY"
        ),
    )
    assert sftp_client.protocol == "sftp"

    fallback_client = _build_client(
        _config(protocol="unknown"),
        secrets=ResolvedFileshareSecrets(),
    )
    assert fallback_client.protocol == "unknown"
    assert _source_uri(validated) == "webdav://dav.example.internal/engineering"
    assert (
        _document_uri(validated, "guide.md") == "webdav://dav.example.internal/engineering/guide.md"
    )
    assert _normalize_remote_path("/engineering", "engineering/guide.md") == "guide.md"
    assert _normalize_remote_path("/engineering", "guide.md") == "guide.md"


def test_ingest_fileshare_source_records_skipped_scan_items(sqlite_session) -> None:
    report = ingest_fileshare_source(
        session=sqlite_session,
        knowledge_base_name="fixture-fileshare",
        config=_config(exclude_patterns=["skip.*"], max_file_size_mb=1),
        env={
            "FILESHARE_USERNAME": "alice",
            "FILESHARE_PASSWORD": "secret-pass",
        },
        client=FakeFileshareClient(
            protocol="smb",
            host="files.example.internal",
            share="team-a",
            objects=[
                _object("skip.md", b"# Skip\n", content_type="text/markdown"),
                _object("binary.txt", b"abc\x00def"),
                _object("large.txt", b"x" * (2 * 1024 * 1024)),
            ],
        ),
    )

    items = sqlite_session.scalars(
        select(PipelineRunItem).order_by(PipelineRunItem.started_at.asc())
    ).all()

    assert report.created_versions == 0
    assert report.skipped_count == 3
    assert sorted(item.metadata_json["skip_reason"] for item in items) == [
        "binary_file",
        "excluded",
        "file_too_large",
    ]


def test_ingest_fileshare_source_fails_run_on_download_credential_error(sqlite_session) -> None:
    with pytest.raises(FileshareCredentialError, match="credentials"):
        ingest_fileshare_source(
            session=sqlite_session,
            knowledge_base_name="fixture-fileshare",
            config=_config(),
            env={
                "FILESHARE_USERNAME": "alice",
                "FILESHARE_PASSWORD": "ultra-secret-value",
            },
            client=FakeFileshareClient(
                protocol="smb",
                host="files.example.internal",
                share="team-a",
                objects=[_object("guide.md", b"# Guide\n", content_type="text/markdown")],
                read_failures={
                    "guide.md": [
                        FileshareCredentialError("credentials rejected for ultra-secret-value")
                    ]
                },
            ),
        )

    run = sqlite_session.scalars(select(PipelineRun)).one()

    assert run.status == "failed"
    assert run.error_message is not None
    assert "ultra-secret-value" not in run.error_message
