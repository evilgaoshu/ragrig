from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from ragrig import __version__
from ragrig.config import Settings, get_settings
from ragrig.db.engine import create_db_engine
from ragrig.health import create_database_check
from ragrig.processing_profile import build_api_profile_list, build_matrix
from ragrig.retrieval import (
    EmbeddingProfileMismatchError,
    EmptyQueryError,
    InvalidTopKError,
    KnowledgeBaseNotFoundError,
    RetrievalError,
    search_knowledge_base,
)
from ragrig.understanding import (
    DocumentVersionNotFoundError,
    ProviderUnavailableError,
    UnderstandAllRequest,
    UnderstandingRequest,
    generate_document_understanding,
    get_understanding_by_version,
    get_understanding_coverage,
    understand_all_versions,
)
from ragrig.vectorstore import get_vector_backend, get_vector_backend_health
from ragrig.web_console import (
    PluginWizardValidationError,
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
    validate_plugin_config_for_wizard,
)


class RetrievalSearchRequest(BaseModel):
    knowledge_base: str
    query: str
    top_k: int = Field(default=5, ge=1, le=50)
    provider: str | None = None
    model: str | None = None
    dimensions: int | None = Field(default=None, gt=0)
    principal_ids: list[str] | None = None
    enforce_acl: bool = True


def _serialize_error(exc: RetrievalError) -> dict[str, Any]:
    return {
        "error": {
            "code": exc.code,
            "message": str(exc),
            "details": exc.details,
        }
    }


def _plugin_validation_error_response(*, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "valid": False,
            "error": {
                "code": code,
                "message": message,
            },
        },
    )


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
            settings=active_settings,
            vector_health=get_vector_backend_health(session, active_settings),
            database_ok=database_ok,
            database_detail=detail,
        )

    @app.get("/knowledge-bases", response_model=None)
    def knowledge_bases(
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, list[dict[str, Any]]]:
        return {"items": list_knowledge_bases(session, settings=active_settings)}

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

    @app.post("/document-versions/{document_version_id}/understand", response_model=None)
    def understand_document_version(
        document_version_id: str,
        request: UnderstandingRequest,
        session: Annotated[Session, Depends(get_session)],
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
    ) -> dict[str, Any] | JSONResponse:
        record = get_understanding_by_version(session, document_version_id)
        if record is None:
            return JSONResponse(
                status_code=404,
                content={
                    "error": "understanding_not_found",
                    "message": (
                        f"No understanding result for document version '{document_version_id}'."
                    ),
                },
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
    ) -> dict[str, Any] | JSONResponse:
        try:
            result = understand_all_versions(
                session,
                knowledge_base_id=kb_id,
                provider=request.provider,
                model=request.model,
                profile_id=request.profile_id,
            )
        except ProviderUnavailableError as exc:
            return JSONResponse(status_code=503, content={"error": exc.code, "message": str(exc)})
        return {
            "total": result.total,
            "created": result.created,
            "skipped": result.skipped,
            "failed": result.failed,
            "errors": [
                {"version_id": e.version_id, "error": e.error} for e in result.errors
            ],
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
        }

    @app.get("/models", response_model=None)
    def models(
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any]:
        return list_models(session)

    @app.get("/plugins", response_model=None)
    def plugins() -> dict[str, list[dict[str, Any]]]:
        return {"items": list_plugins()}

    @app.post("/plugins/{plugin_id}/validate-config", response_model=None)
    async def validate_plugin_config(
        plugin_id: str,
        request: Request,
    ) -> dict[str, Any] | JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            return _plugin_validation_error_response(
                code="malformed_request",
                message="request body must be valid JSON",
            )
        if not isinstance(payload, dict):
            return _plugin_validation_error_response(
                code="malformed_request",
                message="request body must be a JSON object",
            )
        config = payload.get("config", {})
        if not isinstance(config, dict):
            return _plugin_validation_error_response(
                code="malformed_request",
                message="config must be a JSON object",
            )
        try:
            return validate_plugin_config_for_wizard(plugin_id, config)
        except PluginWizardValidationError as exc:
            return _plugin_validation_error_response(code=exc.code, message=exc.message)

    @app.post("/retrieval/search", response_model=None)
    def retrieval_search(
        request: RetrievalSearchRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any] | JSONResponse:
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
                principal_ids=request.principal_ids,
                enforce_acl=request.enforce_acl,
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
            "backend": report.backend,
            "backend_metadata": report.backend_metadata,
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

    @app.get("/processing-profiles", response_model=None)
    def processing_profiles() -> dict[str, list[dict[str, Any]]]:
        return {"profiles": build_api_profile_list()}

    @app.get("/processing-profiles/matrix", response_model=None)
    def processing_profiles_matrix() -> dict[str, Any]:
        return build_matrix()

    return app


app = create_app()
