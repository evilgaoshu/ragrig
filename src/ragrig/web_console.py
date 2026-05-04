from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from ragrig import __version__
from ragrig.db.models import (
    Chunk,
    Document,
    DocumentVersion,
    Embedding,
    KnowledgeBase,
    PipelineRun,
    PipelineRunItem,
    Source,
)
from ragrig.plugins import get_plugin_registry
from ragrig.providers import get_provider_registry

CONSOLE_HTML_PATH = Path(__file__).with_name("web_console.html")


def load_console_html() -> str:
    return CONSOLE_HTML_PATH.read_text(encoding="utf-8")


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _latest_versions_subquery() -> Any:
    latest_version_numbers = (
        select(
            DocumentVersion.document_id.label("document_id"),
            func.max(DocumentVersion.version_number).label("version_number"),
        )
        .group_by(DocumentVersion.document_id)
        .subquery()
    )
    return (
        select(
            DocumentVersion.id.label("document_version_id"),
            DocumentVersion.document_id.label("document_id"),
        )
        .join(
            latest_version_numbers,
            (DocumentVersion.document_id == latest_version_numbers.c.document_id)
            & (DocumentVersion.version_number == latest_version_numbers.c.version_number),
        )
        .subquery()
    )


def build_system_status(
    session: Session,
    *,
    database_ok: bool,
    database_detail: str | None = None,
) -> dict[str, Any]:
    bind = session.get_bind()
    table_names: list[str] = []
    current_revision: str | None = None
    extension_state = "unknown"
    extension_name: str | None = None
    if bind is not None:
        table_names = sorted(inspect(bind).get_table_names())

    if "alembic_version" in table_names:
        current_revision = session.execute(
            text("SELECT version_num FROM alembic_version LIMIT 1")
        ).scalar()

    dialect = bind.dialect.name if bind is not None else "unknown"

    if dialect == "postgresql":
        extension_name = session.execute(
            text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
        ).scalar()
        extension_state = "installed" if extension_name == "vector" else "missing"
    elif dialect != "unknown":
        extension_state = "not_applicable"

    return {
        "status": "healthy" if database_ok else "unhealthy",
        "app": {
            "status": "ok",
            "version": __version__,
        },
        "db": {
            "status": "connected" if database_ok else "error",
            "detail": database_detail,
            "dialect": dialect,
            "runtime_database_url": (
                bind.url.render_as_string(hide_password=True) if bind is not None else None
            ),
            "alembic_revision": current_revision,
            "extension": {
                "name": extension_name,
                "state": extension_state,
            },
            "tables": table_names,
        },
    }


def list_knowledge_bases(session: Session) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for knowledge_base in session.scalars(select(KnowledgeBase).order_by(KnowledgeBase.name)):
        source_count = session.scalar(
            select(func.count(Source.id)).where(Source.knowledge_base_id == knowledge_base.id)
        )
        document_count = session.scalar(
            select(func.count(Document.id)).where(Document.knowledge_base_id == knowledge_base.id)
        )
        chunk_count = session.scalar(
            select(func.count(Chunk.id))
            .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(Document.knowledge_base_id == knowledge_base.id)
        )
        latest_run = session.scalar(
            select(PipelineRun)
            .where(PipelineRun.knowledge_base_id == knowledge_base.id)
            .order_by(
                PipelineRun.finished_at.desc().nullslast(),
                PipelineRun.started_at.desc(),
                PipelineRun.created_at.desc(),
            )
            .limit(1)
        )
        items.append(
            {
                "id": str(knowledge_base.id),
                "name": knowledge_base.name,
                "description": knowledge_base.description,
                "owner": knowledge_base.metadata_json.get("owner"),
                "vector_backend": "pgvector",
                "source_count": source_count or 0,
                "document_count": document_count or 0,
                "chunk_count": chunk_count or 0,
                "updated_at": _isoformat(knowledge_base.updated_at),
                "latest_pipeline_run": _serialize_pipeline_run(latest_run),
            }
        )
    return items


