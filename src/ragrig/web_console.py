from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from ragrig import __version__
from ragrig.acl import AclMetadata, acl_summary_from_metadata, normalize_principal_ids
from ragrig.answer.diagnostics import get_diagnostics_summary as _get_answer_diagnostics_summary
from ragrig.config import Settings
from ragrig.db.models import (
    Chunk,
    Document,
    DocumentUnderstanding,
    DocumentVersion,
    Embedding,
    KnowledgeBase,
    PipelineRun,
    PipelineRunItem,
    Source,
    UnderstandingRun,
)
from ragrig.formats import FormatStatus, get_format_registry
from ragrig.plugins import PluginConfigValidationError, get_plugin_registry
from ragrig.providers import get_provider_registry
from ragrig.providers.model_catalog import serialize_provider_catalog
from ragrig.repositories.audit import create_audit_event
from ragrig.retrieval_benchmark_integrity import get_integrity_summary as _get_integrity_summary
from ragrig.vectorstore.base import VectorBackendHealth
from ragrig.workflows.ingestion_dag import dag_snapshot, resume_ingestion_dag


def _plugin_discovery_by_id() -> dict[str, dict[str, Any]]:
    return {item["plugin_id"]: item for item in get_plugin_registry().list_discovery()}


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
    settings: Settings,
    vector_health: VectorBackendHealth,
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

    plugin_discovery = _plugin_discovery_by_id()
    qdrant_plugin = plugin_discovery.get("vector.qdrant")

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
        "vector": {
            "status": vector_health.status,
            "backend": settings.vector_backend,
            "health": {
                "healthy": vector_health.healthy,
                "distance_metric": vector_health.distance_metric,
                "collections": [
                    {
                        "name": item.name,
                        "exists": item.exists,
                        "dimensions": item.dimensions,
                        "distance_metric": item.distance_metric,
                        "vector_count": item.vector_count,
                        "backend": item.backend,
                        "metadata": item.metadata,
                        "unavailable_reason": item.metadata.get("unavailable_reason"),
                    }
                    for item in vector_health.collections
                ],
                "dependency_status": vector_health.details.get("dependency_status", "ready"),
                "provider": vector_health.details.get("provider", "Unavailable from status API"),
                "model": vector_health.details.get("model", "Unavailable from status API"),
                "total_vectors": vector_health.details.get("total_vectors"),
                "error": vector_health.details.get("error"),
                "score_semantics": vector_health.details.get("score_semantics"),
                "details": vector_health.details,
            },
            "plugin": {
                "plugin_id": qdrant_plugin["plugin_id"] if qdrant_plugin is not None else None,
                "status": qdrant_plugin["status"] if qdrant_plugin is not None else None,
                "reason": qdrant_plugin["reason"] if qdrant_plugin is not None else None,
                "missing_dependencies": (
                    qdrant_plugin["missing_dependencies"] if qdrant_plugin is not None else []
                ),
            },
        },
    }


def list_knowledge_bases(session: Session, *, settings: Settings) -> list[dict[str, Any]]:
    plugin_discovery = _plugin_discovery_by_id()
    vector_plugin = plugin_discovery.get("vector.qdrant")
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
                "vector_backend": settings.vector_backend,
                "vector_plugin_status": vector_plugin["status"]
                if vector_plugin is not None
                else None,
                "source_count": source_count or 0,
                "document_count": document_count or 0,
                "chunk_count": chunk_count or 0,
                "updated_at": _isoformat(knowledge_base.updated_at),
                "latest_pipeline_run": _serialize_pipeline_run(latest_run),
            }
        )
    return items


def build_permission_preview(
    session: Session,
    *,
    principal_ids: list[str] | None,
) -> dict[str, Any]:
    principals = normalize_principal_ids(principal_ids)
    degraded = len(principals) == 0
    latest_versions = _latest_versions_subquery()
    rows = session.execute(
        select(KnowledgeBase, Document, DocumentVersion)
        .join(Document, Document.knowledge_base_id == KnowledgeBase.id)
        .join(latest_versions, latest_versions.c.document_id == Document.id)
        .join(DocumentVersion, DocumentVersion.id == latest_versions.c.document_version_id)
        .order_by(KnowledgeBase.name, Document.uri)
    ).all()

    kb_map: dict[str, dict[str, Any]] = {}
    for knowledge_base, document, version in rows:
        doc_acl = AclMetadata.from_metadata(document.metadata_json or version.metadata_json)
        visible = doc_acl.permits(principals if principals else None)
        reason = doc_acl.decision_reason(principals if principals else None)
        kb_entry = kb_map.setdefault(
            str(knowledge_base.id),
            {
                "id": str(knowledge_base.id),
                "name": knowledge_base.name,
                "visible_documents": 0,
                "filtered_documents": 0,
                "documents": [],
            },
        )
        chunk_count = session.scalar(
            select(func.count(Chunk.id)).where(Chunk.document_version_id == version.id)
        )
        kb_entry["documents"].append(
            {
                "id": str(document.id),
                "uri": document.uri,
                "visible": visible,
                "reason": reason,
                "chunk_count": chunk_count or 0,
                "acl_summary": doc_acl.summary(),
            }
        )
        if visible:
            kb_entry["visible_documents"] += 1
        else:
            kb_entry["filtered_documents"] += 1

    return {
        "principal_context": "present" if principals else "missing",
        "principal_count": len(principals),
        "degraded": degraded,
        "degraded_reason": "missing_principal_context" if degraded else "",
        "knowledge_bases": list(kb_map.values()),
    }


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
                "dag": dag_snapshot(run),
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
        "dag": dag_snapshot(run),
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
                "acl_summary": acl_summary_from_metadata(document.metadata_json),
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
                "acl_summary": acl_summary_from_metadata(chunk.metadata_json),
            }
        )
    return items


def get_document_version_understanding(
    session: Session, document_version_id: str
) -> dict[str, Any] | None:
    version_id = uuid.UUID(document_version_id)
    row = session.scalar(
        select(DocumentUnderstanding).where(DocumentUnderstanding.document_version_id == version_id)
    )
    if row is None:
        return None
    return {
        "id": str(row.id),
        "document_version_id": str(row.document_version_id),
        "profile_id": row.profile_id,
        "provider": row.provider,
        "model": row.model,
        "status": row.status,
        "result": row.result_json,
        "error": row.error,
        "created_at": _isoformat(row.created_at),
        "updated_at": _isoformat(row.updated_at),
    }


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

    llm_provider_names = [
        metadata.name
        for metadata in get_provider_registry().list()
        if any(capability.value in {"chat", "generate"} for capability in metadata.capabilities)
    ]
    reranker_provider_names = [
        metadata.name
        for metadata in get_provider_registry().list()
        if any(capability.value == "rerank" for capability in metadata.capabilities)
    ]

    return {
        "embedding_profiles": profiles,
        "registered_providers": registered_providers,
        "provider_catalog": serialize_provider_catalog(),
        "registry_shell": {
            "llm": {
                "status": "ready",
                "reason": (
                    "Local model providers are registered and exposed through the "
                    "provider registry."
                ),
                "providers": llm_provider_names,
            },
            "reranker": {
                "status": "ready",
                "reason": "Local reranker providers are registered behind optional dependencies.",
                "providers": reranker_provider_names,
            },
            "parser": {
                "status": "derived",
                "reason": "Parser names are inferred from ingested document versions.",
            },
        },
    }


def list_plugins() -> list[dict[str, Any]]:
    return get_plugin_registry().list_discovery()


_SECRET_KEY_PARTS = (
    "api_key",
    "access_key",
    "secret",
    "session_token",
    "token",
    "password",
    "private_key",
    "credential",
    "dsn",
    "service_account",
)


