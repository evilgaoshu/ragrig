from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, inspect, select, text
from sqlalchemy.orm import Session

from ragrig import __version__
from ragrig.acl import acl_summary_from_metadata
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
)
from ragrig.formats import FormatStatus, get_format_registry
from ragrig.plugins import PluginConfigValidationError, get_plugin_registry
from ragrig.providers import get_provider_registry
from ragrig.vectorstore.base import VectorBackendHealth


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
