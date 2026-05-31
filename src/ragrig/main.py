from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import Session, sessionmaker

from ragrig import __version__
from ragrig.api.schemas import (
    AgentAccessExportRequest,
    AnswerRequest,
    AzureBlobExportRequest,
    BackblazeB2ExportRequest,
    CloudflareR2ExportRequest,
    EvaluationRunRequest,
    GcsExportRequest,
    ObjectStorageExportRequest,
    PermissionPreviewRequest,
    RetrievalSearchRequest,
    WebhookExportRequest,
)
from ragrig.config import Settings, get_settings
from ragrig.db.engine import create_db_engine
from ragrig.db.session import get_session as _get_session_default
from ragrig.health import create_database_check
from ragrig.ratelimit import RateLimiter
from ragrig.routers.admin import router as admin_router
from ragrig.routers.audit import router as audit_router
from ragrig.routers.auth import router as auth_router
from ragrig.routers.catalog_ops import router as catalog_ops_router
from ragrig.routers.conflicts import router as conflicts_router
from ragrig.routers.conversations import router as conversations_router
from ragrig.routers.evaluations import router as evaluations_router
from ragrig.routers.frontend import configure_frontend
from ragrig.routers.knowledge import router as knowledge_router
from ragrig.routers.knowledge_ingest import router as knowledge_ingest_router
from ragrig.routers.mcp import router as mcp_router
from ragrig.routers.openai_compat import router as openai_compat_router
from ragrig.routers.processing_profiles import router as processing_profiles_router
from ragrig.routers.retention import router as retention_router
from ragrig.routers.retrieval_api import router as retrieval_router
from ragrig.routers.runtime import set_runtime_state
from ragrig.routers.sink_exports import router as sink_exports_router
from ragrig.routers.source_webhooks import router as source_webhooks_router
from ragrig.routers.sources_pipeline import router as sources_pipeline_router
from ragrig.routers.system import router as system_router
from ragrig.routers.usage import router as usage_router
from ragrig.services.common import create_runtime_settings
from ragrig.services.common import serialize_error as _serialize_error
from ragrig.services.middleware import configure_cors, configure_structured_request_logging
from ragrig.tasks import default_task_executor, sanitize_filename

logger = logging.getLogger(__name__)


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

    def shutdown_task_executor() -> None:
        shutdown = getattr(active_task_executor, "shutdown", None)
        if shutdown is not None:
            shutdown(wait=True)

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
    configure_cors(app, active_settings)
    configure_structured_request_logging(app, logger)

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
    app.include_router(retrieval_router)
    app.include_router(evaluations_router)
    app.include_router(sink_exports_router)
    configure_frontend(app)
    return app


app = create_app()


__all__ = [
    "AgentAccessExportRequest",
    "AnswerRequest",
    "AzureBlobExportRequest",
    "BackblazeB2ExportRequest",
    "CloudflareR2ExportRequest",
    "EvaluationRunRequest",
    "GcsExportRequest",
    "ObjectStorageExportRequest",
    "PermissionPreviewRequest",
    "RetrievalSearchRequest",
    "WebhookExportRequest",
    "_sanitize_filename",
    "_serialize_error",
    "app",
    "create_app",
    "create_runtime_settings",
]
