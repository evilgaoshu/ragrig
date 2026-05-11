from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from ragrig.db.models import Chunk, DocumentVersion, PipelineRun, Source
from ragrig.plugins import PluginConfigValidationError, PluginStatus, build_plugin_registry
from ragrig.repositories import (
    create_pipeline_run,
    create_pipeline_run_item,
    get_or_create_document,
    get_or_create_knowledge_base,
    get_or_create_source,
)
from ragrig.retrieval import RetrievalReport, RetrievalResult

pytestmark = [pytest.mark.integration, pytest.mark.slow]


def _config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "bucket": "exports",
        "prefix": "team-a",
        "endpoint_url": "http://localhost:9000",
        "region": "us-east-1",
        "use_path_style": True,
        "verify_tls": True,
        "access_key": "env:AWS_ACCESS_KEY_ID",
        "secret_key": "env:AWS_SECRET_ACCESS_KEY",
        "session_token": None,
        "path_template": "{knowledge_base}/{run_id}/{artifact}.{format}",
        "overwrite": False,
        "dry_run": False,
        "include_retrieval_artifact": True,
        "include_markdown_summary": True,
        "max_retries": 2,
        "connect_timeout_seconds": 5,
        "read_timeout_seconds": 10,
        "object_metadata": {"team": "alpha"},
    }
    config.update(overrides)
    return config


def _seed_export_fixture(sqlite_session):
    knowledge_base = get_or_create_knowledge_base(sqlite_session, "fixture-export")
    source = get_or_create_source(
        sqlite_session,
        knowledge_base_id=knowledge_base.id,
        kind="local_directory",
        uri="/tmp/fixture-export",
        config_json={"root_path": "/tmp/fixture-export"},
    )
    document, _ = get_or_create_document(
        sqlite_session,
        knowledge_base_id=knowledge_base.id,
        source_id=source.id,
        uri="file:///tmp/fixture-export/guide.md",
        content_hash="guide-v1",
        mime_type="text/markdown",
        metadata_json={"source_uri": source.uri},
    )
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        content_hash="guide-v1",
        parser_name="markdown",
        parser_config_json={"plugin_id": "parser.markdown"},
        extracted_text="# Guide\n\nretrieval export fixture\n",
        metadata_json={
            "source_uri": source.uri,
            "object_snapshot": "fixture-snapshot",
        },
    )
    sqlite_session.add(version)
    sqlite_session.flush()

    chunk = Chunk(
        document_version_id=version.id,
        chunk_index=0,
        text="retrieval export fixture",
        char_start=0,
        char_end=24,
        page_number=None,
        heading="Guide",
        metadata_json={
            "document_uri": document.uri,
            "source_uri": source.uri,
            "provider": "deterministic-local",
            "model": "hash-8d",
            "dimensions": 8,
        },
    )
    sqlite_session.add(chunk)
    sqlite_session.flush()

    run = create_pipeline_run(
        sqlite_session,
        knowledge_base_id=knowledge_base.id,
        source_id=source.id,
        run_type="local_ingestion",
        config_snapshot_json={"root_path": "/tmp/fixture-export"},
    )
    create_pipeline_run_item(
        sqlite_session,
        pipeline_run_id=run.id,
        document_id=document.id,
        status="success",
        metadata_json={"document_uri": document.uri},
    )
    sqlite_session.commit()

    retrieval_report = RetrievalReport(
        knowledge_base="fixture-export",
        query="retrieval export fixture",
        top_k=1,
        provider="deterministic-local",
        model="hash-8d",
        dimensions=8,
        distance_metric="cosine_distance",
        backend="pgvector",
        backend_metadata={"status": "ready", "distance_metric": "cosine"},
        total_results=1,
        results=[
            RetrievalResult(
                document_id=document.id,
                document_version_id=version.id,
                chunk_id=chunk.id,
                chunk_index=0,
                document_uri=document.uri,
                source_uri=source.uri,
                text=chunk.text,
                text_preview=chunk.text,
                distance=0.01,
                score=0.99,
                chunk_metadata=chunk.metadata_json,
            )
        ],
    )
    return knowledge_base, retrieval_report