class PluginWizardValidationError(ValueError):
    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def validate_plugin_config_for_wizard(plugin_id: str, config: dict[str, Any]) -> dict[str, Any]:
    registry = get_plugin_registry()
    discovery_by_id = {item["plugin_id"]: item for item in registry.list_discovery()}
    discovery = discovery_by_id.get(plugin_id)
    if discovery is None:
        raise PluginWizardValidationError(
            code="plugin_not_found",
            message=f"plugin '{plugin_id}' is not registered",
        )

    raw_secret_paths = _find_raw_secret_values(config)
    if raw_secret_paths:
        raise PluginWizardValidationError(
            code="raw_secret_not_allowed",
            message=(
                "raw secret-like values are not accepted in the Web Console wizard; "
                f"use env:VARIABLE_NAME references for {', '.join(raw_secret_paths)}"
            ),
        )

    if plugin_id == "source.fileshare":
        protocol = config.get("protocol") if isinstance(config, dict) else None
        base_url = config.get("base_url") if isinstance(config, dict) else None
        root_path = config.get("root_path") if isinstance(config, dict) else None
        if protocol == "webdav" and base_url is not None:
            import re

            if not re.match(r"^https?://", str(base_url)):
                raise PluginWizardValidationError(
                    code="plugin_config_invalid",
                    message="base_url must start with http:// or https://",
                )
        if isinstance(root_path, str) and root_path != root_path.rstrip():
            raise PluginWizardValidationError(
                code="plugin_config_invalid",
                message="root_path must not have trailing whitespace",
            )
        for secret_key in ("username", "password", "private_key"):
            value = config.get(secret_key) if isinstance(config, dict) else None
            if isinstance(value, str) and value.strip() and not value.startswith("env:"):
                raise PluginWizardValidationError(
                    code="raw_secret_not_allowed",
                    message=(
                        "raw secret-like values are not accepted in the Web Console wizard; "
                        f"use env:VARIABLE_NAME references for config.{secret_key}"
                    ),
                )

    try:
        validated = registry.validate_config(plugin_id, config)
    except PluginConfigValidationError as exc:
        raise PluginWizardValidationError(
            code="plugin_config_invalid",
            message=str(exc),
        ) from exc

    return {
        "valid": True,
        "plugin_id": plugin_id,
        "status": discovery["status"],
        "reason": discovery["reason"],
        "display_name": discovery["display_name"],
        "plugin_type": discovery["plugin_type"],
        "family": discovery["family"],
        "capabilities": discovery["capabilities"],
        "config": validated,
        "secret_requirements": discovery["secret_requirements"],
        "missing_dependencies": discovery["missing_dependencies"],
        "docs_reference": discovery["docs_reference"],
        "next_steps": _plugin_next_steps(discovery),
    }


def _find_raw_secret_values(value: Any, path: str = "config") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            nested_path = f"{path}.{key}"
            key_lower = str(key).lower()
            if _looks_like_secret_key(key_lower) and _is_raw_secret_value(nested):
                findings.append(nested_path)
            findings.extend(_find_raw_secret_values(nested, nested_path))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            findings.extend(_find_raw_secret_values(nested, f"{path}[{index}]"))
    return findings


def _looks_like_secret_key(key: str) -> bool:
    return any(part in key for part in _SECRET_KEY_PARTS)


def _is_raw_secret_value(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not value.startswith("env:")


def _plugin_next_steps(discovery: dict[str, Any]) -> list[str]:
    plugin_id = discovery["plugin_id"]
    plugin_type = discovery["plugin_type"]
    family = discovery["family"]
    if plugin_id == "source.local":
        return [
            "Run make ingest-local-dry-run to preview local files.",
            "Run make ingest-local and make index-local after the source path is correct.",
        ]
    if plugin_id == "source.s3":
        return [
            "Export the declared AWS_* environment variables.",
            "Run make s3-check to verify the S3-compatible source config.",
            "Use the generated config as the source plugin config once browser writes exist.",
        ]
    if plugin_id == "source.fileshare":
        return [
            "For NFS, mount the share first and validate through the local path mode.",
            "For SMB, WebDAV, or SFTP, install the optional fileshare dependencies.",
            "Run make fileshare-check with explicit env vars before enabling live ingestion.",
        ]
    if plugin_id == "sink.object_storage":
        return [
            "Export the declared object storage env vars.",
            "Run make export-object-storage-check to validate the sink path.",
            "Use dry_run=true before writing governed assets to a real bucket.",
        ]
    if plugin_id == "vector.qdrant":
        return [
            "Start local Qdrant with make qdrant-up when using the Qdrant backend.",
            "Run make qdrant-check or make vector-check to verify collection readiness.",
        ]
    if plugin_type == "model":
        if str(family) in {"ollama", "lm_studio", "llama_cpp", "vllm", "xinference", "localai"}:
            return [
                "Start the local model runtime.",
                "Use GET /models and GET /plugins to verify provider readiness.",
            ]
        return [
            "Install the provider optional dependency if required.",
            "Export the declared provider secrets.",
            "Keep cloud providers disabled until live smoke is explicitly enabled.",
        ]
    if plugin_type == "source":
        return [
            "Validate the config draft here before wiring a runtime connector.",
            "Keep live sync disabled until credentials and rate limits are confirmed.",
        ]
    if plugin_type == "sink":
        return [
            "Validate the sink config here before exporting artifacts.",
            "Prefer dry-run output before writing to external systems.",
        ]
    return [
        "Review the docs reference and keep this plugin unavailable until runtime support lands."
    ]


def _serialize_understanding_run(run: UnderstandingRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "knowledge_base_id": str(run.knowledge_base_id),
        "provider": run.provider,
        "model": run.model,
        "profile_id": run.profile_id,
        "trigger_source": run.trigger_source,
        "operator": run.operator,
        "status": run.status,
        "total": run.total,
        "created": run.created,
        "skipped": run.skipped,
        "failed": run.failed,
        "error_summary": run.error_summary,
        "started_at": _isoformat(run.started_at),
        "finished_at": _isoformat(run.finished_at),
    }


def list_understanding_runs(
    session: Session,
    knowledge_base_id: str | None = None,
    limit: int = 20,
    provider: str | None = None,
    model: str | None = None,
    profile_id: str | None = None,
    status: str | None = None,
    started_after: str | None = None,
    started_before: str | None = None,
) -> list[dict[str, Any]]:
    """List recent understanding runs, optionally filtered by KB and other criteria."""
    query = select(UnderstandingRun, KnowledgeBase).join(
        KnowledgeBase, KnowledgeBase.id == UnderstandingRun.knowledge_base_id
    )
    if knowledge_base_id is not None:
        kb_uuid = uuid.UUID(knowledge_base_id)
        query = query.where(UnderstandingRun.knowledge_base_id == kb_uuid)
    if provider is not None:
        query = query.where(UnderstandingRun.provider == provider)
    if model is not None:
        query = query.where(UnderstandingRun.model == model)
    if profile_id is not None:
        query = query.where(UnderstandingRun.profile_id == profile_id)
    if status is not None:
        query = query.where(UnderstandingRun.status == status)
    if started_after is not None:
        query = query.where(UnderstandingRun.started_at >= started_after)
    if started_before is not None:
        query = query.where(UnderstandingRun.started_at <= started_before)
    query = query.order_by(
        UnderstandingRun.started_at.desc(),
        UnderstandingRun.id.desc(),
    ).limit(limit)

    items: list[dict[str, Any]] = []
    for run, kb in session.execute(query):
        item = _serialize_understanding_run(run)
        item["knowledge_base"] = kb.name
        items.append(item)
    return items


def get_understanding_run_detail(session: Session, run_id: str) -> dict[str, Any] | None:
    """Return single understanding run detail with KB name."""
    run_uuid = uuid.UUID(run_id)
    row = session.execute(
        select(UnderstandingRun, KnowledgeBase)
        .join(KnowledgeBase, KnowledgeBase.id == UnderstandingRun.knowledge_base_id)
        .where(UnderstandingRun.id == run_uuid)
        .limit(1)
    ).first()
    if row is None:
        return None
    run, kb = row
    item = _serialize_understanding_run(run)
    item["knowledge_base"] = kb.name
    return item


def list_supported_formats(status: str | None = None) -> dict[str, list[dict[str, Any]]]:
    registry = get_format_registry()
    fmt_status = FormatStatus(status) if status else None
    formats = registry.list(status=fmt_status)
    return {
        "formats": [
            {
                "extension": fmt.extension,
                "mime_type": fmt.mime_type,
                "display_name": fmt.display_name,
                "parser_id": fmt.parser_id,
                "status": fmt.status.value,
                "fallback_policy": fmt.fallback_policy,
                "max_file_size_mb": fmt.max_file_size_mb,
                "capabilities": fmt.capabilities,
                "limitations": fmt.limitations,
                "docs_reference": fmt.docs_reference,
            }
            for fmt in formats
        ]
    }


def check_format(extension: str) -> dict[str, Any]:
    registry = get_format_registry()
    return registry.check(extension)


# ── Sanitizer Coverage Summary ──────────────────────────────────────────────

_SANITIZER_GOLDENS_DIR = Path(__file__).resolve().parents[2] / "tests" / "goldens"


def get_sanitizer_coverage() -> dict[str, Any] | None:
    """Build sanitizer coverage summary from goldens for Web Console display.

    Returns a lightweight summary safe for browser rendering — never
    includes raw secret fragments.  Returns None when no golden files exist.
    """
    import json as _json
    from hashlib import sha256

    golden_files = sorted(_SANITIZER_GOLDENS_DIR.glob("sanitizer_*.json"))
    if not golden_files:
        return None

    parsers: list[dict[str, Any]] = []
    total_fixtures = 0
    total_redacted = 0
    total_degraded = 0

    for golden_path in golden_files:
        golden = _json.loads(golden_path.read_text(encoding="utf-8"))
        parser_id: str = golden.get("parser_id", "unknown")
        redacted: int = golden.get("redaction_count", 0)
        status: str = golden.get("status", "unknown")
        degraded: int = 1 if status == "degraded" else 0

        content_for_hash = _json.dumps(golden, sort_keys=True, ensure_ascii=False)
        golden_hash = sha256(content_for_hash.encode("utf-8")).hexdigest()

        record = {
            "parser_id": parser_id,
            "fixtures": 1,
            "redacted": redacted,
            "degraded": degraded,
            "golden_hash": golden_hash[:12],
            "status": status,
        }
        if "degraded_reason" in golden:
            record["degraded_reason"] = golden["degraded_reason"]
        parsers.append(record)
        total_fixtures += 1
        total_redacted += redacted
        total_degraded += degraded

    return {
        "parsers": parsers,
        "totals": {
            "fixtures": total_fixtures,
            "redacted": total_redacted,
            "degraded": total_degraded,
        },
        "redaction_floor": 1,
        "redaction_floor_check": all(p["redacted"] >= 1 for p in parsers),
    }


# ── Sanitizer Drift History ────────────────────────────────────────────────

_SANITIZER_DRIFT_ARTIFACTS_DIR = (
    Path(__file__).resolve().parents[2] / "docs" / "operations" / "artifacts"
)


def get_sanitizer_drift_history() -> dict[str, Any]:
    """Return the sanitizer drift history for Web Console display.

    Reads drift diff artifacts from docs/operations/artifacts/ and returns
    a lightweight summary safe for browser rendering.  Never includes raw
    secret fragments.  Reports degraded status for missing or corrupt files.
    """
    import json as _json

    if not _SANITIZER_DRIFT_ARTIFACTS_DIR.is_dir():
        return {
            "available": False,
            "status": "no_history",
            "reason": "artifacts directory not found",
        }

    reports: list[dict[str, Any]] = []
    for path in sorted(_SANITIZER_DRIFT_ARTIFACTS_DIR.glob("sanitizer-drift-diff*.json")):
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
            if data.get("artifact") != "sanitizer-drift-diff":
                reports.append(
                    {
                        "_source_path": str(path.name),
                        "_degraded": True,
                        "_degraded_reason": "invalid artifact type",
                    }
                )
                continue
            reports.append(data)
        except (OSError, ValueError, _json.JSONDecodeError) as exc:
            reports.append(
                {
                    "_source_path": str(path.name),
                    "_degraded": True,
                    "_degraded_reason": str(exc),
                }
            )

    def _sort_key(r: dict[str, Any]) -> str:
        if r.get("_degraded"):
            return "9999"
        return r.get("generated_at", "")

    reports.sort(key=_sort_key)
    valid_reports = [r for r in reports if not r.get("_degraded")]

    if not valid_reports:
        return {
            "available": False,
            "status": "no_history",
            "reason": "no valid drift diff reports",
            "degraded_count": len([r for r in reports if r.get("_degraded")]),
        }

    latest = valid_reports[-1]
    parsers = latest.get("parsers", {})
    risk = latest.get("risk", "unknown")

    # Build sparkline data (last 10 reports)
    sparkline_risk: list[str] = []
    sparkline_redacted: list[int] = []
    sparkline_degraded: list[int] = []
    for r in valid_reports[-10:]:
        sparkline_risk.append(r.get("risk", "unknown"))
        sparkline_redacted.append(r.get("totals", {}).get("head", {}).get("redacted", 0))
        sparkline_degraded.append(r.get("totals", {}).get("head", {}).get("degraded", 0))

    return {
        "available": True,
        "status": "success",
        "risk": risk,
        "base_golden_hash": latest.get("base_golden_hash", "")[:12],
        "head_golden_hash": latest.get("head_golden_hash", "")[:12],
        "changed_parser_count": len(parsers.get("changed", [])),
        "added_parser_count": len(parsers.get("added", [])),
        "removed_parser_count": len(parsers.get("removed", [])),
        "head_redacted": latest.get("totals", {}).get("head", {}).get("redacted", 0),
        "head_degraded": latest.get("totals", {}).get("head", {}).get("degraded", 0),
        "generated_at": latest.get("generated_at", ""),
        "report_count": len(valid_reports),
        "sparkline": {
            "risk": sparkline_risk,
            "redacted": sparkline_redacted,
            "degraded": sparkline_degraded,
        },
    }


# ── Understanding Export Diff ──────────────────────────────────────────────

_UNDERSTANDING_EXPORT_DIFF_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "operations"
    / "artifacts"
    / "understanding-export-diff.json"
)

