from __future__ import annotations

import hashlib
import io
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.db.models import Chunk, Document, DocumentVersion, PipelineRun
from ragrig.plugins import get_plugin_registry
from ragrig.plugins.object_storage import (
    ObjectStorageClientProtocol,
    ObjectStorageConfigError,
    ObjectStorageCredentialError,
    ObjectStoragePermanentError,
    ObjectStorageRetryableError,
    build_boto3_object_storage_client,
    sanitize_error_message,
)
from ragrig.repositories import (
    create_pipeline_run,
    get_knowledge_base_by_name,
    get_or_create_source,
    list_latest_document_versions,
)


@dataclass(frozen=True)
class ExportToObjectStorageReport:
    pipeline_run_id: str
    artifact_keys: list[str]
    dry_run: bool
    planned_count: int
    uploaded_count: int
    skipped_count: int
    failed_count: int


@dataclass(frozen=True)
class ResolvedObjectStorageSecrets:
    access_key: str
    secret_key: str
    session_token: str | None = None


@dataclass(frozen=True)
class PreparedArtifact:
    key: str
    artifact_name: str
    body: bytes
    content_type: str
    metadata: dict[str, str]


def export_to_object_storage(
    session: Session,
    *,
    knowledge_base_name: str,
    config: dict[str, object],
    env: Mapping[str, str] | None = None,
    client: ObjectStorageClientProtocol | None = None,
) -> ExportToObjectStorageReport:
    registry = get_plugin_registry()
    validated = registry.validate_config("sink.object_storage", config)
    secrets = _resolve_secrets(validated, env=env or os.environ)
    knowledge_base = get_knowledge_base_by_name(session, knowledge_base_name)
    if knowledge_base is None:
        raise ValueError(f"Knowledge base '{knowledge_base_name}' was not found")

    sink_source = get_or_create_source(
        session,
        knowledge_base_id=knowledge_base.id,
        kind="object_storage_sink",
        uri=_sink_uri(str(validated["bucket"]), str(validated.get("prefix") or "")),
        config_json=validated,
    )
    run = create_pipeline_run(
        session,
        knowledge_base_id=knowledge_base.id,
        source_id=sink_source.id,
        run_type="object_storage_export",
        config_snapshot_json=validated,
    )
    is_dry_run = bool(validated["dry_run"])
    parquet_export = bool(validated.get("parquet_export", False))

    if parquet_export and not _pyarrow_available():
        if not is_dry_run:
            _fail_run(
                run,
                ObjectStorageConfigError("pyarrow is required for parquet export"),
                secrets=secrets,
            )
            session.commit()
            raise ObjectStorageConfigError("pyarrow is required for parquet export")
        parquet_export = False
        validated["parquet_export"] = False

    artifacts = _prepare_artifacts(
        session,
        knowledge_base_name=knowledge_base_name,
        knowledge_base_id=knowledge_base.id,
        run_id=str(run.id),
        config=validated,
        include_pipeline_runs=False,
        run_override=None,
        dry_run=is_dry_run,
    )
    pipeline_artifact_key = _render_key(
        path_template=str(validated["path_template"]),
        prefix=str(validated.get("prefix") or ""),
        knowledge_base=knowledge_base_name,
        run_id=str(run.id),
        artifact="pipeline_runs",
        artifact_format="jsonl",
    )
    planned_keys = [artifact.key for artifact in artifacts] + [pipeline_artifact_key]
    run.total_items = len(planned_keys)

    if is_dry_run:
        run.status = "completed"
        run.finished_at = datetime.now(timezone.utc)
        session.commit()
        return ExportToObjectStorageReport(
            pipeline_run_id=str(run.id),
            artifact_keys=planned_keys,
            dry_run=True,
            planned_count=len(planned_keys),
            uploaded_count=0,
            skipped_count=0,
            failed_count=0,
        )

    active_client = client or build_boto3_object_storage_client({**validated, **secrets.__dict__})

    try:
        active_client.check_bucket_access(
            bucket=str(validated["bucket"]),
            prefix=str(validated.get("prefix") or ""),
        )
    except (ObjectStorageConfigError, ObjectStorageCredentialError) as exc:
        _fail_run(run, exc, secrets=secrets)
        session.commit()
        raise exc.__class__(run.error_message or str(exc)) from exc
    except ObjectStorageRetryableError as exc:
        _fail_run(run, exc, secrets=secrets)
        session.commit()
        raise ObjectStorageRetryableError(run.error_message or str(exc)) from exc

    uploaded_count = 0
    skipped_count = 0
    failed_count = 0
    for artifact in artifacts:
        try:
            existing = active_client.get_object(bucket=str(validated["bucket"]), key=artifact.key)
            if existing is not None and not bool(validated["overwrite"]):
                skipped_count += 1
                continue
            _put_with_retries(
                active_client,
                bucket=str(validated["bucket"]),
                artifact=artifact,
                max_retries=int(validated["max_retries"]),
            )
            uploaded_count += 1
        except (
            ObjectStorageConfigError,
            ObjectStorageCredentialError,
            ObjectStoragePermanentError,
        ) as exc:
            _fail_run(run, exc, secrets=secrets)
            session.commit()
            raise exc.__class__(run.error_message or str(exc)) from exc
        except ObjectStorageRetryableError as exc:
            failed_count += 1
            run.status = "completed_with_failures"
            run.error_message = sanitize_error_message(
                str(exc),
                secrets=[secrets.access_key, secrets.secret_key, secrets.session_token or ""],
            )

    pipeline_existing = active_client.get_object(
        bucket=str(validated["bucket"]),
        key=pipeline_artifact_key,
    )
    pipeline_skipped = pipeline_existing is not None and not bool(validated["overwrite"])
    projected_uploaded_count = uploaded_count + (0 if pipeline_skipped else 1)
    run.success_count = projected_uploaded_count
    run.failure_count = failed_count
    run.status = "completed_with_failures" if failed_count else "completed"
    run.finished_at = datetime.now(timezone.utc)

    pipeline_artifact = _prepare_artifacts(
        session,
        knowledge_base_name=knowledge_base_name,
        knowledge_base_id=knowledge_base.id,
        run_id=str(run.id),
        config=validated,
        include_pipeline_runs=True,
        run_override=run,
        dry_run=False,
    )[-1]
    if pipeline_skipped:
        skipped_count += 1
    else:
        try:
            _put_with_retries(
                active_client,
                bucket=str(validated["bucket"]),
                artifact=pipeline_artifact,
                max_retries=int(validated["max_retries"]),
            )
            uploaded_count += 1
        except (
            ObjectStorageConfigError,
            ObjectStorageCredentialError,
            ObjectStoragePermanentError,
        ) as exc:
            _fail_run(run, exc, secrets=secrets)
            session.commit()
            raise exc.__class__(run.error_message or str(exc)) from exc
        except ObjectStorageRetryableError as exc:
            failed_count += 1
            run.error_message = sanitize_error_message(
                str(exc),
                secrets=[secrets.access_key, secrets.secret_key, secrets.session_token or ""],
            )

    run.success_count = uploaded_count
    run.failure_count = failed_count
    run.status = "completed_with_failures" if failed_count else "completed"
    session.commit()
    return ExportToObjectStorageReport(
        pipeline_run_id=str(run.id),
        artifact_keys=planned_keys,
        dry_run=False,
        planned_count=len(planned_keys),
        uploaded_count=uploaded_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
    )