def list_sources(session: Session) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    statement = (
        select(Source, KnowledgeBase)
        .join(KnowledgeBase, KnowledgeBase.id == Source.knowledge_base_id)
        .order_by(KnowledgeBase.name, Source.uri)
    )
    for source, knowledge_base in session.execute(statement):
        items.append(
            {
                "id": str(source.id),
                "knowledge_base": knowledge_base.name,
                "kind": source.kind,
                "uri": source.uri,
                "config": source.config_json,
                "created_at": _isoformat(source.created_at),
                "updated_at": _isoformat(source.updated_at),
            }
        )
    return items


def _serialize_pipeline_run(run: PipelineRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": str(run.id),
        "run_type": run.run_type,
        "status": run.status,
        "total_items": run.total_items,
        "success_count": run.success_count,
        "failure_count": run.failure_count,
        "started_at": _isoformat(run.started_at),
        "finished_at": _isoformat(run.finished_at),
    }


def list_pipeline_runs(session: Session) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    statement = (
        select(PipelineRun, KnowledgeBase, Source)
        .join(KnowledgeBase, KnowledgeBase.id == PipelineRun.knowledge_base_id)
        .outerjoin(Source, Source.id == PipelineRun.source_id)
        .order_by(PipelineRun.started_at.desc())
    )
    for run, knowledge_base, source in session.execute(statement):
        skipped_count = session.scalar(
            select(func.count(PipelineRunItem.id)).where(
                PipelineRunItem.pipeline_run_id == run.id,
                PipelineRunItem.status == "skipped",
            )
        )
        items.append(
            {
                "id": str(run.id),
                "run_type": run.run_type,
                "knowledge_base": knowledge_base.name,
                "source_uri": source.uri if source is not None else None,
                "status": run.status,
                "total_items": run.total_items,
                "success_count": run.success_count,
                "skipped_count": skipped_count or 0,
                "failure_count": run.failure_count,
                "error_message": run.error_message,
                "config_snapshot": run.config_snapshot_json,
                "started_at": _isoformat(run.started_at),
                "finished_at": _isoformat(run.finished_at),
            }
        )
    return items


def get_pipeline_run_detail(session: Session, pipeline_run_id: str) -> dict[str, Any] | None:
    run_id = uuid.UUID(pipeline_run_id)
    row = session.execute(
        select(PipelineRun, KnowledgeBase, Source)
        .join(KnowledgeBase, KnowledgeBase.id == PipelineRun.knowledge_base_id)
        .outerjoin(Source, Source.id == PipelineRun.source_id)
        .where(PipelineRun.id == run_id)
        .limit(1)
    ).first()
    if row is None:
        return None
    run, knowledge_base, source = row
    skipped_count = session.scalar(
        select(func.count(PipelineRunItem.id)).where(
            PipelineRunItem.pipeline_run_id == run.id,
            PipelineRunItem.status == "skipped",
        )
    )
    return {
        "id": str(run.id),
        "run_type": run.run_type,
        "knowledge_base": knowledge_base.name,
        "source_uri": source.uri if source is not None else None,
        "status": run.status,
        "total_items": run.total_items,
        "success_count": run.success_count,
        "skipped_count": skipped_count or 0,
        "failure_count": run.failure_count,
        "error_message": run.error_message,
        "config_snapshot": run.config_snapshot_json,
        "started_at": _isoformat(run.started_at),
        "finished_at": _isoformat(run.finished_at),
    }


def list_pipeline_run_items(session: Session, pipeline_run_id: str) -> list[dict[str, Any]]:
    run_id = uuid.UUID(pipeline_run_id)
    items: list[dict[str, Any]] = []
    statement = (
        select(PipelineRunItem, Document)
        .join(Document, Document.id == PipelineRunItem.document_id)
        .where(PipelineRunItem.pipeline_run_id == run_id)
        .order_by(PipelineRunItem.started_at.asc())
    )
    for item, document in session.execute(statement):
        items.append(
            {
                "id": str(item.id),
                "document_id": str(document.id),
                "document_uri": document.uri,
                "status": item.status,
                "error_message": item.error_message,
                "metadata": item.metadata_json,
                "started_at": _isoformat(item.started_at),
                "finished_at": _isoformat(item.finished_at),
            }
        )
    return items