# Fields that must never appear in console output
_CONSOLE_SECRET_KEY_PARTS: tuple[str, ...] = (
    "api_key",
    "access_key",
    "secret",
    "password",
    "token",
    "credential",
    "private_key",
    "dsn",
    "service_account",
    "session_token",
)

# Forbidden fragments that must never appear in console output
_CONSOLE_FORBIDDEN_FRAGMENTS: tuple[str, ...] = (
    "sk-live-",
    "sk-proj-",
    "sk-ant-",
    "ghp_",
    "Bearer ",
    "PRIVATE KEY-----",
)


def _redact_console_output(obj: Any) -> Any:
    """Recursively redact secret-like values from console output."""
    if isinstance(obj, dict):
        result: dict[str, Any] = {}
        for k, v in obj.items():
            if any(p in k.lower() for p in _CONSOLE_SECRET_KEY_PARTS):
                result[k] = "[redacted]"
            else:
                result[k] = _redact_console_output(v)
        return result
    if isinstance(obj, list):
        return [_redact_console_output(v) for v in obj]
    if isinstance(obj, str):
        for fragment in _CONSOLE_FORBIDDEN_FRAGMENTS:
            if fragment in obj:
                return "[redacted]"
    return obj


def _assert_console_no_secrets(data: object, source: str = "console") -> None:
    """Panic if any string value contains a forbidden fragment."""
    if isinstance(data, str):
        for fragment in _CONSOLE_FORBIDDEN_FRAGMENTS:
            if fragment in data:
                raise RuntimeError(f"{source}: raw secret fragment {fragment!r} detected in output")
    elif isinstance(data, dict):
        for k, v in data.items():
            _assert_console_no_secrets(v, f"{source}.{k}")
    elif isinstance(data, list):
        for i, v in enumerate(data):
            _assert_console_no_secrets(v, f"{source}[{i}]")


def get_understanding_export_diff() -> dict[str, Any]:
    """Return the latest understanding export diff for Web Console display.

    Reads the artifact at docs/operations/artifacts/understanding-export-diff.json.
    Returns a lightweight summary safe for browser rendering.  Never includes
    raw secret fragments, full prompts, or full original text.

    Missing, corrupt, or schema-incompatible artifacts are reported as
    degraded/failure — never as pass.
    """
    import json as _json

    artifact_path = _UNDERSTANDING_EXPORT_DIFF_PATH

    def _artifact_relative() -> str:
        try:
            return str(artifact_path.relative_to(Path(__file__).resolve().parents[2]))
        except ValueError:
            return str(artifact_path)

    if not artifact_path.exists():
        return {
            "available": False,
            "status": "failure",
            "reason": "artifact not found",
            "artifact_path": _artifact_relative(),
        }

    try:
        raw = _json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, _json.JSONDecodeError) as exc:
        return {
            "available": False,
            "status": "failure",
            "reason": f"corrupt artifact: {exc}",
            "artifact_path": _artifact_relative(),
        }

    # Validate artifact type
    if raw.get("artifact") != "understanding-export-diff":
        return {
            "available": False,
            "status": "failure",
            "reason": "invalid artifact type",
            "artifact_path": _artifact_relative(),
        }

    # Extract safe fields
    status = raw.get("status", "unknown")
    schema_compatible = raw.get("schema_compatible", False)
    baseline = raw.get("baseline", {})
    current = raw.get("current", {})
    runs = raw.get("runs", {})
    generated_at = raw.get("generated_at", "")
    sanitized_field_count = raw.get("sanitized_field_count", 0)

    # Map schema incompatible to failure if somehow marked pass
    if not schema_compatible and status not in ("failure", "degraded"):
        status = "failure"

    summary: dict[str, Any] = {
        "available": True,
        "status": status,
        "schema_compatible": schema_compatible,
        "baseline_run_count": baseline.get("run_count", 0),
        "current_run_count": current.get("run_count", 0),
        "added_count": len(runs.get("added", [])),
        "removed_count": len(runs.get("removed", [])),
        "changed_count": len(runs.get("changed", [])),
        "generated_at": generated_at,
        "artifact_path": _artifact_relative(),
        "sanitized_field_count": sanitized_field_count,
    }

    # Redact and audit
    summary = _redact_console_output(summary)
    _assert_console_no_secrets(summary, "understanding-export-diff-console")

    return summary