def _resolve_secrets(
    config: dict[str, object], *, env: Mapping[str, str]
) -> ResolvedObjectStorageSecrets:
    def _resolve(value: object, *, required: bool) -> str | None:
        if value is None:
            if required:
                raise ObjectStorageConfigError("missing required secret reference")
            return None
        if not isinstance(value, str) or not value.startswith("env:"):
            raise ObjectStorageConfigError("sink.object_storage secrets must use env: references")
        env_name = value.removeprefix("env:")
        resolved = env.get(env_name)
        if resolved is None:
            raise ObjectStorageConfigError(f"missing required secret env: {env_name}")
        return resolved

    return ResolvedObjectStorageSecrets(
        access_key=_resolve(config["access_key"], required=True) or "",
        secret_key=_resolve(config["secret_key"], required=True) or "",
        session_token=_resolve(config.get("session_token"), required=False),
    )


def _pyarrow_available() -> bool:
    try:
        import pyarrow  # noqa: F401

        return True
    except ImportError:
        return False


def _prepare_artifacts(
    session: Session,
    *,
    knowledge_base_name: str,
    knowledge_base_id,
    run_id: str,
    config: dict[str, object],
    include_pipeline_runs: bool,
    run_override: PipelineRun | None,
    dry_run: bool = False,
) -> list[PreparedArtifact]:
    versions = list_latest_document_versions(session, knowledge_base_id=knowledge_base_id)
    documents = [version.document for version in versions]
    chunks = list(
        session.scalars(
            select(Chunk)
            .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(Document.knowledge_base_id == knowledge_base_id)
            .order_by(Document.uri, Chunk.chunk_index)
        )
    )
    pipeline_runs = list(
        session.scalars(
            select(PipelineRun)
            .where(PipelineRun.knowledge_base_id == knowledge_base_id)
            .order_by(PipelineRun.started_at.asc())
        )
    )
    chunk_rows = [
        {
            "chunk_id": str(chunk.id),
            "document_version_id": str(chunk.document_version_id),
            "document_uri": _document_uri_for_version_id(versions, chunk.document_version_id),
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            "page_number": chunk.page_number,
            "heading": chunk.heading,
            "metadata": _json_string(chunk.metadata_json),
        }
        for chunk in chunks
    ]
    document_version_rows = [
        {
            "document_version_id": str(version.id),
            "document_id": str(version.document_id),
            "version_number": version.version_number,
            "content_hash": version.content_hash,
            "parser_name": version.parser_name,
            "parser_config": _json_string(version.parser_config_json),
            "metadata": _json_string(version.metadata_json),
            "document_uri": version.document.uri,
            "source_uri": version.document.source.uri if version.document.source else None,
        }
        for version in versions
    ]
    document_rows = [
        {
            "document_id": str(document.id),
            "knowledge_base_id": str(document.knowledge_base_id),
            "source_id": str(document.source_id),
            "document_uri": document.uri,
            "content_hash": document.content_hash,
            "mime_type": document.mime_type,
            "metadata": _json_string(document.metadata_json),
        }
        for document in documents
    ]
    retrieval_rows = [
        {
            "status": "unsupported",
            "reason": "explicit retrieval report export is not implemented in this phase",
        }
    ]
    artifact_rows: list[tuple[str, str, list[dict[str, Any]] | str, str]] = [
        (
            "chunks",
            "jsonl",
            [
                {
                    "chunk_id": row["chunk_id"],
                    "document_version_id": row["document_version_id"],
                    "chunk_index": row["chunk_index"],
                    "text": row["text"],
                    "char_start": row["char_start"],
                    "char_end": row["char_end"],
                    "page_number": row["page_number"],
                    "heading": row["heading"],
                    "metadata": json.loads(row["metadata"])
                    if row["metadata"] is not None
                    else None,
                }
                for row in chunk_rows
            ],
            "application/x-ndjson",
        ),
        (
            "document_versions",
            "jsonl",
            [
                {
                    "document_version_id": row["document_version_id"],
                    "document_id": row["document_id"],
                    "version_number": row["version_number"],
                    "content_hash": row["content_hash"],
                    "parser_name": row["parser_name"],
                    "parser_config": (
                        json.loads(row["parser_config"])
                        if row["parser_config"] is not None
                        else None
                    ),
                    "metadata": json.loads(row["metadata"])
                    if row["metadata"] is not None
                    else None,
                    "document_uri": row["document_uri"],
                    "source_uri": row["source_uri"],
                }
                for row in document_version_rows
            ],
            "application/x-ndjson",
        ),
        (
            "documents",
            "jsonl",
            [
                {
                    "document_id": row["document_id"],
                    "knowledge_base_id": row["knowledge_base_id"],
                    "source_id": row["source_id"],
                    "document_uri": row["document_uri"],
                    "content_hash": row["content_hash"],
                    "mime_type": row["mime_type"],
                    "metadata": json.loads(row["metadata"])
                    if row["metadata"] is not None
                    else None,
                }
                for row in document_rows
            ],
            "application/x-ndjson",
        ),
        (
            "knowledge_base_manifest",
            "jsonl",
            [
                {
                    "knowledge_base": knowledge_base_name,
                    "knowledge_base_id": str(knowledge_base_id),
                    "run_id": run_id,
                    "document_count": len(documents),
                    "document_version_count": len(versions),
                    "chunk_count": len(chunks),
                    "pipeline_run_count": len(pipeline_runs),
                    "retrieval_artifact": _retrieval_artifact_metadata(
                        enabled=bool(config.get("include_retrieval_artifact", True))
                    ),
                    "evaluation_artifact": {
                        "status": "unsupported",
                        "reason": "evaluation exports are not implemented in this phase",
                    },
                }
            ],
            "application/x-ndjson",
        ),
    ]
    if bool(config.get("include_retrieval_artifact", True)):
        artifact_rows.append(
            (
                "retrieval_status",
                "jsonl",
                retrieval_rows,
                "application/x-ndjson",
            )
        )
    if bool(config.get("parquet_export", False)):
        artifact_rows.extend(
            [
                (
                    "chunks",
                    "parquet",
                    chunk_rows,
                    "application/vnd.apache.parquet",
                ),
                (
                    "document_versions",
                    "parquet",
                    document_version_rows,
                    "application/vnd.apache.parquet",
                ),
                (
                    "documents",
                    "parquet",
                    document_rows,
                    "application/vnd.apache.parquet",
                ),
                (
                    "retrieval_status",
                    "parquet",
                    retrieval_rows,
                    "application/vnd.apache.parquet",
                ),
            ]
        )
    if bool(config.get("include_markdown_summary", True)):
        artifact_rows.append(
            (
                "export_summary",
                "md",
                _build_markdown_summary(
                    knowledge_base_name=knowledge_base_name,
                    run_id=run_id,
                    document_count=len(documents),
                    version_count=len(versions),
                    chunk_count=len(chunks),
                    pipeline_run_count=len(pipeline_runs),
                    retrieval_supported=False,
                ),
                "text/markdown; charset=utf-8",
            )
        )
    if include_pipeline_runs:
        pipeline_run_records = {current_run.id: current_run for current_run in pipeline_runs}
        if run_override is not None:
            pipeline_run_records[run_override.id] = run_override
        pipeline_run_rows = [
            {
                "pipeline_run_id": str(current_run.id),
                "run_type": current_run.run_type,
                "status": current_run.status,
                "source_id": str(current_run.source_id) if current_run.source_id else None,
                "config_snapshot": current_run.config_snapshot_json,
                "total_items": current_run.total_items,
                "success_count": current_run.success_count,
                "failure_count": current_run.failure_count,
                "error_message": current_run.error_message,
                "started_at": current_run.started_at.isoformat(),
                "finished_at": (
                    current_run.finished_at.isoformat() if current_run.finished_at else None
                ),
            }
            for current_run in pipeline_run_records.values()
        ]
        artifact_rows.append(
            (
                "pipeline_runs",
                "jsonl",
                pipeline_run_rows,
                "application/x-ndjson",
            )
        )
    artifacts: list[PreparedArtifact] = []
    for artifact_name, artifact_format, payload, content_type in artifact_rows:
        key = _render_key(
            path_template=str(config["path_template"]),
            prefix=str(config.get("prefix") or ""),
            knowledge_base=knowledge_base_name,
            run_id=run_id,
            artifact=artifact_name,
            artifact_format=artifact_format,
        )
        body = b"" if dry_run else _encode_payload(payload, artifact_format=artifact_format)
        metadata = {
            "artifact": artifact_name,
            "knowledge_base": knowledge_base_name,
            "run_id": run_id,
            "content_sha256": hashlib.sha256(body).hexdigest(),
            **{str(key): str(value) for key, value in config.get("object_metadata", {}).items()},
        }
        artifacts.append(
            PreparedArtifact(
                key=key,
                artifact_name=artifact_name,
                body=body,
                content_type=content_type,
                metadata=metadata,
            )
        )
    return artifacts


