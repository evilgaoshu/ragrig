from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping
from urllib.parse import quote
from uuid import UUID

from sqlalchemy.orm import Session

from ragrig.db.models import DocumentVersion
from ragrig.ingestion.pipeline import IngestionReport
from ragrig.plugins import get_plugin_registry
from ragrig.plugins.sources.database.client import (
    DatabaseClientProtocol,
    DatabaseQueryResult,
    build_sqlalchemy_database_client,
)
from ragrig.plugins.sources.database.config import DatabaseQueryConfig
from ragrig.plugins.sources.database.errors import (
    DatabaseConfigError,
    DatabaseCredentialError,
    DatabaseQueryError,
    sanitize_error_message,
)
from ragrig.repositories import (
    create_pipeline_run,
    create_pipeline_run_item,
    get_document_by_uri,
    get_next_version_number,
    get_or_create_document,
    get_or_create_knowledge_base,
    get_or_create_source,
)


def ingest_database_source(
    session: Session,
    *,
    knowledge_base_name: str,
    config: dict[str, object],
    env: Mapping[str, str] | None = None,
    client: DatabaseClientProtocol | None = None,
) -> IngestionReport:
    registry = get_plugin_registry()
    validated = registry.validate_config("source.database", config)
    dsn = _resolve_dsn(validated, env=env or os.environ)
    source_uri = _source_uri(
        engine=str(validated["engine"]),
        source_name=str(validated["source_name"]),
    )
    knowledge_base = get_or_create_knowledge_base(session, knowledge_base_name)
    source = get_or_create_source(
        session,
        knowledge_base_id=knowledge_base.id,
        kind="database",
        uri=source_uri,
        config_json=_config_snapshot(validated),
    )
    run = create_pipeline_run(
        session,
        knowledge_base_id=knowledge_base.id,
        source_id=source.id,
        run_type="database_ingest",
        config_snapshot_json=_config_snapshot(validated),
    )

    created_documents = 0
    created_versions = 0
    skipped_count = 0
    failed_count = 0
    total_items = 0
    seen_uris: set[str] = set()
    owns_client = client is None

    try:
        active_client = client or build_sqlalchemy_database_client(
            dsn=dsn,
            engine=str(validated["engine"]),
            connect_timeout_seconds=int(validated["connect_timeout_seconds"]),
            query_timeout_seconds=int(validated["query_timeout_seconds"]),
        )
        try:
            for query_payload in validated["queries"]:
                query = DatabaseQueryConfig.model_validate(query_payload)
                query_result = active_client.fetch_query(
                    query,
                    max_rows=int(validated["max_rows_per_query"]),
                )
                total_items += query_result.row_count
                for row_index, row in enumerate(query_result.rows, start=1):
                    (
                        row_created_documents,
                        row_created_versions,
                        row_skipped_count,
                        document_uri,
                    ) = _ingest_row(
                        session,
                        query=query,
                        query_result=query_result,
                        row=row,
                        row_index=row_index,
                        knowledge_base_id=knowledge_base.id,
                        source_id=source.id,
                        pipeline_run_id=run.id,
                        engine=str(validated["engine"]),
                        source_name=str(validated["source_name"]),
                    )
                    created_documents += row_created_documents
                    created_versions += row_created_versions
                    skipped_count += row_skipped_count
                    seen_uris.add(document_uri)
                if query_result.truncated:
                    skipped_count += 1
                    total_items += 1
                    truncated_metadata = {
                        "query_name": query.name,
                        "skip_reason": "max_rows_per_query_reached",
                        "max_rows_per_query": int(validated["max_rows_per_query"]),
                    }
                    document, was_created = get_or_create_document(
                        session,
                        knowledge_base_id=knowledge_base.id,
                        source_id=source.id,
                        uri=_control_uri(
                            engine=str(validated["engine"]),
                            source_name=str(validated["source_name"]),
                            query_name=query.name,
                            reason="max_rows_per_query_reached",
                        ),
                        content_hash="skipped:max_rows_per_query_reached",
                        mime_type="text/plain",
                        metadata_json=truncated_metadata,
                    )
                    if was_created:
                        created_documents += 1
                    create_pipeline_run_item(
                        session,
                        pipeline_run_id=run.id,
                        document_id=document.id,
                        status="skipped",
                        metadata_json=truncated_metadata,
                    )
        finally:
            if owns_client:
                active_client.close()
    except (DatabaseConfigError, DatabaseCredentialError, DatabaseQueryError) as exc:
        failed_count += 1
        _fail_run(run, exc, dsn=dsn)
        session.commit()
        raise exc.__class__(run.error_message or str(exc)) from exc

    for deleted_uri in sorted(set(validated["known_document_uris"]) - seen_uris):
        document = get_document_by_uri(
            session,
            knowledge_base_id=knowledge_base.id,
            uri=deleted_uri,
        )
        if document is None:
            document, was_created = get_or_create_document(
                session,
                knowledge_base_id=knowledge_base.id,
                source_id=source.id,
                uri=deleted_uri,
                content_hash="skipped:deleted_upstream",
                mime_type="text/markdown; charset=utf-8",
                metadata_json={
                    "skip_reason": "deleted_upstream",
                    "delete_detection": "placeholder",
                    "source_uri": source_uri,
                },
            )
            if was_created:
                created_documents += 1
        create_pipeline_run_item(
            session,
            pipeline_run_id=run.id,
            document_id=document.id,
            status="skipped",
            metadata_json={
                "uri": deleted_uri,
                "skip_reason": "deleted_upstream",
                "delete_detection": "placeholder",
            },
        )
        skipped_count += 1
        total_items += 1

    run.total_items = total_items
    run.success_count = created_versions
    run.failure_count = failed_count
    run.status = "completed_with_failures" if failed_count else "completed"
    run.finished_at = datetime.now(timezone.utc)
    session.commit()
    return IngestionReport(
        pipeline_run_id=run.id,
        created_documents=created_documents,
        created_versions=created_versions,
        skipped_count=skipped_count,
        failed_count=failed_count,
    )


