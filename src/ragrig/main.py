import re
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from ragrig import __version__
from ragrig.acl import acl_summary_from_metadata
from ragrig.answer import (
    NoEvidenceError,
    generate_answer,
)
from ragrig.answer import (
    ProviderUnavailableError as AnswerProviderUnavailableError,
)
from ragrig.auth import ensure_default_workspace
from ragrig.config import Settings, get_settings
from ragrig.db.engine import create_db_engine
from ragrig.db.models import KnowledgeBase, KnowledgeGraphRelation
from ragrig.db.session import get_session as _get_session_default
from ragrig.deps import (
    AuthContext,
    get_auth_context,
    require_admin_auth,
    require_write_auth,
)
from ragrig.evaluation import (
    build_evaluation_list_report,
    build_evaluation_run_report,
    list_runs_from_store,
    load_run_from_store,
    run_evaluation,
)
from ragrig.health import create_database_check
from ragrig.ingestion.web_import import WebsiteImportError
from ragrig.knowledge_graph import (
    KnowledgeGraphBuildRequest,
    KnowledgeGraphNotFoundError,
    get_knowledge_graph,
    rebuild_knowledge_graph,
)
from ragrig.local_pilot import (
    ModelConfigError,
    import_website_pages,
)
from ragrig.local_pilot.model_config import resolve_env_config
from ragrig.plugins.sinks.agent_access.connector import export_to_agent_endpoint
from ragrig.plugins.sinks.azure_blob.connector import export_to_azure_blob
from ragrig.plugins.sinks.backblaze_b2.connector import export_to_backblaze_b2
from ragrig.plugins.sinks.cloudflare_r2.connector import export_to_cloudflare_r2
from ragrig.plugins.sinks.gcs.connector import export_to_gcs
from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage
from ragrig.plugins.sinks.webhook.connector import export_to_webhook
from ragrig.ratelimit import RateLimiter
from ragrig.repositories import (
    create_audit_event,
    delete_kb_permission,
    get_knowledge_base_by_name,
    get_or_create_knowledge_base,
    list_kb_permissions,
    set_kb_permission,
)
from ragrig.retrieval import (
    EmbeddingProfileMismatchError,
    EmptyQueryError,
    InvalidTopKError,
    KnowledgeBaseNotFoundError,
    RerankerUnavailableError,
    RetrievalError,
    search_knowledge_base,
)
from ragrig.routers.admin import router as admin_router
from ragrig.routers.audit import router as audit_router
from ragrig.routers.auth import router as auth_router
from ragrig.routers.catalog_ops import router as catalog_ops_router
from ragrig.routers.conflicts import router as conflicts_router
from ragrig.routers.conversations import router as conversations_router
from ragrig.routers.mcp import router as mcp_router
from ragrig.routers.openai_compat import router as openai_compat_router
from ragrig.routers.processing_profiles import router as processing_profiles_router
from ragrig.routers.retention import router as retention_router
from ragrig.routers.runtime import (
    get_workspace_id,
    knowledge_base_access_error,
    set_runtime_state,
)
from ragrig.routers.source_webhooks import router as source_webhooks_router
from ragrig.routers.sources_pipeline import router as sources_pipeline_router
from ragrig.routers.system import router as system_router
from ragrig.routers.usage import router as usage_router
from ragrig.tasks import (
    cleanup_staging_dir,
    create_upload_pipeline_run,
    default_task_executor,
    enqueue_task,
    run_upload_pipeline,
    sanitize_filename,
    validate_and_stage_uploads,
)
from ragrig.understanding import (
    DocumentVersionNotFoundError,
    ProviderUnavailableError,
    UnderstandAllRequest,
    UnderstandingRequest,
    UnderstandingRunFilter,
    build_knowledge_map,
    compare_understanding_runs,
    export_understanding_run,
    export_understanding_runs,
    generate_document_understanding,
    get_understanding_by_version,
    get_understanding_coverage,
    get_understanding_runs,
    knowledge_map_to_dict,
    understand_all_versions,
)
from ragrig.vectorstore import get_vector_backend
from ragrig.web_console import (
    build_permission_preview,
    get_understanding_run_detail,
    list_document_version_chunks,
    list_documents,
    list_knowledge_bases,
    list_understanding_runs,
)


class EvaluationRunRequest(BaseModel):
    golden_path: str
    knowledge_base: str = "fixture-local"
    top_k: int = Field(default=5, ge=1, le=50)
    provider: str | None = None
    model: str | None = None
    dimensions: int | None = Field(default=None, gt=0)
    baseline_path: str | None = None
    mode: str = Field(
        default="dense",
        pattern=(
            r"^(dense|hybrid|rerank|hybrid_rerank|graph|hybrid_graph|"
            r"graph_rerank|hybrid_graph_rerank)$"
        ),
    )
    lexical_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    vector_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    candidate_k: int = Field(default=20, ge=1, le=200)
    reranker_provider: str | None = None
    reranker_model: str | None = None
    graph_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    graph_depth: int = Field(default=1, ge=0, le=2)


class RetrievalSearchRequest(BaseModel):
    knowledge_base: str
    query: str
    top_k: int = Field(default=5, ge=1, le=50)
    role: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    provider: str | None = None
    model: str | None = None
    dimensions: int | None = Field(default=None, gt=0)
    principal_ids: list[str] | None = None
    enforce_acl: bool = True
    # ── Hybrid / rerank fields (backward-compatible) ──
    mode: str = Field(
        default="dense",
        pattern=(
            r"^(dense|hybrid|rerank|hybrid_rerank|graph|hybrid_graph|"
            r"graph_rerank|hybrid_graph_rerank)$"
        ),
    )
    lexical_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    vector_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    candidate_k: int = Field(default=20, ge=1, le=200)
    reranker_provider: str | None = None
    reranker_model: str | None = None
    graph_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    graph_depth: int = Field(default=1, ge=0, le=2)


class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class KnowledgeGraphRelationFeedbackRequest(BaseModel):
    verdict: str = Field(pattern=r"^(incorrect|correct|needs_review)$")
    note: str | None = Field(default=None, max_length=500)


class RetrievalPreferenceRequest(BaseModel):
    mode: str = Field(
        default="dense",
        pattern=(
            r"^(dense|hybrid|rerank|hybrid_rerank|graph|hybrid_graph|"
            r"graph_rerank|hybrid_graph_rerank)$"
        ),
    )
    lexical_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    vector_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    candidate_k: int = Field(default=20, ge=1, le=200)
    reranker_provider: str | None = Field(default=None, max_length=128)
    reranker_model: str | None = Field(default=None, max_length=256)
    graph_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    graph_depth: int = Field(default=1, ge=0, le=2)


class RoleModelConfigRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class KbPermissionRequest(BaseModel):
    role: str = Field(pattern=r"^(admin|editor|viewer|none)$")


class AnswerRequest(BaseModel):
    knowledge_base: str
    query: str
    top_k: int = Field(default=5, ge=1, le=50)
    role: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    role_model_config: dict[str, Any] | None = None
    provider: str = "deterministic-local"
    model: str | None = None
    config: dict[str, Any] | None = None
    answer_provider: str | None = None
    answer_model: str | None = None
    answer_config: dict[str, Any] | None = None
    dimensions: int | None = Field(default=None, gt=0)
    principal_ids: list[str] | None = None
    enforce_acl: bool = True
    stream: bool = False
    mode: str = Field(
        default="dense",
        pattern=(
            r"^(dense|hybrid|rerank|hybrid_rerank|graph|hybrid_graph|"
            r"graph_rerank|hybrid_graph_rerank)$"
        ),
    )
    lexical_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    vector_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    candidate_k: int = Field(default=20, ge=1, le=200)
    reranker_provider: str | None = None
    reranker_model: str | None = None
    graph_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    graph_depth: int = Field(default=1, ge=0, le=2)


class PermissionPreviewRequest(BaseModel):
    principal_ids: list[str] | None = None


class WebsiteImportRequest(BaseModel):
    urls: list[str]
    sitemap_url: str | None = None
    bearer_token: str | None = None
    cookies: dict[str, str] | None = None
    basic_auth_username: str | None = None
    basic_auth_password: str | None = None


class AgentAccessExportRequest(BaseModel):
    endpoint_url: str
    api_key: str
    hmac_secret: str | None = None
    batch_size: int = 100
    timeout_seconds: float = 30.0
    verify_tls: bool = True
    dry_run: bool = False


class WebhookExportRequest(BaseModel):
    endpoint_url: str
    hmac_secret: str | None = None
    format: str = "ndjson"
    extra_headers: dict[str, str] | None = None
    batch_size: int = 200
    timeout_seconds: float = 30.0
    verify_tls: bool = True
    dry_run: bool = False


class ObjectStorageExportRequest(BaseModel):
    bucket: str
    endpoint_url: str | None = None
    access_key: str | None = None
    secret_key: str | None = None
    region: str | None = None
    use_path_style: bool = False
    verify_tls: bool = True
    path_template: str = "{knowledge_base}/{run_id}/{artifact}.{format}"
    overwrite: bool = True
    dry_run: bool = False
    include_retrieval_artifact: bool = True
    include_markdown_summary: bool = True
    parquet_export: bool = False


class CloudflareR2ExportRequest(BaseModel):
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    prefix: str = ""
    jurisdiction: str | None = None
    path_template: str = "{knowledge_base}/{run_id}/{artifact}.{format}"
    overwrite: bool = True
    dry_run: bool = False
    include_retrieval_artifact: bool = True
    include_markdown_summary: bool = True
    parquet_export: bool = False