def _render_key(
    *,
    path_template: str,
    prefix: str,
    knowledge_base: str,
    run_id: str,
    artifact: str,
    artifact_format: str,
) -> str:
    rendered = path_template.format(
        knowledge_base=knowledge_base,
        run_id=run_id,
        artifact=artifact,
        format=artifact_format,
    )
    if not prefix:
        return rendered
    return f"{prefix}/{rendered}"


def _retrieval_artifact_metadata(*, enabled: bool) -> dict[str, str]:
    if not enabled:
        return {
            "status": "disabled",
            "reason": "retrieval artifact export disabled by config",
        }
    return {
        "status": "unsupported",
        "reason": "explicit retrieval report export is not implemented in this phase",
    }


def _document_uri_for_version_id(
    versions: list[DocumentVersion], document_version_id: object
) -> str | None:
    for version in versions:
        if version.id == document_version_id:
            return version.document.uri
    return None


def _json_string(value: object) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True)


def _encode_payload(payload: list[dict[str, Any]] | str, *, artifact_format: str) -> bytes:
    if artifact_format == "md":
        return str(payload).encode("utf-8")
    if artifact_format == "parquet":
        return _encode_parquet_payload(payload)
    lines = [json.dumps(item, sort_keys=True) for item in payload]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _encode_parquet_payload(payload: list[dict[str, Any]] | str) -> bytes:
    if not isinstance(payload, list):
        raise ObjectStorageConfigError("parquet export payload must be a list of records")
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise ObjectStorageConfigError("pyarrow is required for parquet export") from exc

    schema = _schema_for_parquet_payload(payload)
    table = pa.Table.from_pylist(payload, schema=schema)
    sink = io.BytesIO()
    pq.write_table(table, sink)
    return sink.getvalue()