def _ingest_row(
    session: Session,
    *,
    query: DatabaseQueryConfig,
    query_result: DatabaseQueryResult,
    row: Mapping[str, Any],
    row_index: int,
    knowledge_base_id,
    source_id,
    pipeline_run_id,
    engine: str,
    source_name: str,
) -> tuple[int, int, int, str]:
    with session.begin_nested():
        normalized_row = _json_safe(dict(row))
        _assert_query_columns(query, normalized_row)
        row_identity = _row_identity(query=query, row=normalized_row, row_index=row_index)
        row_snapshot = _sha256_json(
            {
                "query_name": query.name,
                "row_identity": row_identity,
                "row": normalized_row,
            }
        )
        document_uri = _document_uri(
            engine=engine,
            source_name=source_name,
            query_name=query.name,
            row_identity_hash=row_identity["hash"],
        )
        document = get_document_by_uri(
            session,
            knowledge_base_id=knowledge_base_id,
            uri=document_uri,
        )
        metadata_json = _metadata_payload(
            engine=engine,
            source_name=source_name,
            query=query,
            query_result=query_result,
            row=normalized_row,
            row_identity=row_identity,
            row_snapshot=row_snapshot,
            document_uri=document_uri,
        )
        if document is not None and document.metadata_json.get("row_snapshot") == row_snapshot:
            create_pipeline_run_item(
                session,
                pipeline_run_id=pipeline_run_id,
                document_id=document.id,
                status="skipped",
                metadata_json={**metadata_json, "skip_reason": "unchanged"},
            )
            return 0, 0, 1, document_uri

        extracted_text = _row_to_markdown(query=query, row=normalized_row, row_index=row_index)
        content_hash = _sha256_text(extracted_text)
        document, was_created = get_or_create_document(
            session,
            knowledge_base_id=knowledge_base_id,
            source_id=source_id,
            uri=document_uri,
            content_hash=content_hash,
            mime_type="text/markdown; charset=utf-8",
            metadata_json=metadata_json,
        )

        version = DocumentVersion(
            document_id=document.id,
            version_number=get_next_version_number(session, document_id=document.id),
            content_hash=content_hash,
            parser_name="database_row",
            parser_config_json={
                "plugin_id": "source.database",
                "query_name": query.name,
            },
            extracted_text=extracted_text,
            metadata_json=metadata_json,
        )
        session.add(version)
        session.flush()

        create_pipeline_run_item(
            session,
            pipeline_run_id=pipeline_run_id,
            document_id=document.id,
            status="success",
            metadata_json={
                **metadata_json,
                "version_number": version.version_number,
            },
        )
        return (1 if was_created else 0), 1, 0, document_uri