class BackblazeB2ExportRequest(BaseModel):
    region: str
    key_id: str
    application_key: str
    bucket: str
    prefix: str = ""
    path_template: str = "{knowledge_base}/{run_id}/{artifact}.{format}"
    overwrite: bool = True
    dry_run: bool = False
    include_retrieval_artifact: bool = True
    include_markdown_summary: bool = True
    parquet_export: bool = False


class AzureBlobExportRequest(BaseModel):
    account_name: str
    account_key: str
    container: str
    prefix: str = ""
    path_template: str = "{knowledge_base}/{run_id}/{artifact}.{format}"
    overwrite: bool = True
    dry_run: bool = False
    include_retrieval_artifact: bool = True
    include_markdown_summary: bool = True
    parquet_export: bool = False


class GcsExportRequest(BaseModel):
    access_key: str
    secret_key: str
    bucket: str
    prefix: str = ""
    path_template: str = "{knowledge_base}/{run_id}/{artifact}.{format}"
    overwrite: bool = True
    dry_run: bool = False
    include_retrieval_artifact: bool = True
    include_markdown_summary: bool = True
    parquet_export: bool = False


def _serialize_error(exc: RetrievalError) -> dict[str, Any]:
    return {
        "error": {
            "code": exc.code,
            "message": str(exc),
            "details": exc.details,
        }
    }


async def _answer_sse_stream(payload: dict[str, Any]):
    """Yield text/event-stream chunks for /retrieval/answer streaming responses.

    Emits one event per ~12-character slice of the answer text, then a final
    ``done`` event carrying citations + grounding metadata, then ``[DONE]``.
    """
    import asyncio
    import json

    answer = payload.get("answer") or ""
    size = 12
    pieces = [answer[i : i + size] for i in range(0, len(answer), size)] or [""]
    for piece in pieces:
        yield "event: delta\n"
        yield f"data: {json.dumps({'text': piece})}\n\n"
        await asyncio.sleep(0)

    final_meta = {
        "citations": payload.get("citations", []),
        "evidence_chunks": payload.get("evidence_chunks", []),
        "model": payload.get("model"),
        "provider": payload.get("provider"),
        "grounding_status": payload.get("grounding_status"),
        "refusal_reason": payload.get("refusal_reason"),
        "retrieval_trace": payload.get("retrieval_trace", {}),
    }
    yield "event: done\n"
    yield f"data: {json.dumps(final_meta)}\n\n"
    yield "data: [DONE]\n\n"


def _safe_chunk_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe = dict(metadata or {})
    if "acl" in safe:
        safe["acl"] = acl_summary_from_metadata(metadata)
    return safe


def _summarize_relation_feedback(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"incorrect": 0, "correct": 0, "needs_review": 0}
    for item in items:
        verdict = item.get("verdict")
        if verdict in counts:
            counts[verdict] += 1
    return {
        "total": sum(counts.values()),
        "incorrect": counts["incorrect"],
        "correct": counts["correct"],
        "needs_review": counts["needs_review"],
        "latest_verdict": items[-1].get("verdict") if items else None,
        "latest_at": items[-1].get("created_at") if items else None,
    }


def _role_model_selection(
    role: str | None,
    role_model_config: dict[str, Any] | None,
) -> tuple[dict[str, Any], str | None]:
    if not role or not role_model_config:
        return {}, None
    raw = role_model_config.get(role)
    matched_role = role
    if raw is None:
        raw = role_model_config.get("default")
        matched_role = "default" if raw is not None else role
    if raw is None:
        return {"role": role, "matched": False}, None
    if not isinstance(raw, dict):
        return {}, f"role_model_config entry for {matched_role!r} must be an object"

    selection: dict[str, Any] = {
        "role": role,
        "matched": True,
        "matched_role": matched_role,
    }
    string_fields = ("provider", "model", "answer_provider", "answer_model")
    config_fields = ("config", "answer_config")
    for field in string_fields:
        if field in raw:
            value = raw[field]
            if value is not None and not isinstance(value, str):
                return {}, f"role_model_config.{matched_role}.{field} must be a string"
            if value is not None:
                selection[field] = value
    for field in config_fields:
        if field in raw:
            value = raw[field]
            if value is not None and not isinstance(value, dict):
                return {}, f"role_model_config.{matched_role}.{field} must be an object"
            if value is not None:
                selection[field] = value
    return selection, None


def _validate_role_model_config(config: dict[str, Any]) -> str | None:
    allowed_fields = {
        "provider",
        "model",
        "config",
        "answer_provider",
        "answer_model",
        "answer_config",
    }
    role_pattern = re.compile(r"^[A-Za-z0-9_.:-]+$")
    for role, entry in config.items():
        if not isinstance(role, str) or not role_pattern.fullmatch(role):
            return f"role_model_config role {role!r} must match {role_pattern.pattern}"
        if not isinstance(entry, dict):
            return f"role_model_config entry for {role!r} must be an object"
        unknown = sorted(set(entry) - allowed_fields)
        if unknown:
            return f"role_model_config.{role} has unsupported field(s): {', '.join(unknown)}"
        for field in ("provider", "model", "answer_provider", "answer_model"):
            value = entry.get(field)
            if value is not None and not isinstance(value, str):
                return f"role_model_config.{role}.{field} must be a string"
        for field in ("config", "answer_config"):
            value = entry.get(field)
            if value is not None and not isinstance(value, dict):
                return f"role_model_config.{role}.{field} must be an object"
    return None


def _kb_role_model_config(knowledge_base: KnowledgeBase | None) -> dict[str, Any] | None:
    if knowledge_base is None:
        return None
    metadata = (
        knowledge_base.metadata_json if isinstance(knowledge_base.metadata_json, dict) else {}
    )
    config = metadata.get("role_model_config")
    return config if isinstance(config, dict) else None


def _public_role_model_config(config: dict[str, Any] | None) -> dict[str, Any]:
    public: dict[str, Any] = {}
    for role, entry in (config or {}).items():
        if not isinstance(role, str) or not isinstance(entry, dict):
            continue
        safe = {
            field: entry[field]
            for field in ("provider", "model", "answer_provider", "answer_model")
            if isinstance(entry.get(field), str)
        }
        if isinstance(entry.get("config"), dict):
            safe["has_config"] = True
        if isinstance(entry.get("answer_config"), dict):
            safe["has_answer_config"] = True
        public[role] = safe
    return public


def _public_role_model_selection(selection: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in selection.items() if key not in {"config", "answer_config"}
    }


def _kb_retrieval_preferences(knowledge_base: KnowledgeBase | None) -> dict[str, Any]:
    defaults = RetrievalPreferenceRequest().model_dump(mode="json")
    if knowledge_base is None:
        return defaults
    metadata = (
        knowledge_base.metadata_json if isinstance(knowledge_base.metadata_json, dict) else {}
    )
    raw = metadata.get("retrieval_preferences")
    if not isinstance(raw, dict):
        return defaults
    try:
        return RetrievalPreferenceRequest(**raw).model_dump(mode="json")
    except ValueError:
        return defaults


def create_runtime_settings(settings: Settings | None = None) -> Settings:
    active_settings = settings or get_settings()
    payload = active_settings.model_dump()
    payload["database_url"] = active_settings.runtime_database_url
    return Settings(**payload)


def _sanitize_filename(filename: str) -> str:
    return sanitize_filename(filename)