def _schema_for_parquet_payload(payload: list[dict[str, Any]]):
    try:
        import pyarrow as pa
    except ImportError as exc:  # pragma: no cover
        raise ObjectStorageConfigError("pyarrow is required for parquet export") from exc

    if payload:
        keys = list(payload[0])
    else:
        return pa.schema([])

    typed_fields = {
        ("reason", "status"): [
            pa.field("status", pa.string(), nullable=False),
            pa.field("reason", pa.string(), nullable=False),
        ],
        (
            "char_end",
            "char_start",
            "chunk_id",
            "chunk_index",
            "document_uri",
            "document_version_id",
            "heading",
            "metadata",
            "page_number",
            "text",
        ): [
            pa.field("chunk_id", pa.string(), nullable=False),
            pa.field("document_version_id", pa.string(), nullable=False),
            pa.field("document_uri", pa.string()),
            pa.field("chunk_index", pa.int64(), nullable=False),
            pa.field("text", pa.string(), nullable=False),
            pa.field("char_start", pa.int64()),
            pa.field("char_end", pa.int64()),
            pa.field("page_number", pa.int64()),
            pa.field("heading", pa.string()),
            pa.field("metadata", pa.string()),
        ],
        (
            "content_hash",
            "document_id",
            "document_uri",
            "document_version_id",
            "metadata",
            "parser_config",
            "parser_name",
            "source_uri",
            "version_number",
        ): [
            pa.field("document_version_id", pa.string(), nullable=False),
            pa.field("document_id", pa.string(), nullable=False),
            pa.field("version_number", pa.int64(), nullable=False),
            pa.field("content_hash", pa.string(), nullable=False),
            pa.field("parser_name", pa.string(), nullable=False),
            pa.field("parser_config", pa.string()),
            pa.field("metadata", pa.string()),
            pa.field("document_uri", pa.string(), nullable=False),
            pa.field("source_uri", pa.string()),
        ],
        (
            "content_hash",
            "document_id",
            "document_uri",
            "knowledge_base_id",
            "metadata",
            "mime_type",
            "source_id",
        ): [
            pa.field("document_id", pa.string(), nullable=False),
            pa.field("knowledge_base_id", pa.string(), nullable=False),
            pa.field("source_id", pa.string(), nullable=False),
            pa.field("document_uri", pa.string(), nullable=False),
            pa.field("content_hash", pa.string(), nullable=False),
            pa.field("mime_type", pa.string()),
            pa.field("metadata", pa.string()),
        ],
    }
    fields = typed_fields.get(tuple(sorted(keys)))
    if fields is None:
        fields = [pa.field(key, pa.string()) for key in keys]
    return pa.schema(fields)