# ── Sanitizer Drift History Summary ────────────────────────────────────────

_SANITIZER_DRIFT_HISTORY_SUMMARY_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "operations"
    / "artifacts"
    / "sanitizer-drift-history-summary.md"
)


def get_sanitizer_drift_history_summary() -> dict[str, Any]:
    """Return the sanitizer drift history summary for Web Console display.

    Reads the summary artifact from docs/operations/artifacts/ and returns
    a lightweight dict safe for browser rendering.  Never includes raw
    secret fragments.  Reports degraded status for missing/corrupt artifacts.
    """
    import json as _json

    summary_md = _SANITIZER_DRIFT_HISTORY_SUMMARY_PATH
    summary_json = summary_md.with_suffix(".json")

    def _relative(p: Path) -> str:
        try:
            return str(p.relative_to(Path(__file__).resolve().parents[2]))
        except ValueError:
            return str(p)

    if not summary_json.exists() and not summary_md.exists():
        return {
            "available": False,
            "status": "no_history",
            "reason": "summary artifact not found at " + _relative(summary_md),
            "summary_path": _relative(summary_md),
        }

    result: dict[str, Any] = {
        "available": True,
        "status": "success",
        "summary_path": _relative(summary_md),
        "summary_json_path": _relative(summary_json) if summary_json.exists() else None,
    }

    # Load JSON summary if available
    if summary_json.exists():
        try:
            summary = _json.loads(summary_json.read_text(encoding="utf-8"))
            result.update(summary)
        except (OSError, ValueError, _json.JSONDecodeError) as exc:
            result["status"] = "failure"
            result["reason"] = f"corrupt summary JSON: {exc}"
            result["latest_risk"] = "unknown"
            result["changed_parser_count"] = 0
            result["degraded_reports_count"] = 0

    # Load markdown summary path
    if summary_md.exists():
        result["summary_md_exists"] = True
    else:
        result["summary_md_exists"] = False

    # Ensure consistent fields missing/corrupt are set
    result.setdefault("latest_risk", "unknown")
    result.setdefault("changed_parser_count", 0)
    result.setdefault("degraded_reports_count", 0)
    result.setdefault("base_golden_hash", "")
    result.setdefault("head_golden_hash", "")
    result.setdefault("valid_report_count", 0)
    result.setdefault("total_report_count", 0)
    result.setdefault("generated_at", "")

    # Safety audit
    _assert_console_no_secrets(result, "sanitizer-drift-history-summary-console")

    return result


# ── Understanding Export Diff ──────────────────────────────────────────────

_BENCHMARK_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "benchmarks"
    / "retrieval-benchmark-baseline.json"
)


def get_recent_benchmark() -> dict[str, Any]:
    """Return the most recent retrieval benchmark result.

    Reads from the baseline artifact.  Returns {'available': False} when
    no artifact exists.
    """
    import json as _json
    from datetime import datetime, timezone

    if not _BENCHMARK_ARTIFACT_PATH.exists():
        return {"available": False}

    try:
        artifact = _json.loads(_BENCHMARK_ARTIFACT_PATH.read_text(encoding="utf-8"))
        mtime = _BENCHMARK_ARTIFACT_PATH.stat().st_mtime
        artifact_mtime = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except (OSError, ValueError, _json.JSONDecodeError):
        return {"available": False}

    # Redact any secret-like values
    SECRET_KEY_PARTS = (
        "api_key",
        "access_key",
        "secret",
        "password",
        "token",
        "credential",
        "private_key",
        "dsn",
        "service_account",
        "session_token",
    )

    def _redact(obj):
        if isinstance(obj, dict):
            return {
                k: "[redacted]" if any(p in k.lower() for p in SECRET_KEY_PARTS) else _redact(v)
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [_redact(v) for v in obj]
        return obj

    artifact = _redact(artifact)

    return {
        "available": True,
        "artifact_path": str(
            _BENCHMARK_ARTIFACT_PATH.relative_to(Path(__file__).resolve().parents[2])
        ),
        "last_updated": artifact_mtime,
        "summary": artifact,
    }


# ── Retrieval Benchmark Integrity ───────────────────────────────────────────


def get_retrieval_benchmark_integrity() -> dict[str, Any]:
    """Return retrieval benchmark baseline integrity for Web Console display.

    Never includes raw secret fragments.
    """
    return _get_integrity_summary()


# ── Answer Live Smoke Diagnostics ──────────────────────────────────────────


def get_answer_live_smoke() -> dict[str, Any]:
    """Return the latest answer live smoke diagnostics for Web Console display.

    Reads the artifact at docs/operations/artifacts/answer-live-smoke.json.
    Returns a lightweight summary with provider, model, status, reason,
    citation count, timing, and artifact path.

    Missing, corrupt, or stale artifacts are reported as degraded/failure —
    never as healthy.

    Never includes raw secret fragments.
    """
    summary = _get_answer_diagnostics_summary()
    summary = _redact_console_output(summary)
    _assert_console_no_secrets(summary, "answer-live-smoke-console")
    return summary


# ── Sanitizer Contract Matrix ───────────────────────────────────────────────

_SANITIZER_CONTRACT_MATRIX_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "operations"
    / "artifacts"
    / "sanitizer-contract-matrix.json"
)


def get_sanitizer_contract_status() -> dict[str, Any]:
    """Return the latest sanitizer contract matrix status for Web Console display.

    Reads the artifact at docs/operations/artifacts/sanitizer-contract-matrix.json.
    Returns a lightweight summary safe for browser rendering.

    Missing, corrupt, or schema-incompatible artifacts are reported as
    degraded/failure — never as pass.

    Never includes raw secret fragments.
    """
    import json as _json

    artifact_path = _SANITIZER_CONTRACT_MATRIX_PATH

    def _artifact_relative() -> str:
        try:
            return str(artifact_path.relative_to(Path(__file__).resolve().parents[2]))
        except ValueError:
            return str(artifact_path)

    if not artifact_path.exists():
        return {
            "available": False,
            "status": "failure",
            "reason": "artifact not found",
            "artifact_path": _artifact_relative(),
        }

    try:
        raw = _json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, _json.JSONDecodeError) as exc:
        return {
            "available": False,
            "status": "failure",
            "reason": f"corrupt artifact: {exc}",
            "artifact_path": _artifact_relative(),
        }

    if raw.get("artifact") != "sanitizer-contract-matrix":
        return {
            "available": False,
            "status": "failure",
            "reason": "invalid artifact type",
            "artifact_path": _artifact_relative(),
        }

    status = raw.get("status", "unknown")
    exit_code = raw.get("exit_code", 1)
    generated_at = raw.get("generated_at", "")
    totals = raw.get("totals", {})
    registered_callsite_count = totals.get("registered", 0)
    matrix = raw.get("matrix", [])

    summary: dict[str, Any] = {
        "available": True,
        "status": status,
        "exit_code": exit_code,
        "registered_callsite_count": registered_callsite_count,
        "report_path": _artifact_relative(),
        "generated_at": generated_at,
        "unregistered_count": totals.get("unregistered", 0),
        "summary_fields_ok": totals.get("summary_fields_ok", False),
        "no_duplicate_impls": totals.get("no_duplicate_impls", False),
        "fixture_ok": totals.get("fixture_ok", False),
        "total_callsites": len(matrix),
    }

    _assert_console_no_secrets(summary, "sanitizer-contract-matrix-console")
    return summary


# ── Advanced Parser Corpus ──────────────────────────────────────────────────


_ADVANCED_PARSER_CORPUS_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "operations"
    / "artifacts"
    / "advanced-parser-corpus.json"
)