def create_app(
    check_database: Callable[[], None] | None = None,
    session_factory: Callable[[], Session] | None = None,
    settings: Settings | None = None,
    task_executor=None,
) -> FastAPI:
    active_settings = settings or get_settings()
    database_check = check_database or create_database_check(active_settings)
    default_session_factory = None
    if session_factory is None:
        default_session_factory = sessionmaker(
            bind=create_db_engine(active_settings),
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    active_task_executor = task_executor or default_task_executor()
    rate_limiter = RateLimiter(active_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            yield
        finally:
            shutdown_task_executor()

    app = FastAPI(title="RAGRig", version=__version__, lifespan=lifespan)

    if active_settings.ragrig_metrics_enabled:
        from ragrig.metrics import setup_metrics

        setup_metrics(app)

    from ragrig.otel import setup_otel

    setup_otel(app, active_settings)

    def shutdown_task_executor() -> None:
        shutdown = getattr(active_task_executor, "shutdown", None)
        if shutdown is not None:
            shutdown(wait=True)

    def resolve_vector_backend():
        if active_settings.vector_backend == "pgvector":
            return None
        return get_vector_backend(active_settings)

    def get_session() -> Session:
        if session_factory is None:
            assert default_session_factory is not None
            session = default_session_factory()
        else:
            session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[_get_session_default] = get_session
    app.dependency_overrides[get_settings] = lambda: active_settings

    def get_session_factory() -> Callable[[], Session]:
        if session_factory is not None:
            return session_factory
        assert default_session_factory is not None
        return default_session_factory

    set_runtime_state(
        app,
        session_factory=get_session_factory(),
        task_executor=active_task_executor,
        database_check=database_check,
    )

    app.include_router(auth_router)
    app.include_router(audit_router)
    app.include_router(conflicts_router)
    app.include_router(retention_router)
    app.include_router(openai_compat_router)
    app.include_router(mcp_router)
    app.include_router(catalog_ops_router)
    app.include_router(processing_profiles_router)
    app.include_router(system_router)
    app.include_router(conversations_router)
    app.include_router(usage_router)
    app.include_router(source_webhooks_router)
    app.include_router(sources_pipeline_router)
    app.include_router(admin_router)

    def _knowledge_base_by_id_for_workspace(
        *,
        session: Session,
        kb_id: str,
        workspace_id: uuid.UUID,
    ) -> tuple[KnowledgeBase | None, JSONResponse | None]:
        try:
            knowledge_base_id = uuid.UUID(str(kb_id))
        except ValueError:
            return None, JSONResponse(
                status_code=404,
                content={"error": "knowledge_base_not_found"},
            )
        knowledge_base = session.get(KnowledgeBase, knowledge_base_id)
        if knowledge_base is None or knowledge_base.workspace_id != workspace_id:
            return None, JSONResponse(
                status_code=404,
                content={"error": "knowledge_base_not_found"},
            )
        return knowledge_base, None

    def _resolve_acl_context(
        *,
        auth: AuthContext,
        requested_principal_ids: list[str] | None,
        requested_enforce_acl: bool,
    ) -> tuple[list[str] | None, bool]:
        if not active_settings.ragrig_auth_enabled:
            return requested_principal_ids, requested_enforce_acl
        return auth.principal_ids, True

    def _knowledge_base_role_error_by_name(
        *,
        session: Session,
        auth: AuthContext,
        kb_name: str,
        workspace_id: uuid.UUID,
        minimum: str,
    ) -> JSONResponse | None:
        kb = get_knowledge_base_by_name(session, kb_name, workspace_id=workspace_id)
        if kb is None:
            return JSONResponse(
                status_code=404,
                content={"error": f"knowledge base '{kb_name}' not found"},
            )
        return knowledge_base_access_error(
            settings=active_settings,
            session=session,
            auth=auth,
            knowledge_base_id=kb.id,
            minimum=minimum,
        )

    def _resolve_evaluation_path(
        raw_path: str | None,
        *,
        default_path: Path,
        allowed_roots: tuple[Path, ...],
    ) -> tuple[Path | None, JSONResponse | None]:
        path = Path(raw_path) if raw_path else default_path
        if not active_settings.ragrig_auth_enabled:
            return path, None
        resolved = path.resolve()
        for root in allowed_roots:
            root_resolved = root.resolve()
            if resolved == root_resolved or root_resolved in resolved.parents:
                return path, None
        allowed = ", ".join(str(root) for root in allowed_roots)
        return None, JSONResponse(
            status_code=400,
            content={"error": f"evaluation path must be under one of: {allowed}"},
        )

    def _record_usage_for_request(
        session: Session,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID | None,
        cost_latency: dict[str, Any] | None,
        request_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Persist the operations list from a cost_latency block as UsageEvents
        and run a budget evaluation for this workspace.

        Failures are swallowed — usage accounting must never break a request.
        """
        try:
            from ragrig.usage import evaluate_budget, record_usage_events

            operations = (cost_latency or {}).get("operations") or []
            if not isinstance(operations, list):
                return
            record_usage_events(
                session,
                workspace_id=workspace_id,
                user_id=user_id,
                operations=operations,
                request_metadata=request_metadata,
            )
            evaluate_budget(session, workspace_id=workspace_id, settings=active_settings)
        except Exception:  # pragma: no cover - usage is best-effort
            import logging

            logging.getLogger(__name__).exception("usage accounting failed")

    @app.get("/knowledge-bases", response_model=None)
    def knowledge_bases(
        session: Annotated[Session, Depends(get_session)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            "items": list_knowledge_bases(
                session,
                settings=active_settings,
                workspace_id=workspace_id,
            )
        }

    @app.post("/knowledge-bases", response_model=None)
    def create_knowledge_base(
        request: KnowledgeBaseCreateRequest,
        session: Annotated[Session, Depends(get_session)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
        _auth: Annotated[AuthContext, Depends(require_write_auth)],
    ) -> JSONResponse:
        name = request.name.strip()
        if not name:
            return JSONResponse(
                status_code=400, content={"error": "knowledge base name is required"}
            )
        ensure_default_workspace(session)
        existed = get_knowledge_base_by_name(session, name, workspace_id=workspace_id) is not None
        kb = get_or_create_knowledge_base(session, name, workspace_id=workspace_id)
        session.commit()
        return JSONResponse(
            status_code=200 if existed else 201,
            content={"id": str(kb.id), "name": kb.name, "created": not existed},
        )

    @app.get("/knowledge-bases/{kb_name}/permissions", response_model=None)
    def list_kb_permissions_endpoint(
        kb_name: str,
        session: Annotated[Session, Depends(get_session)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
        _auth: Annotated[AuthContext, Depends(require_admin_auth)],
    ) -> JSONResponse:
        """List all per-KB permission overrides for a knowledge base.

        Requires admin-or-above role.
        """
        kb = get_knowledge_base_by_name(session, kb_name, workspace_id=workspace_id)
        if kb is None:
            return JSONResponse(
                status_code=404,
                content={"error": f"knowledge base '{kb_name}' not found"},
            )
        return JSONResponse(
            status_code=200,
            content={"items": list_kb_permissions(session, knowledge_base_id=kb.id)},
        )

    @app.put("/knowledge-bases/{kb_name}/permissions/{user_id}", response_model=None)
    def set_kb_permission_endpoint(
        kb_name: str,
        user_id: str,
        request: KbPermissionRequest,
        session: Annotated[Session, Depends(get_session)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
        _auth: Annotated[AuthContext, Depends(require_admin_auth)],
    ) -> JSONResponse:
        """Upsert a per-KB role override for a user.

        Requires admin-or-above role.  ``role='none'`` explicitly denies access.
        """
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            return JSONResponse(status_code=400, content={"error": f"invalid user_id: {user_id!r}"})
        kb = get_knowledge_base_by_name(session, kb_name, workspace_id=workspace_id)
        if kb is None:
            return JSONResponse(
                status_code=404,
                content={"error": f"knowledge base '{kb_name}' not found"},
            )
        set_kb_permission(
            session,
            knowledge_base_id=kb.id,
            user_id=user_uuid,
            role=request.role,
        )
        session.commit()
        return JSONResponse(
            status_code=200,
            content={"knowledge_base": kb_name, "user_id": user_id, "role": request.role},
        )

    @app.delete("/knowledge-bases/{kb_name}/permissions/{user_id}", response_model=None)
    def delete_kb_permission_endpoint(
        kb_name: str,
        user_id: str,
        session: Annotated[Session, Depends(get_session)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
        _auth: Annotated[AuthContext, Depends(require_admin_auth)],
    ) -> JSONResponse:
        """Remove the per-KB permission override for a user.

        Requires admin-or-above role.  Returns 404 if no override existed.
        """
        try:
            user_uuid = uuid.UUID(user_id)
        except ValueError:
            return JSONResponse(status_code=400, content={"error": f"invalid user_id: {user_id!r}"})
        kb = get_knowledge_base_by_name(session, kb_name, workspace_id=workspace_id)
        if kb is None:
            return JSONResponse(
                status_code=404,
                content={"error": f"knowledge base '{kb_name}' not found"},
            )
        existed = delete_kb_permission(
            session,
            knowledge_base_id=kb.id,
            user_id=user_uuid,
        )
        if not existed:
            return JSONResponse(
                status_code=404,
                content={"error": "no permission override found for this user"},
            )
        session.commit()
        return JSONResponse(
            status_code=200,
            content={"knowledge_base": kb_name, "user_id": user_id, "deleted": True},
        )

    @app.get("/documents", response_model=None)
    def documents(
        session: Annotated[Session, Depends(get_session)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    ) -> dict[str, list[dict[str, Any]]]:
        return {"items": list_documents(session, workspace_id=workspace_id)}

    @app.get("/understanding-runs", response_model=None)
    def web_understanding_runs(
        session: Annotated[Session, Depends(get_session)],
        knowledge_base_id: str | None = None,
        limit: int = 20,
        provider: str | None = None,
        model: str | None = None,
        profile_id: str | None = None,
        status: str | None = None,
        started_after: str | None = None,
        started_before: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            "items": list_understanding_runs(
                session,
                knowledge_base_id=knowledge_base_id,
                limit=limit,
                provider=provider,
                model=model,
                profile_id=profile_id,
                status=status,
                started_after=started_after,
                started_before=started_before,
            ),
        }

    @app.get("/understanding-runs/{run_id}", response_model=None)
    def web_understanding_run_detail(
        run_id: str,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any] | JSONResponse:
        detail = get_understanding_run_detail(session, run_id)
        if detail is None:
            return JSONResponse(status_code=404, content={"error": "understanding_run_not_found"})
        return detail

    @app.get("/understanding-runs/{run_id}/export", response_model=None)
    def export_understanding_run_endpoint(
        run_id: str,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any] | JSONResponse:
        result = export_understanding_run(session, run_id)
        if result is None:
            return JSONResponse(status_code=404, content={"error": "understanding_run_not_found"})
        return result

    @app.get("/knowledge-bases/{kb_id}/understanding-runs/export", response_model=None)
    def export_understanding_runs_endpoint(
        kb_id: str,
        session: Annotated[Session, Depends(get_session)],
        provider: str | None = None,
        model: str | None = None,
        profile_id: str | None = None,
        status: str | None = None,
        started_after: str | None = None,
        started_before: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        filters = UnderstandingRunFilter(
            provider=provider,
            model=model,
            profile_id=profile_id,
            status=status,
            started_after=started_after,
            started_before=started_before,
            limit=limit,
        )
        return export_understanding_runs(session, kb_id, filters=filters)

    @app.get("/understanding-runs/{run_id}/diff", response_model=None)
    def diff_understanding_runs_endpoint(
        run_id: str,
        session: Annotated[Session, Depends(get_session)],
        against: str,
    ) -> dict[str, Any] | JSONResponse:
        result = compare_understanding_runs(session, run_id, against)
        if result is None:
            return JSONResponse(status_code=404, content={"error": "understanding_run_not_found"})
        return result

    @app.get("/document-versions/{document_version_id}/chunks", response_model=None)
    def document_version_chunks(
        document_version_id: str,
        session: Annotated[Session, Depends(get_session)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    ) -> dict[str, list[dict[str, Any]]]:
        return {
            "items": list_document_version_chunks(
                session,
                document_version_id,
                workspace_id=workspace_id,
            )
        }

    @app.post("/document-versions/{document_version_id}/understand", response_model=None)
    def understand_document_version(
        document_version_id: str,
        request: UnderstandingRequest,
        session: Annotated[Session, Depends(get_session)],
        _auth: Annotated[AuthContext, Depends(require_write_auth)],
    ) -> dict[str, Any] | JSONResponse:
        try:
            record = generate_document_understanding(
                session,
                document_version_id=document_version_id,
                provider=request.provider,
                model=request.model or "",
                profile_id=request.profile_id,
            )
        except DocumentVersionNotFoundError as exc:
            return JSONResponse(status_code=404, content={"error": exc.code, "message": str(exc)})
        except ProviderUnavailableError as exc:
            return JSONResponse(status_code=503, content={"error": exc.code, "message": str(exc)})
        return {
            "id": record.id,
            "document_version_id": record.document_version_id,
            "profile_id": record.profile_id,
            "provider": record.provider,
            "model": record.model,
            "input_hash": record.input_hash,
            "status": record.status,
            "result": record.result,
            "error": record.error,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    @app.get("/document-versions/{document_version_id}/understanding", response_model=None)
    def get_document_understanding(
        document_version_id: str,
        session: Annotated[Session, Depends(get_session)],
        allow_missing: bool = False,
    ) -> dict[str, Any] | JSONResponse:
        record = get_understanding_by_version(session, document_version_id)
        if record is None:
            content = {
                "error": "understanding_not_found",
                "message": f"No understanding result for document version '{document_version_id}'.",
            }
            if allow_missing:
                return JSONResponse(status_code=200, content=content)
            return JSONResponse(
                status_code=404,
                content=content,
            )
        return {
            "id": record.id,
            "document_version_id": record.document_version_id,
            "profile_id": record.profile_id,
            "provider": record.provider,
            "model": record.model,
            "input_hash": record.input_hash,
            "status": record.status,
            "result": record.result,
            "error": record.error,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
        }

    @app.post("/knowledge-bases/{kb_id}/understand-all", response_model=None)
    def understand_all(
        kb_id: str,
        request: UnderstandAllRequest,
        session: Annotated[Session, Depends(get_session)],
        _auth: Annotated[AuthContext, Depends(require_write_auth)],
        x_operator: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any] | JSONResponse:
        operator = x_operator
        try:
            result = understand_all_versions(
                session,
                knowledge_base_id=kb_id,
                provider=request.provider,
                model=request.model,
                profile_id=request.profile_id,
                trigger_source="api",
                operator=operator,
            )
        except ProviderUnavailableError as exc:
            return JSONResponse(status_code=503, content={"error": exc.code, "message": str(exc)})

        # Look up the most recent run for this KB to include run_id
        import uuid as _uuid

        from ragrig.db.models import UnderstandingRun

        kb_uuid = _uuid.UUID(kb_id)
        latest_run = (
            session.query(UnderstandingRun)
            .filter(UnderstandingRun.knowledge_base_id == kb_uuid)
            .order_by(UnderstandingRun.started_at.desc())
            .first()
        )
        return {
            "run_id": str(latest_run.id) if latest_run else None,
            "total": result.total,
            "created": result.created,
            "skipped": result.skipped,
            "failed": result.failed,
            "errors": [{"version_id": e.version_id, "error": e.error} for e in result.errors],
        }

    @app.get("/knowledge-bases/{kb_id}/understanding-coverage", response_model=None)
    def understanding_coverage(
        kb_id: str,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any]:
        coverage = get_understanding_coverage(session, kb_id)
        return {
            "total_versions": coverage.total_versions,
            "completed": coverage.completed,
            "missing": coverage.missing,
            "stale": coverage.stale,
            "failed": coverage.failed,
            "completeness_score": coverage.completeness_score,
            "recent_errors": [
                {
                    "document_version_id": e.document_version_id,
                    "profile_id": e.profile_id,
                    "provider": e.provider,
                    "error": e.error,
                }
                for e in coverage.recent_errors
            ],
        }

    @app.get("/knowledge-bases/{kb_id}/knowledge-map", response_model=None)
    def knowledge_map(
        kb_id: str,
        session: Annotated[Session, Depends(get_session)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
        auth: Annotated[AuthContext, Depends(get_auth_context)],
        profile_id: str = "*.understand.default",
    ) -> dict[str, Any] | JSONResponse:
        knowledge_base, kb_error = _knowledge_base_by_id_for_workspace(
            session=session,
            kb_id=kb_id,
            workspace_id=workspace_id,
        )
        if kb_error is not None:
            return kb_error
        assert knowledge_base is not None
        access_error = knowledge_base_access_error(
            settings=active_settings,
            session=session,
            auth=auth,
            knowledge_base_id=knowledge_base.id,
            minimum="viewer",
        )
        if access_error is not None:
            return access_error
        result = build_knowledge_map(session, kb_id, profile_id=profile_id)
        if result is None:
            return JSONResponse(status_code=404, content={"error": "knowledge_base_not_found"})
        return knowledge_map_to_dict(result)

    @app.get("/knowledge-bases/{kb_id}/knowledge-graph", response_model=None)
    def knowledge_graph(
        kb_id: str,
        session: Annotated[Session, Depends(get_session)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
        auth: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> dict[str, Any] | JSONResponse:
        knowledge_base, kb_error = _knowledge_base_by_id_for_workspace(
            session=session,
            kb_id=kb_id,
            workspace_id=workspace_id,
        )
        if kb_error is not None:
            return kb_error
        assert knowledge_base is not None
        access_error = knowledge_base_access_error(
            settings=active_settings,
            session=session,
            auth=auth,
            knowledge_base_id=knowledge_base.id,
            minimum="viewer",
        )
        if access_error is not None:
            return access_error
        try:
            return get_knowledge_graph(session, kb_id).model_dump(mode="json")
        except (ValueError, KnowledgeGraphNotFoundError):
            return JSONResponse(status_code=404, content={"error": "knowledge_base_not_found"})

    @app.post("/knowledge-bases/{kb_id}/knowledge-graph/rebuild", response_model=None)
    def rebuild_knowledge_graph_endpoint(
        kb_id: str,
        request: KnowledgeGraphBuildRequest,
        session: Annotated[Session, Depends(get_session)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
        auth: Annotated[AuthContext, Depends(require_write_auth)],
    ) -> dict[str, Any] | JSONResponse:
        knowledge_base, kb_error = _knowledge_base_by_id_for_workspace(
            session=session,
            kb_id=kb_id,
            workspace_id=workspace_id,
        )
        if kb_error is not None:
            return kb_error
        assert knowledge_base is not None
        access_error = knowledge_base_access_error(
            settings=active_settings,
            session=session,
            auth=auth,
            knowledge_base_id=knowledge_base.id,
            minimum="editor",
        )
        if access_error is not None:
            return access_error
        try:
            result = rebuild_knowledge_graph(
                session,
                kb_id,
                profile_id=request.profile_id,
                extractor_version=request.extractor_version,
                reset=request.reset,
            )
        except (ValueError, KnowledgeGraphNotFoundError):
            return JSONResponse(status_code=404, content={"error": "knowledge_base_not_found"})
        return result.model_dump(mode="json")

    @app.post(
        "/knowledge-bases/{kb_id}/knowledge-graph/relations/{relation_id}/feedback",
        response_model=None,
    )
    def submit_knowledge_graph_relation_feedback(
        kb_id: str,
        relation_id: str,
        request: KnowledgeGraphRelationFeedbackRequest,
        session: Annotated[Session, Depends(get_session)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
        auth: Annotated[AuthContext, Depends(require_write_auth)],
    ) -> dict[str, Any] | JSONResponse:
        knowledge_base, kb_error = _knowledge_base_by_id_for_workspace(
            session=session,
            kb_id=kb_id,
            workspace_id=workspace_id,
        )
        if kb_error is not None:
            return kb_error
        assert knowledge_base is not None
        access_error = knowledge_base_access_error(
            settings=active_settings,
            session=session,
            auth=auth,
            knowledge_base_id=knowledge_base.id,
            minimum="editor",
        )
        if access_error is not None:
            return access_error
        try:
            relation_uuid = uuid.UUID(str(relation_id))
        except ValueError:
            return JSONResponse(status_code=404, content={"error": "relation_not_found"})
        relation = session.get(KnowledgeGraphRelation, relation_uuid)
        if relation is None or relation.knowledge_base_id != knowledge_base.id:
            return JSONResponse(status_code=404, content={"error": "relation_not_found"})

        metadata = dict(relation.metadata_json or {})
        feedback_items = [item for item in metadata.get("feedback", []) if isinstance(item, dict)]
        created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        actor = str(auth.user_id) if auth.user_id is not None else "anonymous"
        entry: dict[str, Any] = {
            "verdict": request.verdict,
            "created_at": created_at,
            "actor": actor,
        }
        if request.note and request.note.strip():
            entry["note"] = request.note.strip()
        feedback_items.append(entry)
        metadata["feedback"] = feedback_items[-50:]
        metadata["feedback_summary"] = _summarize_relation_feedback(feedback_items)
        relation.metadata_json = metadata
        create_audit_event(
            session,
            event_type="kg_relation_feedback",
            actor=actor,
            workspace_id=workspace_id,
            knowledge_base_id=knowledge_base.id,
            payload_json={
                "relation_id": str(relation.id),
                "verdict": request.verdict,
                "note": request.note,
            },
        )
        session.commit()
        return {
            "status": "recorded",
            "relation_id": str(relation.id),
            "feedback": entry,
            "feedback_summary": metadata["feedback_summary"],
        }

    @app.get("/knowledge-bases/{kb_id}/retrieval-preferences", response_model=None)
    def get_retrieval_preferences(
        kb_id: str,
        session: Annotated[Session, Depends(get_session)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
        auth: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> dict[str, Any] | JSONResponse:
        knowledge_base, kb_error = _knowledge_base_by_id_for_workspace(
            session=session,
            kb_id=kb_id,
            workspace_id=workspace_id,
        )
        if kb_error is not None:
            return kb_error
        assert knowledge_base is not None
        access_error = knowledge_base_access_error(
            settings=active_settings,
            session=session,
            auth=auth,
            knowledge_base_id=knowledge_base.id,
            minimum="viewer",
        )
        if access_error is not None:
            return access_error
        return {
            "knowledge_base_id": str(knowledge_base.id),
            "knowledge_base": knowledge_base.name,
            "preferences": _kb_retrieval_preferences(knowledge_base),
        }

    @app.put("/knowledge-bases/{kb_id}/retrieval-preferences", response_model=None)
    def put_retrieval_preferences(
        kb_id: str,
        request: RetrievalPreferenceRequest,
        session: Annotated[Session, Depends(get_session)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
        auth: Annotated[AuthContext, Depends(require_write_auth)],
    ) -> dict[str, Any] | JSONResponse:
        knowledge_base, kb_error = _knowledge_base_by_id_for_workspace(
            session=session,
            kb_id=kb_id,
            workspace_id=workspace_id,
        )
        if kb_error is not None:
            return kb_error
        assert knowledge_base is not None
        access_error = knowledge_base_access_error(
            settings=active_settings,
            session=session,
            auth=auth,
            knowledge_base_id=knowledge_base.id,
            minimum="editor",
        )
        if access_error is not None:
            return access_error
        preferences = request.model_dump(mode="json")
        metadata = dict(knowledge_base.metadata_json or {})
        metadata["retrieval_preferences"] = preferences
        knowledge_base.metadata_json = metadata
        actor = str(auth.user_id) if auth.user_id is not None else "anonymous"
        create_audit_event(
            session,
            event_type="retrieval_preference_update",
            actor=actor,
            workspace_id=workspace_id,
            knowledge_base_id=knowledge_base.id,
            payload_json={
                "mode": preferences["mode"],
                "graph_weight": preferences["graph_weight"],
                "graph_depth": preferences["graph_depth"],
            },
        )
        session.commit()
        return {
            "status": "saved",
            "knowledge_base_id": str(knowledge_base.id),
            "knowledge_base": knowledge_base.name,
            "preferences": preferences,
        }

    @app.get("/knowledge-bases/{kb_id}/role-model-config", response_model=None)
    def get_role_model_config(
        kb_id: str,
        session: Annotated[Session, Depends(get_session)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
        auth: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> dict[str, Any] | JSONResponse:
        knowledge_base, kb_error = _knowledge_base_by_id_for_workspace(
            session=session,
            kb_id=kb_id,
            workspace_id=workspace_id,
        )
        if kb_error is not None:
            return kb_error
        assert knowledge_base is not None
        access_error = knowledge_base_access_error(
            settings=active_settings,
            session=session,
            auth=auth,
            knowledge_base_id=knowledge_base.id,
            minimum="viewer",
        )
        if access_error is not None:
            return access_error
        config = _kb_role_model_config(knowledge_base) or {}
        return {
            "knowledge_base_id": str(knowledge_base.id),
            "knowledge_base": knowledge_base.name,
            "config": _public_role_model_config(config),
            "roles": sorted(str(role) for role in config),
        }

    @app.put("/knowledge-bases/{kb_id}/role-model-config", response_model=None)
    def put_role_model_config(
        kb_id: str,
        request: RoleModelConfigRequest,
        session: Annotated[Session, Depends(get_session)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
        auth: Annotated[AuthContext, Depends(require_write_auth)],
    ) -> dict[str, Any] | JSONResponse:
        knowledge_base, kb_error = _knowledge_base_by_id_for_workspace(
            session=session,
            kb_id=kb_id,
            workspace_id=workspace_id,
        )
        if kb_error is not None:
            return kb_error
        assert knowledge_base is not None
        access_error = knowledge_base_access_error(
            settings=active_settings,
            session=session,
            auth=auth,
            knowledge_base_id=knowledge_base.id,
            minimum="editor",
        )
        if access_error is not None:
            return access_error
        validation_error = _validate_role_model_config(request.config)
        if validation_error is not None:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "invalid_role_model_config",
                        "message": validation_error,
                    }
                },
            )
        metadata = dict(knowledge_base.metadata_json or {})
        metadata["role_model_config"] = request.config
        knowledge_base.metadata_json = metadata
        actor = str(auth.user_id) if auth.user_id is not None else "anonymous"
        create_audit_event(
            session,
            event_type="role_model_config_update",
            actor=actor,
            workspace_id=workspace_id,
            knowledge_base_id=knowledge_base.id,
            payload_json={"roles": sorted(str(role) for role in request.config)},
        )
        session.commit()
        return {
            "status": "saved",
            "knowledge_base_id": str(knowledge_base.id),
            "knowledge_base": knowledge_base.name,
            "config": _public_role_model_config(request.config),
            "roles": sorted(str(role) for role in request.config),
        }

    @app.get("/knowledge-bases/{kb_id}/understanding-runs", response_model=None)
    def understanding_runs(
        kb_id: str,
        session: Annotated[Session, Depends(get_session)],
        provider: str | None = None,
        model: str | None = None,
        profile_id: str | None = None,
        status: str | None = None,
        started_after: str | None = None,
        started_before: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        filters = UnderstandingRunFilter(
            provider=provider,
            model=model,
            profile_id=profile_id,
            status=status,
            started_after=started_after,
            started_before=started_before,
            limit=limit,
        )
        runs = get_understanding_runs(session, kb_id, filters=filters)
        return {
            "runs": [r.model_dump() for r in runs],
        }

    @app.post("/knowledge-bases/{kb_name}/website-import", response_model=None)
    def knowledge_base_website_import(
        kb_name: str,
        request: WebsiteImportRequest,
        session: Annotated[Session, Depends(get_session)],
        _auth: Annotated[AuthContext, Depends(require_write_auth)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    ) -> JSONResponse:
        kb = get_knowledge_base_by_name(session, kb_name, workspace_id=workspace_id)
        if kb is None:
            return JSONResponse(
                status_code=404,
                content={"error": f"knowledge base '{kb_name}' not found"},
            )
        access_error = knowledge_base_access_error(
            settings=active_settings,
            session=session,
            auth=_auth,
            knowledge_base_id=kb.id,
            minimum="editor",
        )
        if access_error is not None:
            return access_error

        try:
            result = import_website_pages(
                session,
                knowledge_base=kb,
                urls=request.urls,
                sitemap_url=request.sitemap_url,
                bearer_token=request.bearer_token,
                cookies=request.cookies,
                basic_auth_username=request.basic_auth_username,
                basic_auth_password=request.basic_auth_password,
            )
        except WebsiteImportError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})

        return JSONResponse(status_code=202, content=result)

    @app.post("/knowledge-bases/{kb_name}/upload", response_model=None)
    async def knowledge_base_upload(
        kb_name: str,
        session: Annotated[Session, Depends(get_session)],
        files: Annotated[list[UploadFile], File(...)],
        _auth: Annotated[AuthContext, Depends(require_write_auth)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    ) -> JSONResponse:
        rate_limiter.check_ingest(str(workspace_id))
        kb = get_knowledge_base_by_name(session, kb_name, workspace_id=workspace_id)
        if kb is None:
            return JSONResponse(
                status_code=404,
                content={"error": f"knowledge base '{kb_name}' not found"},
            )
        access_error = knowledge_base_access_error(
            settings=active_settings,
            session=session,
            auth=_auth,
            knowledge_base_id=kb.id,
            minimum="editor",
        )
        if access_error is not None:
            return access_error

        if not files:
            return JSONResponse(
                status_code=400,
                content={"error": "at least one file is required"},
            )

        file_payloads: list[tuple[str, bytes]] = []
        for file in files:
            file_payloads.append((file.filename or "unknown", await file.read()))

        try:
            accepted = validate_and_stage_uploads(files=file_payloads)
        except ValueError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})

        if not accepted.staged_files:
            cleanup_staging_dir(accepted.staging_dir)
            status_code = (
                413 if any(r["reason"] == "file_too_large" for r in accepted.rejected) else 415
            )
            return JSONResponse(
                status_code=status_code,
                content={
                    "accepted_files": 0,
                    "rejected_files": len(accepted.rejected),
                    "rejections": accepted.rejected,
                    "warnings": accepted.warnings,
                },
            )

        pipeline_run_id, _source_id = create_upload_pipeline_run(
            session,
            kb_name=kb_name,
            staged_files=accepted.staged_files,
            workspace_id=workspace_id,
        )
        task_id = enqueue_task(
            session_factory=get_session_factory(),
            task_executor=active_task_executor,
            task_type="knowledge_base_upload",
            payload_json={
                "knowledge_base": kb_name,
                "workspace_id": str(workspace_id),
                "pipeline_run_id": pipeline_run_id,
                "staged_files": accepted.staged_files,
            },
            runner=lambda: run_upload_pipeline(
                session_factory=get_session_factory(),
                kb_name=kb_name,
                pipeline_run_id=pipeline_run_id,
                staged_files=accepted.staged_files,
                workspace_id=workspace_id,
            ),
        )

        return JSONResponse(
            status_code=202,
            content={
                "task_id": task_id,
                "pipeline_run_id": pipeline_run_id,
                "accepted_files": len(accepted.staged_files),
                "rejected_files": len(accepted.rejected),
                "rejections": accepted.rejected,
                "warnings": accepted.warnings,
            },
        )

    @app.post("/retrieval/search", response_model=None)
    def retrieval_search(
        request: RetrievalSearchRequest,
        session: Annotated[Session, Depends(get_session)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
        auth: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> dict[str, Any] | JSONResponse:
        rate_limiter.check_search(str(workspace_id))
        if active_settings.ragrig_auth_enabled:
            if not request.query.strip():
                return JSONResponse(
                    status_code=400,
                    content=_serialize_error(
                        EmptyQueryError("Query must not be empty", details={"query": request.query})
                    ),
                )
            kb = get_knowledge_base_by_name(
                session,
                request.knowledge_base,
                workspace_id=workspace_id,
            )
            if kb is None:
                return JSONResponse(
                    status_code=404,
                    content=_serialize_error(
                        KnowledgeBaseNotFoundError(
                            f"Knowledge base '{request.knowledge_base}' was not found",
                            details={"knowledge_base": request.knowledge_base},
                        )
                    ),
                )
            access_error = knowledge_base_access_error(
                settings=active_settings,
                session=session,
                auth=auth,
                knowledge_base_id=kb.id,
                minimum="viewer",
                allow_anonymous_reader=True,
            )
            if access_error is not None:
                return access_error
        principal_ids, enforce_acl = _resolve_acl_context(
            auth=auth,
            requested_principal_ids=request.principal_ids,
            requested_enforce_acl=request.enforce_acl,
        )
        try:
            vector_backend = resolve_vector_backend()
            report = search_knowledge_base(
                session=session,
                knowledge_base_name=request.knowledge_base,
                query=request.query,
                top_k=request.top_k,
                provider=request.provider,
                model=request.model,
                dimensions=request.dimensions,
                vector_backend=vector_backend,
                principal_ids=principal_ids,
                enforce_acl=enforce_acl,
                workspace_id=workspace_id,
                mode=request.mode,
                lexical_weight=request.lexical_weight,
                vector_weight=request.vector_weight,
                candidate_k=request.candidate_k,
                reranker_provider=request.reranker_provider,
                reranker_model=request.reranker_model,
                graph_weight=request.graph_weight,
                graph_depth=request.graph_depth,
            )
        except KnowledgeBaseNotFoundError as exc:
            return JSONResponse(status_code=404, content=_serialize_error(exc))
        except (EmptyQueryError, EmbeddingProfileMismatchError, InvalidTopKError) as exc:
            return JSONResponse(status_code=400, content=_serialize_error(exc))
        except RerankerUnavailableError as exc:
            return JSONResponse(status_code=503, content=_serialize_error(exc))

        response: dict[str, Any] = {
            "knowledge_base": report.knowledge_base,
            "query": report.query,
            "top_k": report.top_k,
            "provider": report.provider,
            "model": report.model,
            "dimensions": report.dimensions,
            "distance_metric": report.distance_metric,
            "backend": report.backend,
            "backend_metadata": report.backend_metadata,
            "cost_latency": report.cost_latency,
            "total_results": report.total_results,
            "acl_explain": report.acl_explain,
            "graph_context": getattr(report, "graph_context", {}),
            "results": [
                {
                    "document_id": str(result.document_id),
                    "document_version_id": str(result.document_version_id),
                    "chunk_id": str(result.chunk_id),
                    "chunk_index": result.chunk_index,
                    "document_uri": result.document_uri,
                    "source_uri": result.source_uri,
                    "text": result.text,
                    "text_preview": result.text_preview,
                    "distance": result.distance,
                    "score": result.score,
                    "chunk_metadata": _safe_chunk_metadata(result.chunk_metadata),
                    "rank_stage_trace": result.rank_stage_trace,
                    "acl_explain": {
                        "chunk_id": result.acl_explain.chunk_id,
                        "visibility": result.acl_explain.visibility,
                        "permitted": result.acl_explain.permitted,
                        "reason": result.acl_explain.reason,
                    }
                    if result.acl_explain is not None
                    else None,
                }
                for result in report.results
            ],
        }
        if report.results:
            reasons: dict[str, int] = {}
            for r in report.results:
                if r.acl_explain is not None:
                    reasons[r.acl_explain.reason] = reasons.get(r.acl_explain.reason, 0) + 1
            response["acl_explain_summary"] = {
                "total_chunks": len(report.results),
                "reasons": reasons,
            }
        if report.degraded:
            response["degraded"] = True
            response["degraded_reason"] = report.degraded_reason
        _record_usage_for_request(
            session,
            workspace_id,
            None,
            report.cost_latency,
            request_metadata={
                "endpoint": "retrieval.search",
                "role": request.role,
                "mode": request.mode,
            },
        )
        return response

    @app.post("/permissions/preview", response_model=None)
    def permission_preview(
        request: PermissionPreviewRequest,
        session: Annotated[Session, Depends(get_session)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    ) -> dict[str, Any]:
        return build_permission_preview(
            session,
            principal_ids=request.principal_ids,
            workspace_id=workspace_id,
        )

    @app.post("/evaluations/runs", response_model=None)
    def evaluation_run(
        request: EvaluationRunRequest,
        session: Annotated[Session, Depends(get_session)],
        _auth: Annotated[AuthContext, Depends(require_admin_auth)],
    ) -> dict[str, Any] | JSONResponse:
        """Run a golden question evaluation against a knowledge base."""
        golden_path, path_error = _resolve_evaluation_path(
            request.golden_path,
            default_path=Path("evaluation_runs"),
            allowed_roots=(Path("evaluation_runs"), Path("evaluation_baselines"), Path("tests")),
        )
        if path_error is not None:
            return path_error
        assert golden_path is not None
        if not golden_path.exists():
            return JSONResponse(
                status_code=404,
                content={"error": f"Golden question file not found: {golden_path}"},
            )

        baseline_path: Path | None = None
        if request.baseline_path:
            baseline_path, path_error = _resolve_evaluation_path(
                request.baseline_path,
                default_path=Path("evaluation_baselines"),
                allowed_roots=(Path("evaluation_baselines"), Path("evaluation_runs")),
            )
            if path_error is not None:
                return path_error
        try:
            run = run_evaluation(
                session=session,
                golden_path=golden_path,
                knowledge_base=request.knowledge_base,
                top_k=request.top_k,
                provider=request.provider,
                model=request.model,
                dimensions=request.dimensions,
                baseline_path=baseline_path,
                mode=request.mode,
                lexical_weight=request.lexical_weight,
                vector_weight=request.vector_weight,
                candidate_k=request.candidate_k,
                reranker_provider=request.reranker_provider,
                reranker_model=request.reranker_model,
                graph_weight=request.graph_weight,
                graph_depth=request.graph_depth,
                store_dir=Path("evaluation_runs"),
            )
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content={"error": f"Evaluation failed: {exc}"},
            )
        return build_evaluation_run_report(run, include_items=True)

    @app.get("/evaluations/runs/{run_id}", response_model=None)
    def evaluation_run_detail(
        run_id: str,
        _auth: Annotated[AuthContext, Depends(require_admin_auth)],
        store_dir: str | None = None,
    ) -> dict[str, Any] | JSONResponse:
        """Get details for a specific evaluation run."""
        store_path, path_error = _resolve_evaluation_path(
            store_dir,
            default_path=Path("evaluation_runs"),
            allowed_roots=(Path("evaluation_runs"),),
        )
        if path_error is not None:
            return path_error
        assert store_path is not None
        run = load_run_from_store(run_id, store_dir=store_path)
        if run is None:
            return JSONResponse(
                status_code=404,
                content={"error": "evaluation_run_not_found"},
            )
        return build_evaluation_run_report(run, include_items=True)

    @app.get("/evaluations", response_model=None)
    def evaluation_runs_list(
        _auth: Annotated[AuthContext, Depends(require_admin_auth)],
        store_dir: str | None = None,
    ) -> dict[str, Any] | JSONResponse:
        """List all evaluation runs."""
        store_path, path_error = _resolve_evaluation_path(
            store_dir,
            default_path=Path("evaluation_runs"),
            allowed_roots=(Path("evaluation_runs"),),
        )
        if path_error is not None:
            return path_error
        assert store_path is not None
        runs = list_runs_from_store(store_dir=store_path)
        return build_evaluation_list_report(runs)

    @app.get("/evaluations/baselines", response_model=None)
    def evaluation_baselines_list(
        _auth: Annotated[AuthContext, Depends(require_admin_auth)],
        baseline_dir: str | None = None,
    ) -> dict[str, Any] | JSONResponse:
        """List all baselines and current baseline id."""
        from ragrig.evaluation.baseline import list_baselines

        path, path_error = _resolve_evaluation_path(
            baseline_dir,
            default_path=Path("evaluation_baselines"),
            allowed_roots=(Path("evaluation_baselines"),),
        )
        if path_error is not None:
            return path_error
        assert path is not None
        try:
            return list_baselines(baseline_dir=path)
        except Exception as exc:
            return JSONResponse(
                status_code=500,
                content={"error": f"Failed to list baselines: {exc}"},
            )

    @app.post("/retrieval/answer", response_model=None)
    def retrieval_answer(
        request: AnswerRequest,
        session: Annotated[Session, Depends(get_session)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
        auth: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> dict[str, Any] | JSONResponse:
        rate_limiter.check_search(str(workspace_id))
        answer_kb: KnowledgeBase | None = None
        if active_settings.ragrig_auth_enabled:
            if not request.query.strip():
                return JSONResponse(
                    status_code=400,
                    content=_serialize_error(
                        EmptyQueryError("Query must not be empty", details={"query": request.query})
                    ),
                )
            kb = get_knowledge_base_by_name(
                session,
                request.knowledge_base,
                workspace_id=workspace_id,
            )
            if kb is None:
                return JSONResponse(
                    status_code=404,
                    content=_serialize_error(
                        KnowledgeBaseNotFoundError(
                            f"Knowledge base '{request.knowledge_base}' was not found",
                            details={"knowledge_base": request.knowledge_base},
                        )
                    ),
                )
            access_error = knowledge_base_access_error(
                settings=active_settings,
                session=session,
                auth=auth,
                knowledge_base_id=kb.id,
                minimum="viewer",
                allow_anonymous_reader=True,
            )
            if access_error is not None:
                return access_error
            answer_kb = kb
        principal_ids, enforce_acl = _resolve_acl_context(
            auth=auth,
            requested_principal_ids=request.principal_ids,
            requested_enforce_acl=request.enforce_acl,
        )
        if answer_kb is None:
            answer_kb = get_knowledge_base_by_name(
                session,
                request.knowledge_base,
                workspace_id=workspace_id,
            )
        persisted_role_config = _kb_role_model_config(answer_kb)
        effective_role_config = (
            request.role_model_config
            if request.role_model_config is not None
            else persisted_role_config
        )
        role_selection, role_error = _role_model_selection(request.role, effective_role_config)
        if role_error is not None:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "invalid_role_model_config",
                        "message": role_error,
                        "details": {"role": request.role},
                    }
                },
            )
        if role_selection and "source" not in role_selection:
            role_selection["source"] = (
                "request" if request.role_model_config is not None else "knowledge_base"
            )
        selected_provider = role_selection.get("provider", request.provider)
        selected_model = role_selection.get("model", request.model)
        selected_config = role_selection.get("config", request.config)
        selected_answer_provider = role_selection.get(
            "answer_provider",
            request.answer_provider,
        )
        selected_answer_model = role_selection.get("answer_model", request.answer_model)
        selected_answer_config = role_selection.get("answer_config", request.answer_config)
        try:
            provider_config = None
            if selected_config is not None:
                provider_config, missing_env = resolve_env_config(selected_config)
                if missing_env:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": {
                                "code": "missing_model_credentials",
                                "message": (
                                    "Missing environment variable(s): " + ", ".join(missing_env)
                                ),
                                "details": {"missing_credentials": missing_env},
                            }
                        },
                    )
            answer_provider_config = None
            if selected_answer_config is not None:
                answer_provider_config, missing_env = resolve_env_config(selected_answer_config)
                if missing_env:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": {
                                "code": "missing_model_credentials",
                                "message": (
                                    "Missing environment variable(s): " + ", ".join(missing_env)
                                ),
                                "details": {"missing_credentials": missing_env},
                            }
                        },
                    )
            vector_backend = resolve_vector_backend()
            report = generate_answer(
                session=session,
                knowledge_base_name=request.knowledge_base,
                query=request.query,
                top_k=request.top_k,
                provider=selected_provider,
                model=selected_model,
                provider_config=provider_config,
                answer_provider=selected_answer_provider,
                answer_model=selected_answer_model,
                answer_provider_config=answer_provider_config,
                dimensions=request.dimensions,
                vector_backend=vector_backend,
                principal_ids=principal_ids,
                enforce_acl=enforce_acl,
                mode=request.mode,
                lexical_weight=request.lexical_weight,
                vector_weight=request.vector_weight,
                candidate_k=request.candidate_k,
                reranker_provider=request.reranker_provider,
                reranker_model=request.reranker_model,
                graph_weight=request.graph_weight,
                graph_depth=request.graph_depth,
                workspace_id=workspace_id,
            )
        except ModelConfigError as exc:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": exc.code,
                        "message": str(exc),
                        "details": {"field": exc.field},
                    }
                },
            )
        except NoEvidenceError as exc:
            return JSONResponse(
                status_code=200,
                content={
                    "answer": "",
                    "citations": [],
                    "evidence_chunks": [],
                    "model": exc.details.get("model", ""),
                    "provider": exc.details.get("provider", ""),
                    "retrieval_trace": exc.details,
                    "grounding_status": "refused",
                    "refusal_reason": str(exc),
                },
            )
        except KnowledgeBaseNotFoundError as exc:
            return JSONResponse(status_code=404, content=_serialize_error(exc))
        except (EmptyQueryError, EmbeddingProfileMismatchError, InvalidTopKError) as exc:
            return JSONResponse(status_code=400, content=_serialize_error(exc))
        except RerankerUnavailableError as exc:
            return JSONResponse(status_code=503, content=_serialize_error(exc))
        except AnswerProviderUnavailableError as exc:
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": exc.code,
                        "message": str(exc),
                        "details": exc.details,
                    }
                },
            )

        public_role_selection = _public_role_model_selection(role_selection)
        _record_usage_for_request(
            session,
            workspace_id,
            None,
            report.cost_latency,
            request_metadata={
                "endpoint": "retrieval.answer",
                "role": request.role,
                "mode": request.mode,
                "role_model_selection": public_role_selection,
            },
        )
        payload = {
            "answer": report.answer,
            "citations": [
                {
                    "citation_id": c.citation_id,
                    "document_uri": c.document_uri,
                    "chunk_id": c.chunk_id,
                    "chunk_index": c.chunk_index,
                    "text_preview": c.text_preview,
                    "score": c.score,
                    "char_start": c.char_start,
                    "char_end": c.char_end,
                    "page_number": c.page_number,
                    "metadata_summary": c.metadata_summary,
                }
                for c in report.citations
            ],
            "evidence_chunks": [
                {
                    "citation_id": ec.citation_id,
                    "document_uri": ec.document_uri,
                    "chunk_id": ec.chunk_id,
                    "chunk_index": ec.chunk_index,
                    "text": ec.text,
                    "score": ec.score,
                    "distance": ec.distance,
                    "char_start": ec.char_start,
                    "char_end": ec.char_end,
                    "page_number": ec.page_number,
                }
                for ec in report.evidence_chunks
            ],
            "model": report.model,
            "provider": report.provider,
            "role": request.role,
            "role_model_selection": public_role_selection,
            "retrieval_trace": report.retrieval_trace,
            "grounding_status": report.grounding_status,
            "refusal_reason": report.refusal_reason,
        }
        if request.stream:
            return StreamingResponse(
                _answer_sse_stream(payload),
                media_type="text/event-stream",
            )
        return payload

    # ── Sink export endpoints ─────────────────────────────────────────────────
    @app.post("/knowledge-bases/{kb_name}/sink-export/agent-access", response_model=None)
    def knowledge_base_sink_agent_access(
        kb_name: str,
        request: AgentAccessExportRequest,
        session: Annotated[Session, Depends(get_session)],
        _auth: Annotated[AuthContext, Depends(require_write_auth)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    ) -> JSONResponse:
        access_error = _knowledge_base_role_error_by_name(
            session=session,
            auth=_auth,
            kb_name=kb_name,
            workspace_id=workspace_id,
            minimum="editor",
        )
        if access_error is not None:
            return access_error
        try:
            report = export_to_agent_endpoint(
                session,
                knowledge_base_name=kb_name,
                endpoint_url=request.endpoint_url,
                api_key=request.api_key,
                workspace_id=workspace_id,
                hmac_secret=request.hmac_secret,
                batch_size=request.batch_size,
                timeout_seconds=request.timeout_seconds,
                verify_tls=request.verify_tls,
                dry_run=request.dry_run,
            )
        except ValueError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})
        return JSONResponse(
            status_code=200,
            content={
                "total_chunks": report.chunk_count,
                "batches_sent": report.delivered_batches,
                "failed_batches": report.failed_batches,
                "dry_run": report.dry_run,
            },
        )

    @app.post("/knowledge-bases/{kb_name}/sink-export/webhook", response_model=None)
    def knowledge_base_sink_webhook(
        kb_name: str,
        request: WebhookExportRequest,
        session: Annotated[Session, Depends(get_session)],
        _auth: Annotated[AuthContext, Depends(require_write_auth)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    ) -> JSONResponse:
        access_error = _knowledge_base_role_error_by_name(
            session=session,
            auth=_auth,
            kb_name=kb_name,
            workspace_id=workspace_id,
            minimum="editor",
        )
        if access_error is not None:
            return access_error
        try:
            report = export_to_webhook(
                session,
                knowledge_base_name=kb_name,
                endpoint_url=request.endpoint_url,
                workspace_id=workspace_id,
                hmac_secret=request.hmac_secret,
                format=request.format,
                extra_headers=request.extra_headers,
                batch_size=request.batch_size,
                timeout_seconds=request.timeout_seconds,
                verify_tls=request.verify_tls,
                dry_run=request.dry_run,
            )
        except ValueError as exc:
            error_text = str(exc)
            status = 400 if "format must be" in error_text else 404
            return JSONResponse(status_code=status, content={"error": error_text})
        return JSONResponse(
            status_code=200,
            content={
                "total_chunks": report.chunk_count,
                "batches_sent": report.delivered_batches,
                "failed_batches": report.failed_batches,
                "dry_run": report.dry_run,
            },
        )

    @app.post("/knowledge-bases/{kb_name}/sink-export/object-storage", response_model=None)
    def knowledge_base_sink_object_storage(
        kb_name: str,
        request: ObjectStorageExportRequest,
        session: Annotated[Session, Depends(get_session)],
        _auth: Annotated[AuthContext, Depends(require_write_auth)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    ) -> JSONResponse:
        access_error = _knowledge_base_role_error_by_name(
            session=session,
            auth=_auth,
            kb_name=kb_name,
            workspace_id=workspace_id,
            minimum="editor",
        )
        if access_error is not None:
            return access_error
        config: dict[str, Any] = {
            "bucket": request.bucket,
            "path_template": request.path_template,
            "overwrite": request.overwrite,
            "dry_run": request.dry_run,
            "include_retrieval_artifact": request.include_retrieval_artifact,
            "include_markdown_summary": request.include_markdown_summary,
            "parquet_export": request.parquet_export,
        }
        if request.endpoint_url:
            config["endpoint_url"] = request.endpoint_url
        if request.access_key:
            config["access_key"] = request.access_key
        if request.secret_key:
            config["secret_key"] = request.secret_key
        if request.region:
            config["region"] = request.region
        config["use_path_style"] = request.use_path_style
        config["verify_tls"] = request.verify_tls
        try:
            report = export_to_object_storage(
                session,
                knowledge_base_name=kb_name,
                workspace_id=workspace_id,
                config=config,
            )
        except ValueError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})
        return JSONResponse(
            status_code=200,
            content={
                "pipeline_run_id": str(report.pipeline_run_id),
                "planned_count": report.planned_count,
                "uploaded_count": report.uploaded_count,
                "skipped_count": report.skipped_count,
                "failed_count": report.failed_count,
                "dry_run": report.dry_run,
                "artifact_keys": report.artifact_keys,
            },
        )

    @app.post("/knowledge-bases/{kb_name}/sink-export/cloudflare-r2", response_model=None)
    def knowledge_base_sink_cloudflare_r2(
        kb_name: str,
        request: CloudflareR2ExportRequest,
        session: Annotated[Session, Depends(get_session)],
        _auth: Annotated[AuthContext, Depends(require_write_auth)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    ) -> JSONResponse:
        access_error = _knowledge_base_role_error_by_name(
            session=session,
            auth=_auth,
            kb_name=kb_name,
            workspace_id=workspace_id,
            minimum="editor",
        )
        if access_error is not None:
            return access_error
        r2_env = {
            "CF_R2_ACCESS_KEY_ID": request.access_key_id,
            "CF_R2_SECRET_ACCESS_KEY": request.secret_access_key,
        }
        config: dict[str, Any] = {
            "account_id": request.account_id,
            "access_key_id": "env:CF_R2_ACCESS_KEY_ID",
            "secret_access_key": "env:CF_R2_SECRET_ACCESS_KEY",
            "bucket": request.bucket,
            "prefix": request.prefix,
            "path_template": request.path_template,
            "overwrite": request.overwrite,
            "dry_run": request.dry_run,
            "include_retrieval_artifact": request.include_retrieval_artifact,
            "include_markdown_summary": request.include_markdown_summary,
            "parquet_export": request.parquet_export,
        }
        if request.jurisdiction:
            config["jurisdiction"] = request.jurisdiction
        try:
            report = export_to_cloudflare_r2(
                session,
                knowledge_base_name=kb_name,
                workspace_id=workspace_id,
                config=config,
                env=r2_env,
            )
        except ValueError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})
        return JSONResponse(
            status_code=200,
            content={
                "pipeline_run_id": str(report.pipeline_run_id),
                "planned_count": report.planned_count,
                "uploaded_count": report.uploaded_count,
                "skipped_count": report.skipped_count,
                "failed_count": report.failed_count,
                "dry_run": report.dry_run,
                "artifact_keys": report.artifact_keys,
            },
        )

    @app.post("/knowledge-bases/{kb_name}/sink-export/backblaze-b2", response_model=None)
    def knowledge_base_sink_backblaze_b2(
        kb_name: str,
        request: BackblazeB2ExportRequest,
        session: Annotated[Session, Depends(get_session)],
        _auth: Annotated[AuthContext, Depends(require_write_auth)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    ) -> JSONResponse:
        access_error = _knowledge_base_role_error_by_name(
            session=session,
            auth=_auth,
            kb_name=kb_name,
            workspace_id=workspace_id,
            minimum="editor",
        )
        if access_error is not None:
            return access_error
        b2_env = {
            "B2_APPLICATION_KEY_ID": request.key_id,
            "B2_APPLICATION_KEY": request.application_key,
        }
        config: dict[str, Any] = {
            "region": request.region,
            "key_id": "env:B2_APPLICATION_KEY_ID",
            "application_key": "env:B2_APPLICATION_KEY",
            "bucket": request.bucket,
            "prefix": request.prefix,
            "path_template": request.path_template,
            "overwrite": request.overwrite,
            "dry_run": request.dry_run,
            "include_retrieval_artifact": request.include_retrieval_artifact,
            "include_markdown_summary": request.include_markdown_summary,
            "parquet_export": request.parquet_export,
        }
        try:
            report = export_to_backblaze_b2(
                session,
                knowledge_base_name=kb_name,
                workspace_id=workspace_id,
                config=config,
                env=b2_env,
            )
        except ValueError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})
        return JSONResponse(
            status_code=200,
            content={
                "pipeline_run_id": str(report.pipeline_run_id),
                "planned_count": report.planned_count,
                "uploaded_count": report.uploaded_count,
                "skipped_count": report.skipped_count,
                "failed_count": report.failed_count,
                "dry_run": report.dry_run,
                "artifact_keys": report.artifact_keys,
            },
        )

    @app.post("/knowledge-bases/{kb_name}/sink-export/azure-blob", response_model=None)
    def knowledge_base_sink_azure_blob(
        kb_name: str,
        request: AzureBlobExportRequest,
        session: Annotated[Session, Depends(get_session)],
        _auth: Annotated[AuthContext, Depends(require_write_auth)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    ) -> JSONResponse:
        access_error = _knowledge_base_role_error_by_name(
            session=session,
            auth=_auth,
            kb_name=kb_name,
            workspace_id=workspace_id,
            minimum="editor",
        )
        if access_error is not None:
            return access_error
        azure_env = {"AZURE_STORAGE_ACCOUNT_KEY": request.account_key}
        config: dict[str, Any] = {
            "account_name": request.account_name,
            "account_key": "env:AZURE_STORAGE_ACCOUNT_KEY",
            "container": request.container,
            "prefix": request.prefix,
            "path_template": request.path_template,
            "overwrite": request.overwrite,
            "dry_run": request.dry_run,
            "include_retrieval_artifact": request.include_retrieval_artifact,
            "include_markdown_summary": request.include_markdown_summary,
            "parquet_export": request.parquet_export,
        }
        try:
            report = export_to_azure_blob(
                session,
                knowledge_base_name=kb_name,
                workspace_id=workspace_id,
                config=config,
                env=azure_env,
            )
        except ValueError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})
        return JSONResponse(
            status_code=200,
            content={
                "pipeline_run_id": str(report.pipeline_run_id),
                "planned_count": report.planned_count,
                "uploaded_count": report.uploaded_count,
                "skipped_count": report.skipped_count,
                "failed_count": report.failed_count,
                "dry_run": report.dry_run,
                "artifact_keys": report.artifact_keys,
            },
        )

    @app.post("/knowledge-bases/{kb_name}/sink-export/gcs", response_model=None)
    def knowledge_base_sink_gcs(
        kb_name: str,
        request: GcsExportRequest,
        session: Annotated[Session, Depends(get_session)],
        _auth: Annotated[AuthContext, Depends(require_write_auth)],
        workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    ) -> JSONResponse:
        access_error = _knowledge_base_role_error_by_name(
            session=session,
            auth=_auth,
            kb_name=kb_name,
            workspace_id=workspace_id,
            minimum="editor",
        )
        if access_error is not None:
            return access_error
        gcs_env = {
            "GCS_ACCESS_KEY": request.access_key,
            "GCS_SECRET_KEY": request.secret_key,
        }
        config: dict[str, Any] = {
            "access_key": "env:GCS_ACCESS_KEY",
            "secret_key": "env:GCS_SECRET_KEY",
            "bucket": request.bucket,
            "prefix": request.prefix,
            "path_template": request.path_template,
            "overwrite": request.overwrite,
            "dry_run": request.dry_run,
            "include_retrieval_artifact": request.include_retrieval_artifact,
            "include_markdown_summary": request.include_markdown_summary,
            "parquet_export": request.parquet_export,
        }
        try:
            report = export_to_gcs(
                session,
                knowledge_base_name=kb_name,
                workspace_id=workspace_id,
                config=config,
                env=gcs_env,
            )
        except ValueError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})
        return JSONResponse(
            status_code=200,
            content={
                "pipeline_run_id": str(report.pipeline_run_id),
                "planned_count": report.planned_count,
                "uploaded_count": report.uploaded_count,
                "skipped_count": report.skipped_count,
                "failed_count": report.failed_count,
                "dry_run": report.dry_run,
                "artifact_keys": report.artifact_keys,
            },
        )

    # ── React SPA ──────────────────────────────────────────────────────────────
    _dist = Path(__file__).parent / "static" / "dist"
    if _dist.exists():
        app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="react-assets")

        @app.get("/ragrig-icon.svg", include_in_schema=False)
        def react_icon() -> FileResponse:
            return FileResponse(_dist / "ragrig-icon.svg")

        @app.get("/", include_in_schema=False)
        @app.get("/{path:path}", include_in_schema=False)
        def react_app(path: str = "") -> FileResponse:
            if path == "console" or path == "app" or path.startswith("app/"):
                raise HTTPException(status_code=404, detail="Not Found")
            return FileResponse(_dist / "index.html")

    return app


app = create_app()