def _build_markdown_summary(
    *,
    knowledge_base_name: str,
    run_id: str,
    document_count: int,
    version_count: int,
    chunk_count: int,
    pipeline_run_count: int,
    retrieval_supported: bool,
) -> str:
    retrieval_state = "ready" if retrieval_supported else "unsupported/degraded"
    return "\n".join(
        [
            "# Object Storage Export",
            "",
            f"- Knowledge base: `{knowledge_base_name}`",
            f"- Run id: `{run_id}`",
            f"- Documents: {document_count}",
            f"- Latest document versions: {version_count}",
            f"- Chunks: {chunk_count}",
            f"- Pipeline runs: {pipeline_run_count}",
            f"- Retrieval artifact export: {retrieval_state}",
            "- Evaluation artifact export: unsupported/degraded",
        ]
    )


def _put_with_retries(
    client: ObjectStorageClientProtocol,
    *,
    bucket: str,
    artifact: PreparedArtifact,
    max_retries: int,
) -> None:
    attempts = max_retries + 1
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            client.put_object(
                bucket=bucket,
                key=artifact.key,
                body=artifact.body,
                content_type=artifact.content_type,
                metadata=artifact.metadata,
            )
            return
        except ObjectStorageRetryableError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise ObjectStoragePermanentError(f"put_object failed for {artifact.key}")


def _sink_uri(bucket: str, prefix: str) -> str:
    if not prefix:
        return f"s3://{bucket}"
    return f"s3://{bucket}/{prefix}"


def _fail_run(run: PipelineRun, exc: Exception, *, secrets: ResolvedObjectStorageSecrets) -> None:
    run.status = "failed"
    run.error_message = sanitize_error_message(
        str(exc),
        secrets=[secrets.access_key, secrets.secret_key, secrets.session_token or ""],
    )
    run.finished_at = datetime.now(timezone.utc)
