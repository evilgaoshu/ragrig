from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from ragrig import __version__
from ragrig.config import Settings, get_settings
from ragrig.db.engine import create_db_engine
from ragrig.health import create_database_check
from ragrig.retrieval import (
    EmbeddingProfileMismatchError,
    EmptyQueryError,
    InvalidTopKError,
    KnowledgeBaseNotFoundError,
    RetrievalError,
    search_knowledge_base,
)
from ragrig.web_console import (
    build_system_status,
    get_pipeline_run_detail,
    list_document_version_chunks,
    list_documents,
    list_knowledge_bases,
    list_models,
    list_pipeline_run_items,
    list_pipeline_runs,
    list_plugins,
    list_sources,
    load_console_html,
)


class RetrievalSearchRequest(BaseModel):
    knowledge_base: str
    query: str
    top_k: int = Field(default=5, ge=1, le=50)
    provider: str | None = None
    model: str | None = None
    dimensions: int | None = Field(default=None, gt=0)


def _serialize_error(exc: RetrievalError) -> dict[str, Any]:
    return {
        "error": {
            "code": exc.code,
            "message": str(exc),
            "details": exc.details,
        }
    }


def create_runtime_settings(settings: Settings | None = None) -> Settings:
    active_settings = settings or get_settings()
    payload = active_settings.model_dump()
    payload["database_url"] = active_settings.runtime_database_url
    return Settings(**payload)


def create_app(
    check_database: Callable[[], None] | None = None,
    session_factory: Callable[[], Session] | None = None,
    settings: Settings | None = None,
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

    app = FastAPI(title="RAGRig", version=__version__)

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

    @app.get("/health", response_model=None)
    def health() -> dict[str, str] | JSONResponse:
        try:
            database_check()
        except Exception as exc:  # pragma: no cover - covered via contract test
            return JSONResponse(
                status_code=503,
                content={
                    "status": "unhealthy",
                    "app": "ok",
                    "db": "error",
                    "detail": str(exc),
                    "version": __version__,
                },
            )

        return {
            "status": "healthy",
            "app": "ok",
            "db": "connected",
            "version": __version__,
        }

    @app.get("/console", response_class=HTMLResponse)
    def console() -> HTMLResponse:
        return HTMLResponse(load_console_html())

    @app.get("/system/status", response_model=None)
    def system_status(
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any]:
        detail: str | None = None
        database_ok = True
        try:
            database_check()
        except Exception as exc:  # pragma: no cover - exercised via route contract tests
            detail = str(exc)
            database_ok = False
        return build_system_status(
            session,
            database_ok=database_ok,
            database_detail=detail,
        )

    @app.get("/knowledge-bases", response_model=None)
    def knowledge_bases(
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, list[dict[str, Any]]]:
        return {"items": list_knowledge_bases(session)}

    @app.get("/sources", response_model=None)
    def sources(
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, list[dict[str, Any]]]:
        return {"items": list_sources(session)}

    @app.get("/pipeline-runs", response_model=None)
    def pipeline_runs(
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, list[dict[str, Any]]]:
        return {"items": list_pipeline_runs(session)}

    @app.get("/pipeline-runs/{pipeline_run_id}", response_model=None)
    def pipeline_run_detail(
        pipeline_run_id: str,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any] | JSONResponse:
        detail = get_pipeline_run_detail(session, pipeline_run_id)
        if detail is None:
            return JSONResponse(status_code=404, content={"error": "pipeline_run_not_found"})
        return detail

    @app.get("/pipeline-runs/{pipeline_run_id}/items", response_model=None)
    def pipeline_run_items(
        pipeline_run_id: str,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, list[dict[str, Any]]]:
        return {"items": list_pipeline_run_items(session, pipeline_run_id)}

    @app.get("/documents", response_model=None)
    def documents(
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, list[dict[str, Any]]]:
        return {"items": list_documents(session)}

    @app.get("/document-versions/{document_version_id}/chunks", response_model=None)
    def document_version_chunks(
        document_version_id: str,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, list[dict[str, Any]]]:
        return {"items": list_document_version_chunks(session, document_version_id)}

    @app.get("/models", response_model=None)
    def models(
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any]:
        return list_models(session)

    @app.get("/plugins", response_model=None)
    def plugins() -> dict[str, list[dict[str, Any]]]:
        return {"items": list_plugins()}

    @app.post("/retrieval/search", response_model=None)
    def retrieval_search(
        request: RetrievalSearchRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any] | JSONResponse:
        try:
            report = search_knowledge_base(
                session=session,
                knowledge_base_name=request.knowledge_base,
                query=request.query,
                top_k=request.top_k,
                provider=request.provider,
                model=request.model,
                dimensions=request.dimensions,
            )
        except KnowledgeBaseNotFoundError as exc:
            return JSONResponse(status_code=404, content=_serialize_error(exc))
        except (EmptyQueryError, EmbeddingProfileMismatchError, InvalidTopKError) as exc:
            return JSONResponse(status_code=400, content=_serialize_error(exc))

        return {
            "knowledge_base": report.knowledge_base,
            "query": report.query,
            "top_k": report.top_k,
            "provider": report.provider,
            "model": report.model,
            "dimensions": report.dimensions,
            "distance_metric": report.distance_metric,
            "total_results": report.total_results,
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
                    "chunk_metadata": result.chunk_metadata,
                }
                for result in report.results
            ],
        }

    return app


app = create_app()