def list_documents(session: Session) -> list[dict[str, Any]]:
    latest_versions = _latest_versions_subquery()
    items: list[dict[str, Any]] = []
    statement = (
        select(Document, DocumentVersion, Source, KnowledgeBase)
        .join(latest_versions, latest_versions.c.document_id == Document.id)
        .join(DocumentVersion, DocumentVersion.id == latest_versions.c.document_version_id)
        .join(Source, Source.id == Document.source_id)
        .join(KnowledgeBase, KnowledgeBase.id == Document.knowledge_base_id)
        .order_by(KnowledgeBase.name, Document.uri)
    )
    for document, version, source, knowledge_base in session.execute(statement):
        chunk_count = session.scalar(
            select(func.count(Chunk.id)).where(Chunk.document_version_id == version.id)
        )
        items.append(
            {
                "id": str(document.id),
                "knowledge_base": knowledge_base.name,
                "uri": document.uri,
                "source_uri": source.uri,
                "mime_type": document.mime_type,
                "content_hash": document.content_hash,
                "metadata": document.metadata_json,
                "latest_version": {
                    "id": str(version.id),
                    "version_number": version.version_number,
                    "parser_name": version.parser_name,
                    "parser_config": version.parser_config_json,
                    "metadata": version.metadata_json,
                    "extracted_text": version.extracted_text,
                    "text_preview": version.extracted_text[:400],
                    "chunk_count": chunk_count or 0,
                    "created_at": _isoformat(version.created_at),
                },
            }
        )
    return items


def list_document_version_chunks(
    session: Session, document_version_id: str
) -> list[dict[str, Any]]:
    version_id = uuid.UUID(document_version_id)
    items: list[dict[str, Any]] = []
    statement = (
        select(Chunk)
        .where(Chunk.document_version_id == version_id)
        .order_by(Chunk.chunk_index.asc())
    )
    for chunk in session.scalars(statement):
        items.append(
            {
                "id": str(chunk.id),
                "chunk_index": chunk.chunk_index,
                "heading": chunk.heading,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "page_number": chunk.page_number,
                "text": chunk.text,
                "metadata": chunk.metadata_json,
            }
        )
    return items


def list_models(session: Session) -> dict[str, Any]:
    profiles = []
    for provider, model, dimensions, chunk_count in session.execute(
        select(
            Embedding.provider,
            Embedding.model,
            Embedding.dimensions,
            func.count(Embedding.id),
        )
        .group_by(Embedding.provider, Embedding.model, Embedding.dimensions)
        .order_by(Embedding.provider, Embedding.model, Embedding.dimensions)
    ):
        profiles.append(
            {
                "provider": provider,
                "model": model,
                "dimensions": dimensions,
                "chunk_count": chunk_count,
                "status": "ready",
            }
        )

    registered_providers = []
    for metadata in get_provider_registry().list():
        registered_providers.append(
            {
                "name": metadata.name,
                "kind": metadata.kind.value,
                "description": metadata.description,
                "capabilities": sorted(capability.value for capability in metadata.capabilities),
                "default_dimensions": metadata.default_dimensions,
                "max_dimensions": metadata.max_dimensions,
                "default_context_window": metadata.default_context_window,
                "max_context_window": metadata.max_context_window,
                "required_secrets": metadata.required_secrets,
                "config_schema": metadata.config_schema,
                "sdk_protocol": metadata.sdk_protocol,
                "healthcheck": metadata.healthcheck,
                "failure_modes": metadata.failure_modes,
                "retry_policy": {
                    "max_attempts": metadata.retry_policy.max_attempts,
                    "backoff_seconds": metadata.retry_policy.backoff_seconds,
                },
                "audit_fields": metadata.audit_fields,
                "metric_fields": metadata.metric_fields,
                "intended_uses": metadata.intended_uses,
            }
        )

    return {
        "embedding_profiles": profiles,
        "registered_providers": registered_providers,
        "registry_shell": {
            "llm": {
                "status": "disabled",
                "reason": (
                    "Provider registry contract exists, but LLM adapters arrive in Phase 1e PR-2."
                ),
            },
            "reranker": {
                "status": "disabled",
                "reason": (
                    "Provider registry contract exists, but reranker adapters "
                    "arrive in Phase 1e PR-2."
                ),
            },
            "parser": {
                "status": "derived",
                "reason": "Parser names are inferred from ingested document versions.",
            },
        },
    }


def list_plugins() -> list[dict[str, Any]]:
    return get_plugin_registry().list_discovery()