def get_advanced_parser_corpus() -> dict[str, Any]:
    import json as _json

    artifact_path = _ADVANCED_PARSER_CORPUS_PATH

    def _artifact_relative() -> str:
        try:
            return str(artifact_path.relative_to(Path(__file__).resolve().parents[2]))
        except ValueError:
            return str(artifact_path)

    if not artifact_path.exists():
        return {
            "available": False,
            "status": "failure",
            "reason": "artifact not found",
            "artifact_path": _artifact_relative(),
        }

    try:
        raw = _json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, _json.JSONDecodeError) as exc:
        return {
            "available": False,
            "status": "failure",
            "reason": f"corrupt artifact: {exc}",
            "artifact_path": _artifact_relative(),
        }

    if raw.get("artifact") != "advanced-parser-corpus":
        return {
            "available": False,
            "status": "failure",
            "reason": "invalid artifact type",
            "artifact_path": _artifact_relative(),
        }

    status = raw.get("status", "unknown")
    results = raw.get("results", [])

    summary: dict[str, Any] = {
        "available": True,
        "status": status,
        "total_fixtures": raw.get("total_fixtures", 0),
        "healthy": raw.get("healthy", 0),
        "degraded": raw.get("degraded", 0),
        "skipped": raw.get("skipped", 0),
        "failed": raw.get("failed", 0),
        "result_count": len(results),
        "report_path": _artifact_relative(),
        "generated_at": raw.get("generated_at", ""),
        "results": [
            {
                "format": r.get("format", ""),
                "fixture_id": r.get("fixture_id", ""),
                "parser": r.get("parser", ""),
                "status": r.get("status", ""),
                "degraded_reason": r.get("degraded_reason"),
            }
            for r in results
        ],
    }

    _assert_console_no_secrets(summary, "advanced-parser-corpus-console")
    return summary


# ── Source Config Validation ────────────────────────────────────────────────

_SOURCE_SECRET_FIELDS = {
    "source.local": [],
    "source.s3": ["access_key", "secret_key", "session_token"],
    "source.fileshare": ["username", "password", "private_key"],
}


def validate_source_config(
    plugin_id: str, config: dict[str, Any], env: dict[str, str] | None = None
) -> dict[str, Any]:
    """Validate a source config draft with dependency/credential checks.

    Returns a status dict::
      {"valid": True, "status": "ready", ...}
      {"valid": True, "status": "degraded", "reason": "...", ...}
      {"valid": False, "status": "disabled", "reason": "...", ...}
    """
    if plugin_id not in ("source.local", "source.s3", "source.fileshare"):
        return {
            "valid": False,
            "status": "disabled",
            "reason": f"unsupported source plugin: {plugin_id}",
        }

    registry = get_plugin_registry()
    discovery_by_id = {item["plugin_id"]: item for item in registry.list_discovery()}
    discovery = discovery_by_id.get(plugin_id)
    if discovery is None:
        return {
            "valid": False,
            "status": "disabled",
            "reason": f"plugin '{plugin_id}' is not registered",
        }

    raw_secret_paths = _find_raw_secret_values(config)
    if raw_secret_paths:
        return {
            "valid": False,
            "status": "disabled",
            "reason": (
                "raw secret-like values not accepted; "
                f"use env:VARIABLE_NAME references for {', '.join(raw_secret_paths)}"
            ),
        }

    # Dependency check
    missing_deps = list(discovery.get("missing_dependencies", []))
    dep_status = "ready"
    dep_reason = None
    if missing_deps:
        dep_status = "degraded"
        dep_reason = f"missing dependencies: {', '.join(missing_deps)}"

    # Credential check (env refs)
    env = env or {}
    credential_issues = []
    for field in _SOURCE_SECRET_FIELDS.get(plugin_id, []):
        value = config.get(field) if isinstance(config, dict) else None
        if isinstance(value, str) and value.startswith("env:"):
            env_name = value.removeprefix("env:")
            if env_name not in env or not env[env_name]:
                credential_issues.append(f"{field}: env:{env_name} not set")

    cred_status = "ready"
    cred_reason = None
    if credential_issues:
        cred_status = "degraded"
        cred_reason = f"unresolved credential refs: {'; '.join(credential_issues)}"

    # Config validation
    try:
        validated = registry.validate_config(plugin_id, config)
    except PluginConfigValidationError as exc:
        return {
            "valid": False,
            "status": "disabled",
            "reason": str(exc),
        }

    overall_status = "ready"
    overall_reason = None
    if dep_status != "ready" and cred_status != "ready":
        overall_status = "disabled"
        overall_reason = f"{dep_reason}; {cred_reason}"
    elif dep_status != "ready":
        overall_status = dep_status
        overall_reason = dep_reason
    elif cred_status != "ready":
        overall_status = cred_status
        overall_reason = cred_reason

    return {
        "valid": True,
        "status": overall_status,
        "reason": overall_reason,
        "plugin_id": plugin_id,
        "display_name": discovery.get("display_name"),
        "config": validated,
        "missing_dependencies": missing_deps,
        "credential_issues": credential_issues,
        "secret_requirements": discovery.get("secret_requirements", []),
        "next_steps": _plugin_next_steps(discovery),
    }


# ── Dry-run source ingestion ────────────────────────────────────────────────


@dataclass
class DryRunFile:
    path: str
    status: str  # "discovered" | "skipped" | "failed"
    reason: str | None = None
    parser: str | None = None


@dataclass
class DryRunReport:
    source_id: str | None
    source_kind: str
    total: int
    discovered: list[DryRunFile]
    skipped: list[DryRunFile]
    failed: list[DryRunFile]
    dry_run: bool = True


def _dry_run_local_directory(
    session: Session,
    config: dict[str, Any],
) -> DryRunReport:
    from ragrig.ingestion.pipeline import _select_parser
    from ragrig.ingestion.scanner import scan_paths

    root_path = Path(str(config["root_path"]))
    include_patterns = config.get("include_patterns")
    exclude_patterns = config.get("exclude_patterns")
    max_size = int(config.get("max_file_size_bytes", 10 * 1024 * 1024))

    scan_result = scan_paths(
        root_path=root_path,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        max_file_size_bytes=max_size,
    )

    discovered: list[DryRunFile] = []
    skipped: list[DryRunFile] = []
    failed: list[DryRunFile] = []

    for sk in scan_result.skipped:
        skipped.append(DryRunFile(path=str(sk.path), status="skipped", reason=sk.reason))

    for cand in scan_result.discovered:
        try:
            parser = _select_parser(cand.path)
            _ = parser.parse(cand.path)
            discovered.append(
                DryRunFile(
                    path=str(cand.path),
                    status="discovered",
                    parser=parser.__class__.__name__,
                )
            )
        except Exception as exc:
            failed.append(DryRunFile(path=str(cand.path), status="failed", reason=str(exc)))

    return DryRunReport(
        source_id=None,
        source_kind="local_directory",
        total=len(discovered) + len(skipped) + len(failed),
        discovered=discovered,
        skipped=skipped,
        failed=failed,
    )


def _dry_run_s3_source(
    session: Session,
    config: dict[str, Any],
    env: dict[str, str] | None = None,
    client=None,
) -> DryRunReport:
    from ragrig.plugins.sources.s3.client import build_boto3_client
    from ragrig.plugins.sources.s3.connector import _resolve_secrets
    from ragrig.plugins.sources.s3.scanner import scan_objects

    secrets = _resolve_secrets(config, env=env or {})
    active_client = client or build_boto3_client({**config, **secrets.__dict__})

    try:
        scan_result = scan_objects(active_client, config=config)
    except Exception as exc:
        return DryRunReport(
            source_id=None,
            source_kind="s3",
            total=0,
            discovered=[],
            skipped=[],
            failed=[DryRunFile(path="s3://scan", status="failed", reason=str(exc))],
        )

    discovered: list[DryRunFile] = []
    skipped: list[DryRunFile] = []
    for sk in scan_result.skipped:
        skipped.append(
            DryRunFile(
                path=sk.object_metadata.key,
                status="skipped",
                reason=sk.reason,
            )
        )
    for cand in scan_result.discovered:
        discovered.append(
            DryRunFile(
                path=cand.object_metadata.key,
                status="discovered",
                parser=f"s3:{cand.object_metadata.content_type or 'unknown'}",
            )
        )

    return DryRunReport(
        source_id=None,
        source_kind="s3",
        total=len(discovered) + len(skipped),
        discovered=discovered,
        skipped=skipped,
        failed=[],
    )


