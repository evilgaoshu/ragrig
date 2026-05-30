import logging
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request
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
from ragrig.config import Settings, get_settings
from ragrig.db.engine import create_db_engine
from ragrig.db.models import KnowledgeBase
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
from ragrig.knowledge_base_config import (
    kb_role_model_config,
    public_role_model_selection,
    role_model_selection,
)
from ragrig.local_pilot import ModelConfigError
from ragrig.local_pilot.model_config import resolve_env_config
from ragrig.observability import bind_log_context, log_event
from ragrig.plugins.sinks.agent_access.connector import export_to_agent_endpoint
from ragrig.plugins.sinks.azure_blob.connector import export_to_azure_blob
from ragrig.plugins.sinks.backblaze_b2.connector import export_to_backblaze_b2
from ragrig.plugins.sinks.cloudflare_r2.connector import export_to_cloudflare_r2
from ragrig.plugins.sinks.gcs.connector import export_to_gcs
from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage
from ragrig.plugins.sinks.webhook.connector import export_to_webhook
from ragrig.ratelimit import RateLimiter
from ragrig.repositories import get_knowledge_base_by_name
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
from ragrig.routers.knowledge import router as knowledge_router
from ragrig.routers.knowledge_ingest import router as knowledge_ingest_router
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
    default_task_executor,
    sanitize_filename,
)
from ragrig.vectorstore import get_vector_backend
from ragrig.web_console import build_permission_preview

logger = logging.getLogger(__name__)


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

    @app.middleware("http")
    async def structured_request_logging(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        started = perf_counter()
        with bind_log_context(request_id=request_id):
            log_event(
                logger,
                logging.INFO,
                "api.request.start",
                method=request.method,
                route=request.url.path,
            )
            try:
                response = await call_next(request)
            except Exception as exc:
                log_event(
                    logger,
                    logging.ERROR,
                    "api.request.failed",
                    method=request.method,
                    route=request.url.path,
                    duration_ms=round((perf_counter() - started) * 1000, 3),
                    error=str(exc),
                    exc_info=True,
                )
                raise
            response.headers["X-Request-ID"] = request_id
            log_event(
                logger,
                logging.INFO,
                "api.request.completed",
                method=request.method,
                route=request.url.path,
                status_code=response.status_code,
                duration_ms=round((perf_counter() - started) * 1000, 3),
            )
            return response

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
        rate_limiter=rate_limiter,
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
    app.include_router(knowledge_router)
    app.include_router(knowledge_ingest_router)
    app.include_router(sources_pipeline_router)
    app.include_router(admin_router)

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
        persisted_role_config = kb_role_model_config(answer_kb)
        effective_role_config = (
            request.role_model_config
            if request.role_model_config is not None
            else persisted_role_config
        )
        role_selection, role_error = role_model_selection(request.role, effective_role_config)
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

        public_role_selection = public_role_model_selection(role_selection)
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