def _install_fake_pyarrow(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    captures: list[dict[str, object]] = []

    class FakeArrowType:
        def __init__(self, name: str) -> None:
            self.name = name

    class FakeField:
        def __init__(self, name: str, arrow_type: FakeArrowType, *, nullable: bool = True) -> None:
            self.name = name
            self.type = arrow_type
            self.nullable = nullable

    class FakeSchema:
        def __init__(self, fields: list[FakeField]) -> None:
            self.fields = fields

    class FakeTable:
        def __init__(self, rows: list[dict[str, object]], schema: FakeSchema) -> None:
            self.rows = rows
            self.schema = schema

        @classmethod
        def from_pylist(cls, rows: list[dict[str, object]], schema: FakeSchema) -> "FakeTable":
            return cls(rows, schema)

    fake_pyarrow = types.ModuleType("pyarrow")
    fake_pyarrow.field = lambda name, arrow_type, nullable=True: FakeField(
        name, arrow_type, nullable=nullable
    )
    fake_pyarrow.schema = lambda fields: FakeSchema(list(fields))
    fake_pyarrow.string = lambda: FakeArrowType("string")
    fake_pyarrow.int64 = lambda: FakeArrowType("int64")
    fake_pyarrow.float64 = lambda: FakeArrowType("float64")
    fake_pyarrow.bool_ = lambda: FakeArrowType("bool")
    fake_pyarrow.Table = FakeTable

    fake_parquet = types.ModuleType("pyarrow.parquet")

    def _write_table(table: FakeTable, sink) -> None:
        captures.append(
            {
                "rows": table.rows,
                "schema": [
                    {
                        "name": field.name,
                        "type": field.type.name,
                        "nullable": field.nullable,
                    }
                    for field in table.schema.fields
                ],
            }
        )
        sink.write(
            json.dumps(
                {
                    "rows": table.rows,
                    "schema": [
                        {
                            "name": field.name,
                            "type": field.type.name,
                            "nullable": field.nullable,
                        }
                        for field in table.schema.fields
                    ],
                },
                sort_keys=True,
            ).encode("utf-8")
        )

    fake_parquet.write_table = _write_table

    monkeypatch.setitem(sys.modules, "pyarrow", fake_pyarrow)
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", fake_parquet)
    return captures


def test_object_storage_plugin_config_validation_accepts_declared_secrets_only() -> None:
    registry = build_plugin_registry()

    validated = registry.validate_config(
        "sink.object_storage",
        _config(
            session_token="env:AWS_SESSION_TOKEN",
            object_metadata={" team ": " alpha "},
        ),
    )

    assert validated["session_token"] == "env:AWS_SESSION_TOKEN"
    assert validated["object_metadata"] == {"team": "alpha"}

    with pytest.raises(PluginConfigValidationError, match="undeclared secret"):
        registry.validate_config(
            "sink.object_storage",
            _config(secret_key="env:NOT_DECLARED"),
        )

    with pytest.raises(PluginConfigValidationError, match="path_template"):
        registry.validate_config(
            "sink.object_storage",
            _config(path_template="/absolute/{artifact}.{format}"),
        )

    with pytest.raises(PluginConfigValidationError, match="path_template must not be empty"):
        registry.validate_config(
            "sink.object_storage",
            _config(path_template="   "),
        )

    with pytest.raises(PluginConfigValidationError, match="path_template"):
        registry.validate_config(
            "sink.object_storage",
            _config(path_template="{knowledge_base}/{artifact}.jsonl"),
        )


def test_object_storage_plugin_readiness_depends_on_boto3(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ragrig.plugins.guards.is_dependency_available", lambda import_name: False)
    unavailable_registry = build_plugin_registry()
    unavailable_manifest = unavailable_registry.get("sink.object_storage")
    unavailable_discovery = {
        item["plugin_id"]: item for item in unavailable_registry.list_discovery()
    }["sink.object_storage"]

    assert unavailable_manifest.status is PluginStatus.DEGRADED
    assert unavailable_discovery["status"] == "degraded"
    assert unavailable_discovery["missing_dependencies"] == ["boto3", "pyarrow"]

    monkeypatch.setattr(
        "ragrig.plugins.guards.is_dependency_available",
        lambda import_name: import_name != "pyarrow",
    )
    parquet_missing_registry = build_plugin_registry()
    parquet_missing_manifest = parquet_missing_registry.get("sink.object_storage")
    parquet_missing_discovery = {
        item["plugin_id"]: item for item in parquet_missing_registry.list_discovery()
    }["sink.object_storage"]

    assert parquet_missing_manifest.status is PluginStatus.DEGRADED
    assert parquet_missing_discovery["status"] == "degraded"
    assert parquet_missing_discovery["missing_dependencies"] == ["pyarrow"]

    monkeypatch.setattr("ragrig.plugins.guards.is_dependency_available", lambda import_name: True)
    ready_registry = build_plugin_registry()
    ready_manifest = ready_registry.get("sink.object_storage")

    assert ready_manifest.status is PluginStatus.DEGRADED
    assert ready_manifest.example_config is not None
    assert ready_manifest.example_config["path_template"] == (
        "{knowledge_base}/{run_id}/{artifact}.{format}"
    )


def test_export_to_object_storage_writes_jsonl_and_markdown_artifacts(sqlite_session) -> None:
    from ragrig.plugins.object_storage.client import FakeObjectStorageClient
    from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

    _seed_export_fixture(sqlite_session)
    client = FakeObjectStorageClient()

    report = export_to_object_storage(
        sqlite_session,
        knowledge_base_name="fixture-export",
        config=_config(),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=client,
    )

    sink_source = sqlite_session.scalars(
        select(Source).where(Source.kind == "object_storage_sink")
    ).one()
    latest_run = sqlite_session.scalars(
        select(PipelineRun).where(PipelineRun.run_type == "object_storage_export")
    ).one()

    assert report.uploaded_count == 7
    assert report.skipped_count == 0
    assert report.failed_count == 0
    assert report.artifact_keys == [
        f"team-a/fixture-export/{report.pipeline_run_id}/chunks.jsonl",
        f"team-a/fixture-export/{report.pipeline_run_id}/document_versions.jsonl",
        f"team-a/fixture-export/{report.pipeline_run_id}/documents.jsonl",
        f"team-a/fixture-export/{report.pipeline_run_id}/knowledge_base_manifest.jsonl",
        f"team-a/fixture-export/{report.pipeline_run_id}/retrieval_status.jsonl",
        f"team-a/fixture-export/{report.pipeline_run_id}/export_summary.md",
        f"team-a/fixture-export/{report.pipeline_run_id}/pipeline_runs.jsonl",
    ]
    assert sink_source.uri == "s3://exports/team-a"
    assert latest_run is not None
    assert latest_run.run_type == "object_storage_export"
    assert latest_run.status == "completed"
    assert latest_run.success_count == 7
    assert client.objects[report.artifact_keys[0]].content_type == "application/x-ndjson"
    assert client.objects[report.artifact_keys[5]].content_type == "text/markdown; charset=utf-8"
    assert client.objects[report.artifact_keys[0]].metadata["artifact"] == "chunks"
    assert client.objects[report.artifact_keys[0]].metadata["knowledge_base"] == "fixture-export"
    assert client.objects[report.artifact_keys[0]].metadata["team"] == "alpha"
    assert b'"chunk_index": 0' in client.objects[report.artifact_keys[0]].body
    assert b"# Object Storage Export" in client.objects[report.artifact_keys[5]].body
    assert b'"status": "unsupported"' in client.objects[report.artifact_keys[4]].body
    assert b'"run_type": "object_storage_export"' in client.objects[report.artifact_keys[6]].body
    assert b'"status": "completed"' in client.objects[report.artifact_keys[6]].body
    assert b'"success_count": 7' in client.objects[report.artifact_keys[6]].body
    assert (
        client.objects[report.artifact_keys[6]].body.count(
            f'"pipeline_run_id": "{report.pipeline_run_id}"'.encode()
        )
        == 1
    )


def test_export_to_object_storage_writes_parquet_artifacts_when_enabled(
    sqlite_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ragrig.plugins.object_storage.client import FakeObjectStorageClient
    from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

    _seed_export_fixture(sqlite_session)
    captures = _install_fake_pyarrow(monkeypatch)
    client = FakeObjectStorageClient()

    report = export_to_object_storage(
        sqlite_session,
        knowledge_base_name="fixture-export",
        config=_config(parquet_export=True),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=client,
    )

    parquet_keys = sorted(key for key in report.artifact_keys if key.endswith(".parquet"))
    assert report.uploaded_count == 11
    assert len(parquet_keys) == 4
    assert parquet_keys == [
        f"team-a/fixture-export/{report.pipeline_run_id}/chunks.parquet",
        f"team-a/fixture-export/{report.pipeline_run_id}/document_versions.parquet",
        f"team-a/fixture-export/{report.pipeline_run_id}/documents.parquet",
        f"team-a/fixture-export/{report.pipeline_run_id}/retrieval_status.parquet",
    ]
    assert all(
        client.objects[key].content_type == "application/vnd.apache.parquet" for key in parquet_keys
    )
    assert all(client.objects[key].metadata["team"] == "alpha" for key in parquet_keys)
    assert all(
        client.objects[key].metadata["knowledge_base"] == "fixture-export" for key in parquet_keys
    )

    chunk_export = json.loads(client.objects[parquet_keys[0]].body.decode("utf-8"))
    assert chunk_export["rows"] == [
        {
            "char_end": 24,
            "char_start": 0,
            "chunk_id": str(
                sqlite_session.scalars(select(Chunk.id).order_by(Chunk.chunk_index.asc())).one()
            ),
            "chunk_index": 0,
            "document_uri": "file:///tmp/fixture-export/guide.md",
            "document_version_id": str(
                sqlite_session.scalars(
                    select(DocumentVersion.id).order_by(DocumentVersion.version_number.asc())
                ).one()
            ),
            "heading": "Guide",
            "metadata": json.dumps(
                {
                    "dimensions": 8,
                    "document_uri": "file:///tmp/fixture-export/guide.md",
                    "model": "hash-8d",
                    "provider": "deterministic-local",
                    "source_uri": "/tmp/fixture-export",
                },
                sort_keys=True,
            ),
            "page_number": None,
            "text": "retrieval export fixture",
        }
    ]
    assert chunk_export["schema"] == [
        {"name": "chunk_id", "nullable": False, "type": "string"},
        {"name": "document_version_id", "nullable": False, "type": "string"},
        {"name": "document_uri", "nullable": True, "type": "string"},
        {"name": "chunk_index", "nullable": False, "type": "int64"},
        {"name": "text", "nullable": False, "type": "string"},
        {"name": "char_start", "nullable": True, "type": "int64"},
        {"name": "char_end", "nullable": True, "type": "int64"},
        {"name": "page_number", "nullable": True, "type": "int64"},
        {"name": "heading", "nullable": True, "type": "string"},
        {"name": "metadata", "nullable": True, "type": "string"},
    ]

    retrieval_export = json.loads(client.objects[parquet_keys[3]].body.decode("utf-8"))
    assert retrieval_export["rows"] == [
        {
            "reason": "explicit retrieval report export is not implemented in this phase",
            "status": "unsupported",
        }
    ]
    assert retrieval_export["schema"] == [
        {"name": "status", "nullable": False, "type": "string"},
        {"name": "reason", "nullable": False, "type": "string"},
    ]
    parquet_captures = [
        capture for capture in captures if capture["schema"] == retrieval_export["schema"]
    ]
    assert len(captures) >= 4
    assert len(parquet_captures) >= 1


def test_export_to_object_storage_skips_existing_parquet_objects_when_overwrite_disabled(
    sqlite_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ragrig.plugins.object_storage.client import FakeObjectStorageClient, FakeStoredObject
    from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

    _seed_export_fixture(sqlite_session)
    _install_fake_pyarrow(monkeypatch)

    document_key = "team-a/fixture-export/fixed-run/documents.parquet"
    retrieval_key = "team-a/fixture-export/fixed-run/retrieval_status.parquet"
    pipeline_key = "team-a/fixture-export/fixed-run/pipeline_runs.jsonl"
    client = FakeObjectStorageClient(
        objects={
            document_key: FakeStoredObject(
                key=document_key,
                body=b"existing-document-parquet",
                content_type="application/vnd.apache.parquet",
                metadata={
                    "artifact": "documents",
                    "knowledge_base": "fixture-export",
                    "content_sha256": "existing-doc-parquet-hash",
                },
                last_modified=datetime(2026, 5, 5, tzinfo=timezone.utc),
            ),
            retrieval_key: FakeStoredObject(
                key=retrieval_key,
                body=b"existing-retrieval-parquet",
                content_type="application/vnd.apache.parquet",
                metadata={
                    "artifact": "retrieval_status",
                    "knowledge_base": "fixture-export",
                    "content_sha256": "existing-retrieval-parquet-hash",
                },
                last_modified=datetime(2026, 5, 5, tzinfo=timezone.utc),
            ),
            pipeline_key: FakeStoredObject(
                key=pipeline_key,
                body=b'{"status": "completed"}\n',
                content_type="application/x-ndjson",
                metadata={
                    "artifact": "pipeline_runs",
                    "knowledge_base": "fixture-export",
                    "content_sha256": "existing-pipeline-hash",
                },
                last_modified=datetime(2026, 5, 5, tzinfo=timezone.utc),
            ),
        }
    )

    report = export_to_object_storage(
        sqlite_session,
        knowledge_base_name="fixture-export",
        config=_config(
            parquet_export=True,
            path_template="{knowledge_base}/fixed-run/{artifact}.{format}",
        ),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=client,
    )

    assert report.skipped_count >= 3
    assert report.uploaded_count + report.skipped_count == 11
    assert client.objects[document_key].body == b"existing-document-parquet"
    assert client.objects[retrieval_key].body == b"existing-retrieval-parquet"


def test_export_to_object_storage_keeps_jsonl_exports_working_without_pyarrow(
    sqlite_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ragrig.plugins.object_storage.client import FakeObjectStorageClient
    from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

    _seed_export_fixture(sqlite_session)
    monkeypatch.setitem(sys.modules, "pyarrow", None)
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", None)
    client = FakeObjectStorageClient()

    report = export_to_object_storage(
        sqlite_session,
        knowledge_base_name="fixture-export",
        config=_config(),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=client,
    )

    assert report.uploaded_count == 7
    assert all(not key.endswith(".parquet") for key in report.artifact_keys)


def test_export_to_object_storage_requires_pyarrow_for_parquet_export(
    sqlite_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ragrig.plugins.object_storage.errors import ObjectStorageConfigError
    from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

    class NoopClient:
        def check_bucket_access(self, *, bucket: str, prefix: str) -> None:
            del bucket, prefix
            raise AssertionError("artifact preparation should fail before remote checks")

        def get_object(self, *, bucket: str, key: str):
            del bucket, key
            raise AssertionError("artifact preparation should fail before lookups")

        def put_object(self, *, bucket: str, key: str, body: bytes, content_type: str, metadata):
            del bucket, key, body, content_type, metadata
            raise AssertionError("artifact preparation should fail before uploads")

    _seed_export_fixture(sqlite_session)
    monkeypatch.setitem(sys.modules, "pyarrow", None)
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", None)

    with pytest.raises(ObjectStorageConfigError, match="pyarrow is required for parquet export"):
        export_to_object_storage(
            sqlite_session,
            knowledge_base_name="fixture-export",
            config=_config(parquet_export=True),
            env={
                "AWS_ACCESS_KEY_ID": "test-access-key",
                "AWS_SECRET_ACCESS_KEY": "test-secret-key",
            },
            client=NoopClient(),
        )

    latest_run = sqlite_session.scalars(
        select(PipelineRun).where(PipelineRun.run_type == "object_storage_export")
    ).one()
    assert latest_run is not None
    assert latest_run.status == "failed"
    assert "pyarrow is required" in (latest_run.error_message or "")


def test_export_to_object_storage_dry_run_excludes_parquet_when_pyarrow_missing(
    sqlite_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

    class DryRunClient:
        def __init__(self) -> None:
            self.objects: dict[str, object] = {}

        def check_bucket_access(self, *, bucket: str, prefix: str) -> None:
            del bucket, prefix
            raise AssertionError("dry run should not check remote bucket access")

        def get_object(self, *, bucket: str, key: str):
            del bucket, key
            raise AssertionError("dry run should not look up remote objects")

        def put_object(self, *, bucket: str, key: str, body: bytes, content_type: str, metadata):
            del bucket, key, body, content_type, metadata
            raise AssertionError("dry run should not upload remote objects")

    _seed_export_fixture(sqlite_session)
    monkeypatch.setitem(sys.modules, "pyarrow", None)
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", None)

    report = export_to_object_storage(
        sqlite_session,
        knowledge_base_name="fixture-export",
        config=_config(dry_run=True, parquet_export=True),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=DryRunClient(),
    )

    assert report.dry_run is True
    assert report.planned_count == 7
    assert all(not key.endswith(".parquet") for key in report.artifact_keys)
    assert any(key.endswith(".jsonl") for key in report.artifact_keys)


def test_export_to_object_storage_dry_run_reports_planned_artifacts_without_writes(
    sqlite_session,
) -> None:
    from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

    class DryRunClient:
        def __init__(self) -> None:
            self.checked = False
            self.objects: dict[str, object] = {}

        def check_bucket_access(self, *, bucket: str, prefix: str) -> None:
            del bucket, prefix
            self.checked = True
            raise AssertionError("dry run should not check remote bucket access")

        def get_object(self, *, bucket: str, key: str):
            del bucket, key
            raise AssertionError("dry run should not look up remote objects")

        def put_object(self, *, bucket: str, key: str, body: bytes, content_type: str, metadata):
            del bucket, key, body, content_type, metadata
            raise AssertionError("dry run should not upload remote objects")

    _seed_export_fixture(sqlite_session)
    client = DryRunClient()

    report = export_to_object_storage(
        sqlite_session,
        knowledge_base_name="fixture-export",
        config=_config(dry_run=True),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=client,
    )

    assert report.dry_run is True
    assert report.uploaded_count == 0
    assert report.skipped_count == 0
    assert report.planned_count == 7
    assert client.objects == {}
    assert client.checked is False
    assert report.artifact_keys[0].startswith("team-a/")


def test_export_to_object_storage_skips_existing_matching_objects_when_overwrite_disabled(
    sqlite_session,
) -> None:
    from ragrig.plugins.object_storage.client import FakeObjectStorageClient, FakeStoredObject
    from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

    _seed_export_fixture(sqlite_session)
    existing_key = "team-a/fixture-export/fixed-run/documents.jsonl"
    pipeline_key = "team-a/fixture-export/fixed-run/pipeline_runs.jsonl"
    client = FakeObjectStorageClient(
        objects={
            existing_key: FakeStoredObject(
                key=existing_key,
                body=b'{"document_uri": "file:///tmp/fixture-export/guide.md"}\n',
                content_type="application/x-ndjson",
                metadata={
                    "artifact": "documents",
                    "knowledge_base": "fixture-export",
                    "content_sha256": "reuse-existing-hash",
                },
                last_modified=datetime(2026, 5, 5, tzinfo=timezone.utc),
            ),
            pipeline_key: FakeStoredObject(
                key=pipeline_key,
                body=b'{"status": "completed"}\n',
                content_type="application/x-ndjson",
                metadata={
                    "artifact": "pipeline_runs",
                    "knowledge_base": "fixture-export",
                    "content_sha256": "pipeline-existing-hash",
                },
                last_modified=datetime(2026, 5, 5, tzinfo=timezone.utc),
            ),
        }
    )

    report = export_to_object_storage(
        sqlite_session,
        knowledge_base_name="fixture-export",
        config=_config(path_template="{knowledge_base}/fixed-run/{artifact}.{format}"),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=client,
    )

    assert report.skipped_count >= 2
    assert report.uploaded_count + report.skipped_count == 7


def test_export_to_object_storage_requires_declared_secret_env_values(sqlite_session) -> None:
    from ragrig.plugins.object_storage.errors import ObjectStorageConfigError
    from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

    _seed_export_fixture(sqlite_session)

    with pytest.raises(ObjectStorageConfigError, match="missing required secret env"):
        export_to_object_storage(
            sqlite_session,
            knowledge_base_name="fixture-export",
            config=_config(),
            env={"AWS_ACCESS_KEY_ID": "test-access-key"},
        )


def test_export_to_object_storage_fails_run_on_retryable_bucket_check_error(
    sqlite_session,
) -> None:
    from ragrig.plugins.object_storage.client import FakeObjectStorageClient
    from ragrig.plugins.object_storage.errors import ObjectStorageRetryableError
    from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

    _seed_export_fixture(sqlite_session)

    with pytest.raises(ObjectStorageRetryableError, match="bucket access check failed"):
        export_to_object_storage(
            sqlite_session,
            knowledge_base_name="fixture-export",
            config=_config(),
            env={
                "AWS_ACCESS_KEY_ID": "test-access-key",
                "AWS_SECRET_ACCESS_KEY": "test-secret-key",
            },
            client=FakeObjectStorageClient(
                list_error=ObjectStorageRetryableError("bucket access check failed")
            ),
        )

    latest_run = sqlite_session.scalars(
        select(PipelineRun).where(PipelineRun.run_type == "object_storage_export")
    ).one()
    assert latest_run is not None
    assert latest_run.status == "failed"


def test_export_to_object_storage_fails_run_on_credential_bucket_check_error(
    sqlite_session,
) -> None:
    from ragrig.plugins.object_storage.client import FakeObjectStorageClient
    from ragrig.plugins.object_storage.errors import ObjectStorageCredentialError
    from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

    _seed_export_fixture(sqlite_session)

    with pytest.raises(ObjectStorageCredentialError, match="credentials were rejected"):
        export_to_object_storage(
            sqlite_session,
            knowledge_base_name="fixture-export",
            config=_config(),
            env={
                "AWS_ACCESS_KEY_ID": "test-access-key",
                "AWS_SECRET_ACCESS_KEY": "test-secret-key",
            },
            client=FakeObjectStorageClient(
                list_error=ObjectStorageCredentialError("credentials were rejected")
            ),
        )

    latest_run = sqlite_session.scalars(
        select(PipelineRun).where(PipelineRun.run_type == "object_storage_export")
    ).one()
    assert latest_run is not None
    assert latest_run.status == "failed"


def test_export_to_object_storage_retries_retryable_put_failures(sqlite_session) -> None:
    from ragrig.plugins.object_storage.client import FakeObjectStorageClient
    from ragrig.plugins.object_storage.errors import ObjectStorageRetryableError
    from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

    _seed_export_fixture(sqlite_session)
    client = FakeObjectStorageClient(
        put_failures={
            "team-a/fixture-export/fixed-run/documents.jsonl": [
                ObjectStorageRetryableError("temporary outage"),
                ObjectStorageRetryableError("temporary outage"),
            ]
        }
    )

    report = export_to_object_storage(
        sqlite_session,
        knowledge_base_name="fixture-export",
        config=_config(path_template="{knowledge_base}/fixed-run/{artifact}.{format}"),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=client,
    )

    assert report.failed_count == 0
    assert client.put_attempts["team-a/fixture-export/fixed-run/documents.jsonl"] == 3


def test_export_to_object_storage_respects_optional_artifact_flags(sqlite_session) -> None:
    from ragrig.plugins.object_storage.client import FakeObjectStorageClient
    from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

    _seed_export_fixture(sqlite_session)
    client = FakeObjectStorageClient()

    report = export_to_object_storage(
        sqlite_session,
        knowledge_base_name="fixture-export",
        config=_config(
            include_markdown_summary=False,
            include_retrieval_artifact=False,
        ),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=client,
    )

    assert report.planned_count == 5
    assert all(not key.endswith("export_summary.md") for key in report.artifact_keys)
    manifest_key = next(
        key for key in report.artifact_keys if key.endswith("knowledge_base_manifest.jsonl")
    )
    assert b'"status": "disabled"' in client.objects[manifest_key].body


def test_export_to_object_storage_respects_optional_artifact_flags_for_parquet(
    sqlite_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ragrig.plugins.object_storage.client import FakeObjectStorageClient
    from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

    _seed_export_fixture(sqlite_session)
    captures = _install_fake_pyarrow(monkeypatch)
    client = FakeObjectStorageClient()

    report = export_to_object_storage(
        sqlite_session,
        knowledge_base_name="fixture-export",
        config=_config(
            parquet_export=True,
            include_markdown_summary=False,
            include_retrieval_artifact=False,
        ),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=client,
    )

    assert report.planned_count == 8
    assert all("retrieval_status" not in key for key in report.artifact_keys)
    assert len(captures) == 6


def test_export_to_object_storage_rejects_missing_knowledge_base(sqlite_session) -> None:
    from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

    with pytest.raises(ValueError, match="Knowledge base 'missing' was not found"):
        export_to_object_storage(
            sqlite_session,
            knowledge_base_name="missing",
            config=_config(dry_run=True),
            env={
                "AWS_ACCESS_KEY_ID": "test-access-key",
                "AWS_SECRET_ACCESS_KEY": "test-secret-key",
            },
        )


def test_export_to_object_storage_fails_run_on_existing_object_lookup_error(sqlite_session) -> None:
    from ragrig.plugins.object_storage.errors import ObjectStoragePermanentError
    from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

    class BrokenLookupClient:
        def check_bucket_access(self, *, bucket: str, prefix: str) -> None:
            del bucket, prefix

        def get_object(self, *, bucket: str, key: str):
            del bucket, key
            raise ObjectStoragePermanentError("existing object lookup failed")

        def put_object(self, *, bucket: str, key: str, body: bytes, content_type: str, metadata):
            del bucket, key, body, content_type, metadata

    _seed_export_fixture(sqlite_session)

    with pytest.raises(ObjectStoragePermanentError, match="existing object lookup failed"):
        export_to_object_storage(
            sqlite_session,
            knowledge_base_name="fixture-export",
            config=_config(),
            env={
                "AWS_ACCESS_KEY_ID": "test-access-key",
                "AWS_SECRET_ACCESS_KEY": "test-secret-key",
            },
            client=BrokenLookupClient(),
        )

    latest_run = sqlite_session.scalars(
        select(PipelineRun).where(PipelineRun.run_type == "object_storage_export")
    ).one()
    assert latest_run.status == "failed"


def test_export_to_object_storage_records_retryable_upload_failure(sqlite_session) -> None:
    from ragrig.plugins.object_storage.client import FakeObjectStorageClient
    from ragrig.plugins.object_storage.errors import ObjectStorageRetryableError
    from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

    _seed_export_fixture(sqlite_session)
    client = FakeObjectStorageClient(
        put_failures={
            "team-a/fixture-export/fixed-run/documents.jsonl": [
                ObjectStorageRetryableError("temporary outage"),
                ObjectStorageRetryableError("temporary outage"),
            ]
        }
    )

    report = export_to_object_storage(
        sqlite_session,
        knowledge_base_name="fixture-export",
        config=_config(
            path_template="{knowledge_base}/fixed-run/{artifact}.{format}",
            max_retries=1,
        ),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=client,
    )

    latest_run = sqlite_session.scalars(
        select(PipelineRun).where(PipelineRun.run_type == "object_storage_export")
    ).one()
    assert report.failed_count == 1
    assert latest_run.status == "completed_with_failures"
    assert latest_run.error_message == "temporary outage"


def test_export_to_object_storage_fails_on_pipeline_artifact_upload_error(sqlite_session) -> None:
    from ragrig.plugins.object_storage.client import FakeObjectStorageClient
    from ragrig.plugins.object_storage.errors import ObjectStoragePermanentError
    from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

    _seed_export_fixture(sqlite_session)
    client = FakeObjectStorageClient(
        put_failures={
            "team-a/fixture-export/fixed-run/pipeline_runs.jsonl": [
                ObjectStoragePermanentError("pipeline write denied")
            ]
        }
    )

    with pytest.raises(ObjectStoragePermanentError, match="pipeline write denied"):
        export_to_object_storage(
            sqlite_session,
            knowledge_base_name="fixture-export",
            config=_config(path_template="{knowledge_base}/fixed-run/{artifact}.{format}"),
            env={
                "AWS_ACCESS_KEY_ID": "test-access-key",
                "AWS_SECRET_ACCESS_KEY": "test-secret-key",
            },
            client=client,
        )

    latest_run = sqlite_session.scalars(
        select(PipelineRun).where(PipelineRun.run_type == "object_storage_export")
    ).one()
    assert latest_run.status == "failed"


def test_export_to_object_storage_records_retryable_pipeline_artifact_upload_failure(
    sqlite_session,
) -> None:
    from ragrig.plugins.object_storage.client import FakeObjectStorageClient
    from ragrig.plugins.object_storage.errors import ObjectStorageRetryableError
    from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage

    _seed_export_fixture(sqlite_session)
    client = FakeObjectStorageClient(
        put_failures={
            "team-a/fixture-export/fixed-run/pipeline_runs.jsonl": [
                ObjectStorageRetryableError("pipeline temporary outage"),
                ObjectStorageRetryableError("pipeline temporary outage"),
            ]
        }
    )

    report = export_to_object_storage(
        sqlite_session,
        knowledge_base_name="fixture-export",
        config=_config(
            path_template="{knowledge_base}/fixed-run/{artifact}.{format}",
            max_retries=1,
        ),
        env={
            "AWS_ACCESS_KEY_ID": "test-access-key",
            "AWS_SECRET_ACCESS_KEY": "test-secret-key",
        },
        client=client,
    )

    latest_run = sqlite_session.scalars(
        select(PipelineRun).where(PipelineRun.run_type == "object_storage_export")
    ).one()
    assert report.failed_count == 1
    assert report.uploaded_count == 6
    assert latest_run.status == "completed_with_failures"
    assert latest_run.error_message == "pipeline temporary outage"


def test_object_storage_internal_helpers_cover_edge_cases() -> None:
    from ragrig.plugins.object_storage.errors import (
        ObjectStorageConfigError,
        ObjectStoragePermanentError,
        ObjectStorageRetryableError,
    )
    from ragrig.plugins.sinks.object_storage.connector import (
        PreparedArtifact,
        _document_uri_for_version_id,
        _encode_parquet_payload,
        _json_string,
        _put_with_retries,
        _render_key,
        _resolve_secrets,
        _sink_uri,
    )

    class NoopClient:
        def put_object(
            self,
            *,
            bucket: str,
            key: str,
            body: bytes,
            content_type: str,
            metadata,
        ) -> None:
            del bucket, key, body, content_type, metadata

    assert _sink_uri("exports", "") == "s3://exports"
    assert _document_uri_for_version_id([], "missing") is None
    assert _json_string(None) is None
    assert (
        _render_key(
            path_template="{knowledge_base}/{artifact}.{format}",
            prefix="",
            knowledge_base="fixture-export",
            run_id="run-1",
            artifact="documents",
            artifact_format="jsonl",
        )
        == "fixture-export/documents.jsonl"
    )

    with pytest.raises(ObjectStorageConfigError, match="missing required secret reference"):
        _resolve_secrets(
            {"access_key": None, "secret_key": "env:AWS_SECRET_ACCESS_KEY"},
            env={"AWS_SECRET_ACCESS_KEY": "secret"},
        )

    with pytest.raises(ObjectStorageConfigError, match="must use env"):
        _resolve_secrets(
            {"access_key": "plain-text", "secret_key": "env:AWS_SECRET_ACCESS_KEY"},
            env={"AWS_SECRET_ACCESS_KEY": "secret"},
        )

    with pytest.raises(ObjectStorageRetryableError, match="still failing"):
        _put_with_retries(
            type(
                "RetryClient",
                (),
                {
                    "put_object": lambda self, **kwargs: (_ for _ in ()).throw(
                        ObjectStorageRetryableError("still failing")
                    )
                },
            )(),
            bucket="exports",
            artifact=PreparedArtifact(
                key="a.jsonl",
                artifact_name="documents",
                body=b"{}\n",
                content_type="application/x-ndjson",
                metadata={},
            ),
            max_retries=0,
        )

    with pytest.raises(ObjectStoragePermanentError, match="put_object failed"):
        _put_with_retries(
            NoopClient(),
            bucket="exports",
            artifact=PreparedArtifact(
                key="a.jsonl",
                artifact_name="documents",
                body=b"{}\n",
                content_type="application/x-ndjson",
                metadata={},
            ),
            max_retries=-1,
        )

    with pytest.raises(ObjectStorageConfigError, match="parquet export payload must be a list"):
        _encode_parquet_payload("not-a-list")


def test_parquet_schema_helpers_cover_empty_and_fallback_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ragrig.plugins.sinks.object_storage.connector import _schema_for_parquet_payload

    _install_fake_pyarrow(monkeypatch)

    empty_schema = _schema_for_parquet_payload(artifact_name="retrieval_status", payload=[])
    assert [
        {"name": field.name, "type": field.type.name, "nullable": field.nullable}
        for field in empty_schema.fields
    ] == [
        {"name": "status", "type": "string", "nullable": False},
        {"name": "reason", "type": "string", "nullable": False},
    ]

    fallback_schema = _schema_for_parquet_payload(
        artifact_name="custom_artifact", payload=[{"custom_field": "value"}]
    )
    assert [
        {"name": field.name, "type": field.type.name, "nullable": field.nullable}
        for field in fallback_schema.fields
    ] == [{"name": "custom_field", "type": "string", "nullable": True}]


@pytest.mark.parametrize(
    ("operation", "scenario", "expected_exception"),
    [
        ("check", "success", None),
        ("check", "no_credentials", "credential"),
        ("check", "invalid_credentials", "credential"),
        ("check", "retryable_client_error", "retryable"),
        ("check", "client_error", "permanent"),
        ("check", "botocore_error", "retryable"),
        ("head", "success", None),
        ("head", "not_found", None),
        ("head", "no_credentials", "credential"),
        ("head", "invalid_credentials", "credential"),
        ("head", "retryable_client_error", "retryable"),
        ("head", "client_error", "permanent"),
        ("head", "botocore_error", "retryable"),
        ("put", "success", None),
        ("put", "no_credentials", "credential"),
        ("put", "invalid_credentials", "credential"),
        ("put", "retryable_client_error", "retryable"),
        ("put", "client_error", "permanent"),
        ("put", "botocore_error", "retryable"),
    ],
)
def test_build_boto3_object_storage_client_maps_sdk_errors(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    scenario: str,
    expected_exception: str | None,
) -> None:
    from ragrig.plugins.object_storage.client import build_boto3_object_storage_client
    from ragrig.plugins.object_storage.errors import (
        ObjectStorageCredentialError,
        ObjectStoragePermanentError,
        ObjectStorageRetryableError,
    )

    class FakeNoCredentialsError(Exception):
        pass

    class FakeBotoCoreError(Exception):
        pass

    class FakeClientError(Exception):
        def __init__(self, code: str):
            super().__init__(code)
            self.response = {"Error": {"Code": code}}

    class FakeSdkClient:
        def list_objects_v2(self, **kwargs):
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
            return {"Contents": []}

        def head_object(self, **kwargs):
            del kwargs
            if scenario == "no_credentials":
                raise FakeNoCredentialsError()
            if scenario == "not_found":
                raise FakeClientError("NotFound")
            if scenario == "invalid_credentials":
                raise FakeClientError("AccessDenied")
            if scenario == "retryable_client_error":
                raise FakeClientError("SlowDown")
            if scenario == "client_error":
                raise FakeClientError("Boom")
            if scenario == "botocore_error":
                raise FakeBotoCoreError()
            return {
                "ContentType": "application/x-ndjson",
                "Metadata": {"artifact": "documents"},
                "LastModified": datetime(2026, 5, 5, tzinfo=timezone.utc),
            }

        def put_object(self, **kwargs):
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

    captured: dict[str, object] = {}

    class FakeSession:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def client(self, *args, **kwargs):
            captured["client_args"] = args
            captured["client_kwargs"] = kwargs
            return FakeSdkClient()

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

    client = build_boto3_object_storage_client(
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

    exception_map = {
        "credential": ObjectStorageCredentialError,
        "permanent": ObjectStoragePermanentError,
        "retryable": ObjectStorageRetryableError,
    }
    if expected_exception is not None:
        with pytest.raises(exception_map[expected_exception]):
            if operation == "check":
                client.check_bucket_access(bucket="exports", prefix="team-a")
            elif operation == "head":
                client.get_object(bucket="exports", key="team-a/documents.jsonl")
            else:
                client.put_object(
                    bucket="exports",
                    key="team-a/documents.jsonl",
                    body=b"{}\n",
                    content_type="application/x-ndjson",
                    metadata={"artifact": "documents"},
                )
        return

    if operation == "check":
        client.check_bucket_access(bucket="exports", prefix="team-a")
    elif operation == "head":
        result = client.get_object(bucket="exports", key="team-a/documents.jsonl")
        if scenario == "not_found":
            assert result is None
        else:
            assert result is not None
            assert result.metadata == {"artifact": "documents"}
            assert result.content_type == "application/x-ndjson"
    else:
        client.put_object(
            bucket="exports",
            key="team-a/documents.jsonl",
            body=b"{}\n",
            content_type="application/x-ndjson",
            metadata={"artifact": "documents"},
        )