def _dry_run_fileshare_source(
    session: Session,
    config: dict[str, Any],
    env: dict[str, str] | None = None,
) -> DryRunReport:
    from ragrig.plugins.sources.fileshare.connector import (
        _build_client,
        _resolve_fileshare_secrets,
    )
    from ragrig.plugins.sources.fileshare.scanner import scan_files

    try:
        secrets = _resolve_fileshare_secrets(config, env=env or {})
        client = _build_client(config, secrets)
    except Exception as exc:
        return DryRunReport(
            source_id=None,
            source_kind="fileshare",
            total=0,
            discovered=[],
            skipped=[],
            failed=[DryRunFile(path="fileshare://scan", status="failed", reason=str(exc))],
        )

    try:
        scan_result = scan_files(client, config=config)
    except Exception as exc:
        return DryRunReport(
            source_id=None,
            source_kind="fileshare",
            total=0,
            discovered=[],
            skipped=[],
            failed=[DryRunFile(path="fileshare://scan", status="failed", reason=str(exc))],
        )

    discovered: list[DryRunFile] = []
    skipped: list[DryRunFile] = []
    for sk in scan_result.skipped:
        skipped.append(DryRunFile(path=sk.path, status="skipped", reason=sk.reason))
    for cand in scan_result.discovered:
        discovered.append(DryRunFile(path=cand.path, status="discovered", parser=cand.content_type))

    return DryRunReport(
        source_id=None,
        source_kind="fileshare",
        total=len(discovered) + len(skipped),
        discovered=discovered,
        skipped=skipped,
        failed=[],
    )


def _serialize_dry_run(report: DryRunReport) -> dict[str, Any]:
    return {
        "dry_run": True,
        "source_kind": report.source_kind,
        "total": report.total,
        "discovered_count": len(report.discovered),
        "skipped_count": len(report.skipped),
        "failed_count": len(report.failed),
        "discovered": [
            {"path": f.path, "status": f.status, "parser": f.parser} for f in report.discovered
        ],
        "skipped": [{"path": f.path, "reason": f.reason} for f in report.skipped],
        "failed": [{"path": f.path, "reason": f.reason} for f in report.failed],
    }


def dry_run_source(
    session: Session,
    plugin_id: str,
    config: dict[str, Any],
    env: dict[str, str] | None = None,
    client=None,
) -> dict[str, Any]:
    """Run a dry-run ingestion scan for a source plugin.

    Scans the source and returns candidate files without writing any
    document_versions, chunks, or embeddings to the database.
    """
    registry = get_plugin_registry()
    validated = registry.validate_config(plugin_id, config)

    create_audit_event(
        session,
        event_type="dry_run_start",
        payload_json=_safe_payload({"plugin_id": plugin_id}),
    )
    session.commit()

    if plugin_id == "source.local":
        report = _dry_run_local_directory(session, validated)
    elif plugin_id == "source.s3":
        report = _dry_run_s3_source(session, validated, env=env, client=client)
    elif plugin_id == "source.fileshare":
        report = _dry_run_fileshare_source(session, validated, env=env)
    else:
        create_audit_event(
            session,
            event_type="dry_run_complete",
            payload_json={"plugin_id": plugin_id, "error": "unsupported source plugin"},
        )
        session.commit()
        return {"dry_run": False, "error": f"unsupported source plugin: {plugin_id}"}

    serialized = _serialize_dry_run(report)
    create_audit_event(
        session,
        event_type="dry_run_complete",
        payload_json=_safe_payload(
            {
                "plugin_id": plugin_id,
                "source_kind": report.source_kind,
                "total": report.total,
                "discovered_count": len(report.discovered),
                "skipped_count": len(report.skipped),
                "failed_count": len(report.failed),
            }
        ),
    )
    session.commit()
    return serialized


# ── Source Config Save ──────────────────────────────────────────────────────


def save_source_config(
    session: Session,
    *,
    plugin_id: str,
    config: dict[str, Any],
    knowledge_base_name: str,
    operator: str | None = None,
) -> dict[str, Any]:
    """Validate and save a source configuration.

    Creates or updates a Source record with validated config.
    Returns the source details.
    """
    registry = get_plugin_registry()
    validated = registry.validate_config(plugin_id, config)

    source_kind = plugin_id.removeprefix("source.")
    if source_kind == "local":
        from ragrig.repositories import get_or_create_knowledge_base as _get_or_create_kb
        from ragrig.repositories import get_or_create_source as _get_or_create_src

        kb = _get_or_create_kb(session, knowledge_base_name)
        root_path = Path(str(validated.get("root_path", "")))
        source_uri = str(root_path.resolve()) if root_path else "local://unspecified"

        source = _get_or_create_src(
            session,
            knowledge_base_id=kb.id,
            kind=source_kind,
            uri=source_uri,
            config_json=validated,
        )
    elif source_kind == "s3":
        from ragrig.repositories import get_or_create_knowledge_base as _get_or_create_kb
        from ragrig.repositories import get_or_create_source as _get_or_create_src

        kb = _get_or_create_kb(session, knowledge_base_name)
        bucket = str(validated.get("bucket", ""))
        prefix = str(validated.get("prefix", ""))
        source_uri = f"s3://{bucket}/{prefix}" if prefix else f"s3://{bucket}"

        source = _get_or_create_src(
            session,
            knowledge_base_id=kb.id,
            kind=source_kind,
            uri=source_uri,
            config_json=validated,
        )
    elif source_kind == "fileshare":
        from ragrig.repositories import get_or_create_knowledge_base as _get_or_create_kb
        from ragrig.repositories import get_or_create_source as _get_or_create_src

        kb = _get_or_create_kb(session, knowledge_base_name)
        protocol = str(validated.get("protocol", "smb"))
        host = str(validated.get("host", ""))
        share = str(validated.get("share", ""))
        source_uri = f"{protocol}://{host}/{share}"

        source = _get_or_create_src(
            session,
            knowledge_base_id=kb.id,
            kind=source_kind,
            uri=source_uri,
            config_json=validated,
        )
    else:
        return {"error": f"unsupported source kind: {source_kind}"}

    session.commit()

    summary = _safe_payload(
        {
            "source_id": str(source.id),
            "kind": source_kind,
            "uri": source.uri,
        }
    )
    create_audit_event(
        session,
        event_type="source_save",
        actor=operator,
        knowledge_base_id=kb.id,
        payload_json=summary,
    )
    session.commit()

    return {
        "id": str(source.id),
        "knowledge_base": knowledge_base_name,
        "kind": source_kind,
        "uri": source.uri,
        "config": validated,
        "created_at": _isoformat(source.created_at),
        "updated_at": _isoformat(source.updated_at),
    }


def _check_retry_guardrails(
    session: Session,
    *,
    item: PipelineRunItem,
    run: PipelineRun,
) -> dict[str, Any] | None:
    """Check guardrails before allowing a retry.

    Returns a deny response dict if a guardrail blocks the retry,
    or None if the retry may proceed.
    """
    if item.status != "failed":
        return {
            "denied": True,
            "reason": "invalid_state_transition",
            "message": (
                f"Cannot retry item with status '{item.status}';"
                " only 'failed' items may be retried."
            ),
            "item_id": str(item.id),
            "current_status": item.status,
        }

    # Check for existing successful retry
    if (
        item.metadata_json
        and item.metadata_json.get("retry_version_number") is not None
        and item.status == "success"
    ):
        return {
            "denied": True,
            "reason": "duplicate_retry",
            "message": "Item has already been successfully retried.",
            "item_id": str(item.id),
        }

    # Check concurrent retry (item already being retried in another session)
    if item.metadata_json and item.metadata_json.get("retry_in_progress"):
        return {
            "denied": True,
            "reason": "concurrent_retry",
            "message": "Item retry is already in progress.",
            "item_id": str(item.id),
        }

    # Check for expired config snapshot
    snapshot = run.config_snapshot_json or {}
    snapshot_age = None
    if run.finished_at:
        now = datetime.now(timezone.utc)
        finished = run.finished_at
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=timezone.utc)
        snapshot_age = (now - finished).total_seconds()
    if snapshot.get("snapshot_expired"):
        return {
            "denied": True,
            "reason": "expired_snapshot",
            "message": "Config snapshot has been marked as expired.",
            "item_id": str(item.id),
            "run_id": str(run.id),
        }
    if snapshot_age is not None and snapshot_age > 86400:
        return {
            "denied": True,
            "reason": "expired_snapshot",
            "message": f"Config snapshot is too old ({snapshot_age:.0f}s > 86400s threshold).",
            "item_id": str(item.id),
            "run_id": str(run.id),
            "snapshot_age_seconds": snapshot_age,
        }

    return None