def _resolve_dsn(config: dict[str, object], *, env: Mapping[str, str]) -> str:
    value = config.get("dsn")
    if not isinstance(value, str) or not value.startswith("env:"):
        raise DatabaseCredentialError("source.database dsn must use env: references")
    env_name = value.removeprefix("env:")
    resolved = env.get(env_name)
    if not resolved:
        raise DatabaseCredentialError(f"missing required secret env: {env_name}")
    return resolved


def _config_snapshot(config: dict[str, object]) -> dict[str, object]:
    return {**config, "dsn": str(config.get("dsn") or "env:SOURCE_DATABASE_DSN")}


def _source_uri(*, engine: str, source_name: str) -> str:
    return f"database://{quote(engine, safe='')}/{quote(source_name, safe='')}"


def _document_uri(
    *,
    engine: str,
    source_name: str,
    query_name: str,
    row_identity_hash: str,
) -> str:
    return (
        f"{_source_uri(engine=engine, source_name=source_name)}"
        f"/{quote(query_name, safe='')}/{row_identity_hash}"
    )


def _control_uri(*, engine: str, source_name: str, query_name: str, reason: str) -> str:
    return (
        f"{_source_uri(engine=engine, source_name=source_name)}"
        f"/_control/{quote(query_name, safe='')}/{quote(reason, safe='')}"
    )


def _assert_query_columns(query: DatabaseQueryConfig, row: Mapping[str, Any]) -> None:
    columns = set(row)
    required = [
        *query.document_id_columns,
        *query.text_columns,
        *query.metadata_columns,
        *(column for column in [query.title_column] if column),
    ]
    missing = sorted(column for column in required if column not in columns)
    if missing:
        raise DatabaseConfigError(
            f"query {query.name!r} returned rows missing configured columns: {', '.join(missing)}"
        )


def _row_identity(
    *,
    query: DatabaseQueryConfig,
    row: Mapping[str, Any],
    row_index: int,
) -> dict[str, object]:
    if query.document_id_columns:
        identity_value = {column: row[column] for column in query.document_id_columns}
        identity_kind = "columns"
    else:
        identity_value = {"row_index": row_index}
        identity_kind = "row_index"
    identity_hash = _sha256_json(identity_value)[:24]
    return {
        "kind": identity_kind,
        "columns": list(query.document_id_columns),
        "hash": identity_hash,
    }


def _metadata_payload(
    *,
    engine: str,
    source_name: str,
    query: DatabaseQueryConfig,
    query_result: DatabaseQueryResult,
    row: Mapping[str, Any],
    row_identity: dict[str, object],
    row_snapshot: str,
    document_uri: str,
) -> dict[str, object]:
    selected_metadata = {column: row[column] for column in query.metadata_columns if column in row}
    return {
        "engine": engine,
        "source_name": source_name,
        "source_uri": _source_uri(engine=engine, source_name=source_name),
        "query_name": query.name,
        "document_uri": document_uri,
        "row_identity": row_identity,
        "row_snapshot": row_snapshot,
        "row_count": query_result.row_count,
        "truncated": query_result.truncated,
        "metadata_columns": selected_metadata,
    }


def _row_to_markdown(
    *,
    query: DatabaseQueryConfig,
    row: Mapping[str, Any],
    row_index: int,
) -> str:
    title = _row_title(query=query, row=row, row_index=row_index)
    text_columns = query.text_columns or [
        column for column in row if column not in query.metadata_columns
    ]
    lines = [
        f"# {title}",
        "",
        f"Query: `{query.name}`",
        "",
    ]
    for column in text_columns:
        if column not in row:
            continue
        value = row[column]
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            rendered = str(value)
        lines.extend([f"## {column}", "", rendered, ""])
    return "\n".join(lines).strip() + "\n"


def _row_title(
    *,
    query: DatabaseQueryConfig,
    row: Mapping[str, Any],
    row_index: int,
) -> str:
    if (
        query.title_column
        and query.title_column in row
        and row[query.title_column] not in (None, "")
    ):
        return str(row[query.title_column])
    if query.document_id_columns:
        values = [str(row[column]) for column in query.document_id_columns if column in row]
        if values:
            return f"{query.name}: {' / '.join(values)}"
    return f"{query.name} row {row_index}"


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(nested) for key, nested in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return {
            "bytes_sha256": hashlib.sha256(value).hexdigest(),
            "bytes_size": len(value),
        }
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fail_run(run, exc: Exception, *, dsn: str) -> None:
    run.status = "failed"
    run.error_message = sanitize_error_message(str(exc), secrets=[dsn])
    run.finished_at = datetime.now(timezone.utc)