def _check_run_retry_guardrails(
    session: Session,
    *,
    run: PipelineRun,
) -> dict[str, Any] | None:
    """Check guardrails before retrying all failed items in a run."""
    failed_items = (
        session.query(PipelineRunItem)
        .filter(
            PipelineRunItem.pipeline_run_id == run.id,
            PipelineRunItem.status == "failed",
        )
        .all()
    )

    if not failed_items:
        return None

    snapshot = run.config_snapshot_json or {}
    snapshot_age = None
    if run.finished_at:
        now = datetime.now(timezone.utc)
        finished = run.finished_at
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=timezone.utc)
        snapshot_age = (now - finished).total_seconds()
    if snapshot.get("snapshot_expired"):
        return {
            "denied": True,
            "reason": "expired_snapshot",
            "message": "Config snapshot has been marked as expired.",
            "run_id": str(run.id),
        }
    if snapshot_age is not None and snapshot_age > 86400:
        return {
            "denied": True,
            "reason": "expired_snapshot",
            "message": f"Config snapshot is too old ({snapshot_age:.0f}s > 86400s threshold).",
            "run_id": str(run.id),
            "snapshot_age_seconds": snapshot_age,
        }

    return None


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive keys from a payload dict.

    Mirrors the pattern from ragrig.repositories.audit._safe_payload.
    """
    _forbidden_keys = {
        "password",
        "api_key",
        "token",
        "secret",
        "raw_secret",
        "private_key",
        "access_key",
        "session_token",
    }
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        key_text = str(key)
        if key_text.lower() in _forbidden_keys:
            safe[key_text] = "[REDACTED]"
        elif isinstance(value, dict):
            safe[key_text] = _safe_payload(value)
        elif isinstance(value, list):
            safe[key_text] = [
                _safe_payload(item) if isinstance(item, dict) else item for item in value[:50]
            ]
        elif isinstance(value, str) and len(value) > 240:
            safe[key_text] = value[:237] + "..."
        else:
            safe[key_text] = value
    return safe


# ── Pipeline Run Item Inspect & Retry ───────────────────────────────────────


def get_pipeline_run_item_detail(session: Session, item_id: str) -> dict[str, Any] | None:
    """Return detail for a single pipeline run item."""
    item_uuid = uuid.UUID(item_id)
    row = session.execute(
        select(PipelineRunItem, Document, PipelineRun)
        .join(Document, Document.id == PipelineRunItem.document_id)
        .join(PipelineRun, PipelineRun.id == PipelineRunItem.pipeline_run_id)
        .where(PipelineRunItem.id == item_uuid)
        .limit(1)
    ).first()
    if row is None:
        return None
    item, document, run = row
    return {
        "id": str(item.id),
        "pipeline_run_id": str(run.id),
        "run_type": run.run_type,
        "status": item.status,
        "document_id": str(document.id),
        "document_uri": document.uri,
        "error_message": item.error_message,
        "metadata": item.metadata_json,
        "config_snapshot": run.config_snapshot_json,
        "started_at": _isoformat(item.started_at),
        "finished_at": _isoformat(item.finished_at),
    }


def retry_pipeline_run_item(
    session: Session,
    *,
    item_id: str,
    operator: str | None = None,
) -> dict[str, Any] | None:
    """Retry a single failed pipeline run item.

    Re-processes the failed document using the same run's config snapshot.
    Returns the new item status, or None if the item is not found.
    """
    item_uuid = uuid.UUID(item_id)
    row = session.execute(
        select(PipelineRunItem, PipelineRun, Document, Source, KnowledgeBase)
        .join(PipelineRun, PipelineRun.id == PipelineRunItem.pipeline_run_id)
        .join(Document, Document.id == PipelineRunItem.document_id)
        .outerjoin(Source, Source.id == PipelineRun.source_id)
        .join(KnowledgeBase, KnowledgeBase.id == PipelineRun.knowledge_base_id)
        .where(PipelineRunItem.id == item_uuid)
        .limit(1)
    ).first()
    if row is None:
        return None

    item, run, document, source, kb = row

    # Guardrail check
    guardrail = _check_retry_guardrails(session, item=item, run=run)
    if guardrail is not None:
        return {**guardrail, "retried": False}

    create_audit_event(
        session,
        event_type="retry_start",
        actor=operator,
        knowledge_base_id=kb.id,
        document_id=document.id,
        run_id=run.id,
        item_id=item.id,
        payload_json={"document_uri": document.uri, "run_type": run.run_type},
    )
    session.commit()

    from ragrig.db.models import DocumentVersion
    from ragrig.ingestion.pipeline import _select_parser
    from ragrig.parsers.base import parse_with_timeout

    config_snapshot = run.config_snapshot_json or {}

    # Determine file path from metadata or config
    file_path = None
    metadata_path = (item.metadata_json or {}).get("object_key") or (item.metadata_json or {}).get(
        "file_name"
    )
    doc_uri = document.uri

    if run.run_type == "s3_ingest":
        # S3 items need to be re-downloaded
        from ragrig.plugins.sources.s3.client import build_boto3_client
        from ragrig.plugins.sources.s3.connector import _resolve_secrets

        try:
            secrets = _resolve_secrets(config_snapshot, env={})
            client = build_boto3_client({**config_snapshot, **secrets.__dict__})
            from tempfile import NamedTemporaryFile

            bucket = str(config_snapshot.get("bucket", ""))
            key = metadata_path or ""
            body = client.download_object(bucket=bucket, key=key)
            suffix = Path(key).suffix
            tmp = NamedTemporaryFile(suffix=suffix, delete=False)
            tmp.write(body)
            tmp.close()
            file_path = Path(tmp.name)
        except Exception as exc:
            error_msg = _sanitize_retry_error(str(exc))
            item.status = "failed"
            item.error_message = error_msg
            item.finished_at = datetime.now(timezone.utc)
            session.commit()
            create_audit_event(
                session,
                event_type="retry_complete",
                actor=operator,
                knowledge_base_id=kb.id,
                document_id=document.id,
                run_id=run.id,
                item_id=item.id,
                payload_json={"status": "failed", "error_message": error_msg},
            )
            session.commit()
            return {
                "id": str(item.id),
                "pipeline_run_id": str(run.id),
                "document_uri": doc_uri,
                "status": "failed",
                "error_message": error_msg,
                "retried": True,
            }

    elif run.run_type == "fileshare_ingest":
        from ragrig.plugins.sources.fileshare.connector import (
            _build_client,
            _resolve_fileshare_secrets,
        )

        try:
            secrets = _resolve_fileshare_secrets(config_snapshot, env={})
            client = _build_client(config_snapshot, secrets)
        except Exception as exc:
            error_msg = _sanitize_retry_error(str(exc))
            item.status = "failed"
            item.error_message = error_msg
            item.finished_at = datetime.now(timezone.utc)
            session.commit()
            create_audit_event(
                session,
                event_type="retry_complete",
                actor=operator,
                knowledge_base_id=kb.id,
                document_id=document.id,
                run_id=run.id,
                item_id=item.id,
                payload_json={"status": "failed", "error_message": error_msg},
            )
            session.commit()
            return {
                "id": str(item.id),
                "pipeline_run_id": str(run.id),
                "document_uri": doc_uri,
                "status": "failed",
                "error_message": error_msg,
                "retried": True,
            }
        try:
            from tempfile import NamedTemporaryFile

            remote_path = metadata_path or ""
            body = client.download_file(remote_path)
            suffix = Path(remote_path).suffix
            tmp = NamedTemporaryFile(suffix=suffix, delete=False)
            tmp.write(body)
            tmp.close()
            file_path = Path(tmp.name)
        except Exception as exc:
            error_msg = _sanitize_retry_error(str(exc))
            item.status = "failed"
            item.error_message = error_msg
            item.finished_at = datetime.now(timezone.utc)
            session.commit()
            create_audit_event(
                session,
                event_type="retry_complete",
                actor=operator,
                knowledge_base_id=kb.id,
                document_id=document.id,
                run_id=run.id,
                item_id=item.id,
                payload_json={"status": "failed", "error_message": error_msg},
            )
            session.commit()
            return {
                "id": str(item.id),
                "pipeline_run_id": str(run.id),
                "document_uri": doc_uri,
                "status": "failed",
                "error_message": error_msg,
                "retried": True,
            }
    else:
        # Local ingestion - file path from document URI
        file_path = Path(document.uri)

    if file_path is None or not file_path.exists():
        error_msg = "file not found for retry"
        item.status = "failed"
        item.error_message = error_msg
        item.finished_at = datetime.now(timezone.utc)
        session.commit()
        create_audit_event(
            session,
            event_type="retry_complete",
            actor=operator,
            knowledge_base_id=kb.id,
            document_id=document.id,
            run_id=run.id,
            item_id=item.id,
            payload_json={"status": "failed", "error_message": error_msg},
        )
        session.commit()
        return {
            "id": str(item.id),
            "pipeline_run_id": str(run.id),
            "document_uri": doc_uri,
            "status": "failed",
            "error_message": error_msg,
            "retried": True,
        }

    # Re-process the file
    try:
        parser = _select_parser(file_path)
        parse_result = parse_with_timeout(parser, file_path, timeout_seconds=30.0)

        document.content_hash = parse_result.content_hash
        document.mime_type = parse_result.mime_type
        document.metadata_json = parse_result.metadata

        version = DocumentVersion(
            document_id=document.id,
            version_number=0,  # will be set by _get_next_version
            content_hash=parse_result.content_hash,
            parser_name=parse_result.parser_name,
            parser_config_json={"plugin_id": _parser_plugin_id(parse_result.parser_name)},
            extracted_text=parse_result.extracted_text,
            metadata_json=parse_result.metadata,
        )
        from ragrig.repositories import get_next_version_number

        version.version_number = get_next_version_number(session, document_id=document.id)
        session.add(version)
        session.flush()

        item.status = "success"
        item.error_message = None
        item.metadata_json = {
            **(item.metadata_json or {}),
            "retry_version_number": version.version_number,
        }
        item.finished_at = datetime.now(timezone.utc)

        # Update run counts
        run.failure_count = max(0, (run.failure_count or 0) - 1)
        run.success_count = (run.success_count or 0) + 1

        session.commit()

        create_audit_event(
            session,
            event_type="retry_complete",
            actor=operator,
            knowledge_base_id=kb.id,
            document_id=document.id,
            run_id=run.id,
            item_id=item.id,
            payload_json={
                "status": "success",
                "new_version_number": version.version_number,
            },
        )
        session.commit()

        return {
            "id": str(item.id),
            "pipeline_run_id": str(run.id),
            "document_uri": doc_uri,
            "status": "success",
            "retried": True,
            "new_version_number": version.version_number,
        }
    except Exception as exc:
        error_msg = _sanitize_retry_error(str(exc))
        item.status = "failed"
        item.error_message = error_msg
        item.finished_at = datetime.now(timezone.utc)
        session.commit()
        create_audit_event(
            session,
            event_type="retry_complete",
            actor=operator,
            knowledge_base_id=kb.id,
            document_id=document.id,
            run_id=run.id,
            item_id=item.id,
            payload_json={"status": "failed", "error_message": error_msg},
        )
        session.commit()
        return {
            "id": str(item.id),
            "pipeline_run_id": str(run.id),
            "document_uri": doc_uri,
            "status": "failed",
            "error_message": error_msg,
            "retried": True,
        }
    finally:
        if file_path and run.run_type in ("s3_ingest", "fileshare_ingest"):
            try:
                file_path.unlink(missing_ok=True)
            except OSError:
                pass


def retry_pipeline_run(
    session: Session,
    *,
    run_id: str,
    operator: str | None = None,
    new_snapshot: bool = False,
) -> dict[str, Any] | None:
    """Retry all failed items in a pipeline run.

    If new_snapshot is False, reuses the original config_snapshot_json.
    If new_snapshot is True, creates a new snapshot from current config.
    Returns a summary of retry results.
    """
    run_uuid = uuid.UUID(run_id)
    run = session.get(PipelineRun, run_uuid)
    if run is None:
        return None

    # Run-level guardrail check
    guardrail = _check_run_retry_guardrails(session, run=run)
    if guardrail is not None:
        return {**guardrail, "retried": False}

    create_audit_event(
        session,
        event_type="retry_start",
        actor=operator,
        knowledge_base_id=run.knowledge_base_id,
        run_id=run.id,
        payload_json={"run_type": run.run_type},
    )
    session.commit()

    # Collect failed items
    failed_items = (
        session.query(PipelineRunItem)
        .filter(
            PipelineRunItem.pipeline_run_id == run_uuid,
            PipelineRunItem.status == "failed",
        )
        .all()
    )

    if not failed_items:
        create_audit_event(
            session,
            event_type="retry_complete",
            actor=operator,
            knowledge_base_id=run.knowledge_base_id,
            run_id=run.id,
            payload_json={"status": "no_failed_items"},
        )
        session.commit()
        return {
            "run_id": run_id,
            "status": "no_failed_items",
            "message": "No failed items to retry.",
            "retried": 0,
            "succeeded": 0,
            "failed": 0,
        }

    results: list[dict[str, Any]] = []
    for item in failed_items:
        result = retry_pipeline_run_item(session, item_id=str(item.id), operator=operator)
        if result is not None:
            results.append(result)

    succeeded = sum(1 for r in results if r.get("status") == "success")
    still_failed = sum(1 for r in results if r.get("status") == "failed")

    create_audit_event(
        session,
        event_type="retry_complete",
        actor=operator,
        knowledge_base_id=run.knowledge_base_id,
        run_id=run.id,
        payload_json={
            "status": "completed",
            "retried": len(results),
            "succeeded": succeeded,
            "failed": still_failed,
        },
    )
    session.commit()

    return {
        "run_id": run_id,
        "status": "completed",
        "retried": len(results),
        "succeeded": succeeded,
        "failed": still_failed,
        "items": results,
    }


def resume_pipeline_dag(
    session: Session,
    *,
    run_id: str,
) -> dict[str, Any] | None:
    """Resume a persisted ingestion DAG from its first incomplete node."""
    return resume_ingestion_dag(session, pipeline_run_id=run_id)


def _sanitize_retry_error(message: str) -> str:
    """Remove secret-like patterns from error messages."""
    for fragment in _CONSOLE_FORBIDDEN_FRAGMENTS:
        message = message.replace(fragment, "[redacted]")
    return message


def _parser_plugin_id(parser_name: str) -> str:
    if parser_name == "plaintext":
        return "parser.text"
    return f"parser.{parser_name}"


# ── Ops Diagnostics ────────────────────────────────────────────────────

_OPS_ARTIFACTS_DIR = Path(__file__).resolve().parents[2] / "docs" / "operations" / "artifacts"


def _load_ops_artifact(name: str) -> dict[str, Any] | None:
    """Load an ops summary artifact, returning None if missing or corrupt."""
    import json as _json

    path = _OPS_ARTIFACTS_DIR / f"{name}.json"
    if not path.exists():
        return None
    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
        _assert_console_no_secrets(data, f"ops-{name}")
        return data
    except (OSError, ValueError, _json.JSONDecodeError):
        return None


def get_ops_diagnostics() -> dict[str, Any]:
    """Return ops diagnostics summary for Web Console display.

    Reads artifacts from docs/operations/artifacts/ and returns:
    - deploy summary
    - backup summary
    - restore summary
    - upgrade summary

    Missing/corrupt artifacts are reported as degraded/failure.
    Never includes plaintext DSN, token, API key, or object storage secret.
    """
    artifacts: list[str] = [
        "ops-deploy-summary",
        "ops-backup-summary",
        "ops-restore-summary",
        "ops-upgrade-summary",
    ]

    summaries: dict[str, Any] = {}
    overall_status = "success"

    for name in artifacts:
        data = _load_ops_artifact(name)
        if data is None:
            summaries[name] = {
                "available": False,
                "artifact": name,
                "status": "failure",
                "reason": "artifact not found or corrupt",
            }
            overall_status = "degraded"
        else:
            op_status = data.get("operation_status", "unknown")
            summaries[name] = {
                "available": True,
                "artifact": data.get("artifact", name),
                "version": data.get("version", ""),
                "snapshot_id": data.get("snapshot_id"),
                "schema_revision": data.get("schema_revision"),
                "status": op_status,
                "generated_at": data.get("generated_at"),
                "check_count": len(data.get("verification_checks", [])),
            }
            if op_status != "success":
                overall_status = "degraded"

    result: dict[str, Any] = {
        "overall_status": overall_status,
        "summaries": summaries,
        "artifacts_dir": str(_OPS_ARTIFACTS_DIR),
    }

    _assert_console_no_secrets(result, "ops-diagnostics")
    return result
