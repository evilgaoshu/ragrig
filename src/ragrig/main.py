import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, File, Header, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker
from starlette.responses import Response

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
from ragrig.evaluation import (
    build_evaluation_list_report,
    build_evaluation_run_report,
    list_runs_from_store,
    load_run_from_store,
    run_evaluation,
)
from ragrig.formats import FormatStatus, get_format_registry
from ragrig.health import create_database_check
from ragrig.ingestion.pipeline import _select_parser
from ragrig.parsers.base import ParserTimeoutError, parse_with_timeout
from ragrig.plugins.enterprise import list_enterprise_connectors, probe_enterprise_connector
from ragrig.processing_profile import (
    ProfileStatus,
    TaskType,
    build_api_profile_list,
    build_matrix,
    create_override,
    delete_override,
    get_override,
    list_overrides,
    resolve_provider_availability,
    update_override,
)
from ragrig.providers.model_catalog import list_provider_models, measure_provider_latency
from ragrig.repositories import (
    create_pipeline_run,
    create_pipeline_run_item,
    get_knowledge_base_by_name,
    get_next_version_number,
    get_or_create_document,
    get_or_create_source,
)
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
    UnderstandingRunFilter,
    compare_understanding_runs,
    export_understanding_run,
    export_understanding_runs,
    generate_document_understanding,
    get_understanding_by_version,
    get_understanding_coverage,
    get_understanding_runs,
    understand_all_versions,
)
from ragrig.vectorstore import get_vector_backend, get_vector_backend_health
from ragrig.web_console import (
    PluginWizardValidationError,
    build_permission_preview,
    build_system_status,
    check_format,
    get_answer_live_smoke,
    get_pipeline_run_detail,
    get_recent_benchmark,
    get_retrieval_benchmark_integrity,
    get_sanitizer_contract_status,
    get_sanitizer_coverage,
    get_sanitizer_drift_history,
    get_sanitizer_drift_history_summary,
    get_understanding_export_diff,
    get_understanding_run_detail,
    list_document_version_chunks,
    list_documents,
    list_knowledge_bases,
    list_models,
    list_pipeline_run_items,
    list_pipeline_runs,
    list_plugins,
    list_sources,
    list_supported_formats,
    list_understanding_runs,
    load_console_html,
    validate_plugin_config_for_wizard,
)
from ragrig.workflows import (
    WorkflowDefinition,
    WorkflowStep,
    WorkflowValidationError,
    list_workflow_operations,
    run_workflow,
)


class EvaluationRunRequest(BaseModel):
    golden_path: str
    knowledge_base: str = "fixture-local"
    top_k: int = Field(default=5, ge=1, le=50)
    provider: str | None = None
    model: str | None = None
    dimensions: int | None = Field(default=None, gt=0)
    baseline_path: str | None = None


class RetrievalSearchRequest(BaseModel):
    knowledge_base: str
    query: str
    top_k: int = Field(default=5, ge=1, le=50)
    provider: str | None = None
    model: str | None = None
    dimensions: int | None = Field(default=None, gt=0)
    principal_ids: list[str] | None = None
    enforce_acl: bool = True
    # ── Hybrid / rerank fields (backward-compatible) ──
    mode: str = Field(
        default="dense",
        pattern=r"^(dense|hybrid|rerank|hybrid_rerank)$",
    )
    lexical_weight: float = Field(default=0.3, ge=0.0, le=1.0)
    vector_weight: float = Field(default=0.7, ge=0.0, le=1.0)
    candidate_k: int = Field(default=20, ge=1, le=200)
    reranker_provider: str | None = None
    reranker_model: str | None = None


class EnterpriseConnectorProbeRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowStepRequest(BaseModel):
    step_id: str
    operation: str
    config: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    max_retries: int = Field(default=0, ge=0, le=5)
    continue_on_error: bool = False


class WorkflowRunRequest(BaseModel):
    workflow_id: str
    steps: list[WorkflowStepRequest]
    dry_run: bool = False


class AnswerRequest(BaseModel):
    knowledge_base: str
    query: str
    top_k: int = Field(default=5, ge=1, le=50)
    provider: str = "deterministic-local"
    model: str | None = None
    dimensions: int | None = Field(default=None, gt=0)
    principal_ids: list[str] | None = None
    enforce_acl: bool = True


class PermissionPreviewRequest(BaseModel):
    principal_ids: list[str] | None = None


class CreateProcessingProfileRequest(BaseModel):
    profile_id: str
    extension: str
    task_type: TaskType
    display_name: str
    description: str
    provider: str
    model_id: str | None = None
    kind: str = "deterministic"
    tags: list[str] | None = None
    metadata: dict[str, object] | None = None
    created_by: str | None = None


class PatchProcessingProfileRequest(BaseModel):
    status: ProfileStatus | None = None
    display_name: str | None = None
    description: str | None = None
    provider: str | None = None
    model_id: str | None = None
    kind: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, object] | None = None


class DiffPreviewRequest(BaseModel):
    profile_id: str
    status: ProfileStatus | None = None
    display_name: str | None = None
    description: str | None = None
    provider: str | None = None
    model_id: str | None = None
    kind: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, object] | None = None


class RollbackRequest(BaseModel):
    audit_id: str
    actor: str | None = None


def _serialize_error(exc: RetrievalError) -> dict[str, Any]:
    return {
        "error": {
            "code": exc.code,
            "message": str(exc),
            "details": exc.details,
        }
    }


def _safe_chunk_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe = dict(metadata or {})
    if "acl" in safe:
        safe["acl"] = acl_summary_from_metadata(metadata)
    return safe


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


def _sanitize_filename(filename: str) -> str:
    """Remove path traversal characters and sanitize a filename."""
    from pathlib import PurePath

    name = PurePath(filename).name
    name = name.replace("/", "_").replace("\\", "_").replace("\0", "")
    if not name or name.startswith("."):
        name = f"upload_{name or 'file'}"
    return name


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

    @app.get("/models", response_model=None)
    def models(
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any]:
        return list_models(session)

    @app.get("/models/{provider_name:path}/available-models", response_model=None)
    def provider_available_models(provider_name: str) -> dict[str, Any]:
        return list_provider_models(provider_name)

    @app.post("/models/{provider_name:path}/speed-test", response_model=None)
    def provider_speed_test(provider_name: str) -> dict[str, Any]:
        return measure_provider_latency(provider_name)

    @app.get("/plugins", response_model=None)
    def plugins() -> dict[str, list[dict[str, Any]]]:
        return {"items": list_plugins()}

    @app.get("/enterprise-connectors", response_model=None)
    def enterprise_connectors() -> dict[str, list[dict[str, object]]]:
        return {"items": list_enterprise_connectors()}

    @app.post("/enterprise-connectors/{connector_id:path}/probe", response_model=None)
    def enterprise_connector_probe(
        connector_id: str,
        request: EnterpriseConnectorProbeRequest,
    ) -> dict[str, object]:
        return probe_enterprise_connector(connector_id, config=request.config)

    @app.get("/workflows/operations", response_model=None)
    def workflow_operations() -> dict[str, list[dict[str, object]]]:
        return {"items": list_workflow_operations()}

    @app.post("/workflows/runs", response_model=None)
    def workflow_run(
        request: WorkflowRunRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any] | JSONResponse:
        try:
            definition = WorkflowDefinition(
                workflow_id=request.workflow_id,
                steps=[
                    WorkflowStep(
                        step_id=step.step_id,
                        operation=step.operation,
                        config=step.config,
                        depends_on=step.depends_on,
                        max_retries=step.max_retries,
                        continue_on_error=step.continue_on_error,
                    )
                    for step in request.steps
                ],
            )
            return run_workflow(
                session=session,
                definition=definition,
                dry_run=request.dry_run,
            ).as_dict()
        except WorkflowValidationError as exc:
            return JSONResponse(status_code=400, content={"error": str(exc)})

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

    @app.get("/supported-formats", response_model=None)
    def supported_formats(
        status: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        return list_supported_formats(status=status)

    @app.get("/supported-formats/check", response_model=None)
    def supported_formats_check(
        extension: str,
    ) -> dict[str, Any] | JSONResponse:
        if not extension:
            return JSONResponse(
                status_code=400,
                content={"error": "extension query parameter is required"},
            )
        result = check_format(extension)
        return result

    @app.get("/sanitizer-coverage", response_model=None)
    def sanitizer_coverage() -> dict[str, Any] | None:
        """Return the sanitizer coverage summary for Web Console display.

        Reads golden snapshots from tests/goldens/ and returns a
        structured summary with parser-level redaction counts,
        degradation status, and golden hashes.

        Never includes raw secret fragments.
        """
        return get_sanitizer_coverage()

    @app.get("/sanitizer-drift-history", response_model=None)
    def sanitizer_drift_history() -> dict[str, Any]:
        """Return the sanitizer drift history for Web Console display.

        Reads drift diff artifacts from docs/operations/artifacts/ and
        returns a lightweight summary with risk level, base/head hashes,
        changed parser count, and trend sparklines.

        Never includes raw secret fragments.
        """
        return get_sanitizer_drift_history()

    @app.get("/sanitizer-drift-history-summary", response_model=None)
    def sanitizer_drift_history_summary() -> dict[str, Any]:
        """Return the sanitizer drift history summary for Web Console display.

        Reads the summary artifact from docs/operations/artifacts/ and
        returns latest status, risk, parser counts, degraded reports count,
        and summary path.

        Missing/corrupt artifacts are reported as degraded/failure.
        Never includes raw secret fragments.
        """
        return get_sanitizer_drift_history_summary()

    @app.get("/understanding-export-diff", response_model=None)
    def understanding_export_diff() -> dict[str, Any]:
        """Return the latest understanding export diff for Web Console display.

        Reads from the artifact at
        docs/operations/artifacts/understanding-export-diff.json.

        Returns a lightweight summary with status, baseline/current run counts,
        added/removed/changed counts, schema compatibility, and artifact path.

        Missing, corrupt, or schema-incompatible artifacts are reported as
        degraded/failure — never as pass.

        Never includes raw secret fragments.
        """
        return get_understanding_export_diff()

    @app.get("/sanitizer-contract-status", response_model=None)
    def sanitizer_contract_status() -> dict[str, Any]:
        """Return the latest sanitizer contract matrix status for Web Console display.

        Reads the artifact at
        docs/operations/artifacts/sanitizer-contract-matrix.json.

        Returns a lightweight summary with contract status, registered callsite
        count, unregistered count, summary fields check, duplicate impl check,
        and artifact path.

        Missing, corrupt, or schema-incompatible artifacts are reported as
        degraded/failure — never as pass.

        Never includes raw secret fragments.
        """
        return get_sanitizer_contract_status()

    @app.get("/retrieval/benchmark/recent", response_model=None)
    def retrieval_benchmark_recent() -> dict[str, Any]:
        """Return the most recent retrieval benchmark result.

        Reads from the baseline artifact at
        docs/operations/artifacts/retrieval-benchmark-baseline.json.

        Never includes raw secret fragments.
        """
        return get_recent_benchmark()

    @app.get("/retrieval/benchmark/integrity", response_model=None)
    def retrieval_benchmark_integrity() -> dict[str, Any]:
        """Return retrieval benchmark baseline integrity status.

        Evaluates manifest freshness, hash consistency, and schema
        compatibility.  Returns a lightweight summary safe for browser
        rendering — never includes raw secret fragments.
        """
        return get_retrieval_benchmark_integrity()

    @app.get("/answer/live-smoke", response_model=None)
    def answer_live_smoke() -> dict[str, Any]:
        """Return the latest answer live smoke diagnostics for Web Console display.

        Reads the artifact at
        docs/operations/artifacts/answer-live-smoke.json.

        Returns a lightweight summary with provider, model, status, reason,
        citation count, timing, and artifact path.

        Missing, corrupt, or stale artifacts are reported as degraded/failure
        — never as healthy.

        Never includes raw secret fragments.
        """
        return get_answer_live_smoke()

    @app.post("/knowledge-bases/{kb_name}/upload", response_model=None)
    async def knowledge_base_upload(
        kb_name: str,
        session: Annotated[Session, Depends(get_session)],
        files: Annotated[list[UploadFile], File(...)],
    ) -> JSONResponse:
        from ragrig.db.models import DocumentVersion

        kb = get_knowledge_base_by_name(session, kb_name)
        if kb is None:
            return JSONResponse(
                status_code=404,
                content={"error": f"knowledge base '{kb_name}' not found"},
            )

        if not files:
            return JSONResponse(
                status_code=400,
                content={"error": "at least one file is required"},
            )

        registry = get_format_registry()
        accepted_files: list[UploadFile] = []
        rejected: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        for f in files:
            filename = f.filename or "unknown"
            extension = Path(filename).suffix.lower()
            if not extension:
                extension = ""

            fmt = registry.lookup(extension)
            if fmt is None:
                rejected.append(
                    {
                        "filename": filename,
                        "extension": extension or "(none)",
                        "reason": "unsupported_format",
                        "message": (
                            f"File format {extension or '(no extension)'} is not supported."
                        ),
                    }
                )
                continue

            if fmt.status == FormatStatus.PLANNED:
                rejected.append(
                    {
                        "filename": filename,
                        "extension": extension,
                        "reason": "unsupported_format",
                        "message": (
                            f"{fmt.display_name} support is planned. "
                            f"{fmt.limitations or 'Not yet implemented.'}"
                        ),
                    }
                )
                continue

            if fmt.status == FormatStatus.PREVIEW:
                warnings.append(
                    {
                        "filename": filename,
                        "extension": extension,
                        "status": "preview",
                        "parser_id": fmt.parser_id,
                        "fallback_policy": fmt.fallback_policy,
                        "message": (
                            f"{fmt.display_name} is in preview status — "
                            f"{fmt.limitations or 'content will be parsed as plain text.'}"
                        ),
                    }
                )

            accepted_files.append(f)

        if not accepted_files:
            return JSONResponse(
                status_code=415,
                content={
                    "accepted_files": 0,
                    "rejected_files": len(rejected),
                    "rejections": rejected,
                    "warnings": warnings,
                },
            )

        if len(accepted_files) > 10:
            return JSONResponse(
                status_code=400,
                content={
                    "error": (
                        f"too many files: {len(accepted_files)}. Maximum 10 files per request."
                    ),
                },
            )

        with tempfile.TemporaryDirectory(prefix="ragrig-upload-") as staging_dir:
            staging_path = Path(staging_dir)
            saved_paths: list[Path] = []

            for f in accepted_files:
                filename = f.filename or "unnamed"
                safe_name = _sanitize_filename(filename)
                dest = staging_path / safe_name
                content = await f.read()
                extension = Path(filename).suffix.lower()
                fmt = registry.lookup(extension)
                max_size = (fmt.max_file_size_mb * 1024 * 1024) if fmt else (10 * 1024 * 1024)
                if len(content) > max_size:
                    rejected.append(
                        {
                            "filename": filename,
                            "extension": extension,
                            "reason": "file_too_large",
                            "message": (
                                f"File '{filename}' exceeds the {fmt.max_file_size_mb} MB "
                                f"size limit for {fmt.display_name}."
                            ),
                        }
                    )
                    continue
                dest.write_bytes(content)
                saved_paths.append(dest)

            if not saved_paths:
                return JSONResponse(
                    status_code=413,
                    content={
                        "accepted_files": 0,
                        "rejected_files": len(rejected),
                        "rejections": rejected,
                        "warnings": warnings,
                    },
                )

            source = get_or_create_source(
                session,
                knowledge_base_id=kb.id,
                uri=str(staging_path),
                config_json={
                    "kind": "web_upload",
                    "staging_dir": str(staging_path),
                },
            )

            run = create_pipeline_run(
                session,
                knowledge_base_id=kb.id,
                source_id=source.id,
                run_type="web_upload",
                config_snapshot_json={
                    "source": "web_upload",
                    "knowledge_base": kb_name,
                    "file_count": len(saved_paths),
                },
            )

            created_documents = 0
            created_versions = 0
            failed_count = 0

            for dest in saved_paths:
                document = None
                item_status = "success"
                item_error: str | None = None
                item_metadata: dict[str, Any] = {"file_name": dest.name}
                try:
                    parser = _select_parser(dest)
                    parse_result = parse_with_timeout(parser, dest, timeout_seconds=30.0)
                    document, was_created = get_or_create_document(
                        session,
                        knowledge_base_id=kb.id,
                        source_id=source.id,
                        uri=str(dest),
                        content_hash=parse_result.content_hash,
                        mime_type=parse_result.mime_type,
                        metadata_json=parse_result.metadata,
                    )
                    if was_created:
                        created_documents += 1

                    version = DocumentVersion(
                        document_id=document.id,
                        version_number=get_next_version_number(session, document_id=document.id),
                        content_hash=parse_result.content_hash,
                        parser_name=parse_result.parser_name,
                        parser_config_json={"plugin_id": f"parser.{parse_result.parser_name}"},
                        extracted_text=parse_result.extracted_text,
                        metadata_json=parse_result.metadata,
                    )
                    session.add(version)
                    session.flush()
                    created_versions += 1

                    item_metadata["version_number"] = version.version_number
                    item_metadata["parser_name"] = parse_result.parser_name
                    item_metadata["parser_id"] = f"parser.{parse_result.parser_name}"
                    degraded_reason = parse_result.metadata.get("degraded_reason")
                    if degraded_reason:
                        item_status = "degraded"
                        item_metadata["degraded_reason"] = degraded_reason
                except ParserTimeoutError as exc:
                    failed_count += 1
                    item_status = "failed"
                    item_error = str(exc)
                    item_metadata["failure_reason"] = "parser_timeout"
                    if document is None:
                        document, _ = get_or_create_document(
                            session,
                            knowledge_base_id=kb.id,
                            source_id=source.id,
                            uri=str(dest),
                            content_hash="timeout",
                            mime_type="text/plain",
                            metadata_json={"failure_reason": "parser_timeout", "path": str(dest)},
                        )
                except Exception as exc:
                    failed_count += 1
                    item_status = "failed"
                    item_error = str(exc)
                    item_metadata["failure_reason"] = str(exc)
                    if document is None:
                        document, _ = get_or_create_document(
                            session,
                            knowledge_base_id=kb.id,
                            source_id=source.id,
                            uri=str(dest),
                            content_hash="failed",
                            mime_type="text/plain",
                            metadata_json={"failure_reason": str(exc), "path": str(dest)},
                        )

                create_pipeline_run_item(
                    session,
                    pipeline_run_id=run.id,
                    document_id=document.id,
                    status=item_status,
                    error_message=item_error,
                    metadata_json=item_metadata,
                )

            run.total_items = len(saved_paths)
            run.success_count = created_versions
            run.failure_count = failed_count
            run.status = "completed_with_failures" if failed_count else "completed"
            run.finished_at = datetime.now(timezone.utc)
            session.commit()

            return JSONResponse(
                status_code=202,
                content={
                    "pipeline_run_id": str(run.id),
                    "accepted_files": len(saved_paths),
                    "rejected_files": len(rejected),
                    "rejections": rejected,
                    "warnings": warnings,
                },
            )

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
                mode=request.mode,
                lexical_weight=request.lexical_weight,
                vector_weight=request.vector_weight,
                candidate_k=request.candidate_k,
                reranker_provider=request.reranker_provider,
                reranker_model=request.reranker_model,
            )
        except KnowledgeBaseNotFoundError as exc:
            return JSONResponse(status_code=404, content=_serialize_error(exc))
        except (EmptyQueryError, EmbeddingProfileMismatchError, InvalidTopKError) as exc:
            return JSONResponse(status_code=400, content=_serialize_error(exc))

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
            "total_results": report.total_results,
            "acl_explain": report.acl_explain,
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
                }
                for result in report.results
            ],
        }
        if report.degraded:
            response["degraded"] = True
            response["degraded_reason"] = report.degraded_reason
        return response

    @app.post("/permissions/preview", response_model=None)
    def permission_preview(
        request: PermissionPreviewRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any]:
        return build_permission_preview(session, principal_ids=request.principal_ids)

    @app.post("/evaluations/runs", response_model=None)
    def evaluation_run(
        request: EvaluationRunRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any] | JSONResponse:
        """Run a golden question evaluation against a knowledge base."""
        from pathlib import Path

        golden_path = Path(request.golden_path)
        if not golden_path.exists():
            return JSONResponse(
                status_code=404,
                content={"error": f"Golden question file not found: {golden_path}"},
            )

        baseline_path = Path(request.baseline_path) if request.baseline_path else None
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
        store_dir: str | None = None,
    ) -> dict[str, Any] | JSONResponse:
        """Get details for a specific evaluation run."""
        store_path = Path(store_dir) if store_dir else Path("evaluation_runs")
        run = load_run_from_store(run_id, store_dir=store_path)
        if run is None:
            return JSONResponse(
                status_code=404,
                content={"error": "evaluation_run_not_found"},
            )
        return build_evaluation_run_report(run, include_items=True)

    @app.get("/evaluations", response_model=None)
    def evaluation_runs_list(
        store_dir: str | None = None,
    ) -> dict[str, Any]:
        """List all evaluation runs."""
        store_path = Path(store_dir) if store_dir else Path("evaluation_runs")
        runs = list_runs_from_store(store_dir=store_path)
        return build_evaluation_list_report(runs)

    @app.get("/evaluations/baselines", response_model=None)
    def evaluation_baselines_list(
        baseline_dir: str | None = None,
    ) -> dict[str, Any] | JSONResponse:
        """List all baselines and current baseline id."""
        from ragrig.evaluation.baseline import list_baselines

        path = Path(baseline_dir) if baseline_dir else Path("evaluation_baselines")
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
    ) -> dict[str, Any] | JSONResponse:
        try:
            vector_backend = resolve_vector_backend()
            report = generate_answer(
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

        return {
            "answer": report.answer,
            "citations": [
                {
                    "citation_id": c.citation_id,
                    "document_uri": c.document_uri,
                    "chunk_id": c.chunk_id,
                    "chunk_index": c.chunk_index,
                    "text_preview": c.text_preview,
                    "score": c.score,
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
                }
                for ec in report.evidence_chunks
            ],
            "model": report.model,
            "provider": report.provider,
            "retrieval_trace": report.retrieval_trace,
            "grounding_status": report.grounding_status,
            "refusal_reason": report.refusal_reason,
        }

    @app.get("/processing-profiles", response_model=None)
    def processing_profiles(
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, list[dict[str, Any]]]:
        return {"profiles": build_api_profile_list(session=session)}

    @app.get("/processing-profiles/overrides", response_model=None)
    def processing_profile_overrides(
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, list[dict[str, Any]]]:
        return {"overrides": [p.to_api_dict() for p in list_overrides(session=session)]}

    @app.get("/processing-profiles/overrides/{profile_id}", response_model=None)
    def processing_profile_override_detail(
        profile_id: str,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any] | JSONResponse:
        profile = get_override(profile_id, session=session)
        if profile is None:
            return JSONResponse(status_code=404, content={"error": "override_not_found"})
        entry = profile.to_api_dict()
        entry["provider_available"] = resolve_provider_availability(profile.provider)
        return entry

    @app.post("/processing-profiles", response_model=None)
    def create_processing_profile(
        request: CreateProcessingProfileRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any] | JSONResponse:
        from ragrig.processing_profile.models import ProcessingKind

        kind = ProcessingKind.DETERMINISTIC
        if request.kind == "LLM-assisted":
            kind = ProcessingKind.LLM_ASSISTED
        try:
            profile = create_override(
                profile_id=request.profile_id,
                extension=request.extension,
                task_type=request.task_type,
                display_name=request.display_name,
                description=request.description,
                provider=request.provider,
                model_id=request.model_id,
                kind=kind,
                tags=request.tags,
                metadata=request.metadata,
                created_by=request.created_by,
                session=session,
            )
            session.commit()
        except ValueError as exc:
            return JSONResponse(status_code=409, content={"error": str(exc)})
        entry = profile.to_api_dict()
        entry["provider_available"] = resolve_provider_availability(profile.provider)
        return entry

    @app.patch("/processing-profiles/overrides/{profile_id}", response_model=None)
    def patch_processing_profile(
        profile_id: str,
        request: PatchProcessingProfileRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any] | JSONResponse:
        from ragrig.processing_profile.models import ProcessingKind

        if get_override(profile_id, session=session) is None:
            return JSONResponse(status_code=404, content={"error": "override_not_found"})
        kind = None
        if request.kind is not None:
            kind = (
                ProcessingKind.LLM_ASSISTED
                if request.kind == "LLM-assisted"
                else ProcessingKind.DETERMINISTIC
            )
        try:
            profile = update_override(
                profile_id,
                status=request.status,
                display_name=request.display_name,
                description=request.description,
                provider=request.provider,
                model_id=request.model_id,
                kind=kind,
                tags=request.tags,
                metadata=request.metadata,
                session=session,
            )
            session.commit()
        except ValueError as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})
        entry = profile.to_api_dict()
        entry["provider_available"] = resolve_provider_availability(profile.provider)
        return entry

    @app.delete("/processing-profiles/overrides/{profile_id}", response_model=None)
    def delete_processing_profile(
        profile_id: str,
        session: Annotated[Session, Depends(get_session)],
    ) -> Response | JSONResponse:
        deleted = delete_override(profile_id, session=session)
        if not deleted:
            return JSONResponse(status_code=404, content={"error": "override_not_found"})
        session.commit()
        return Response(status_code=204)

    @app.get("/processing-profiles/matrix", response_model=None)
    def processing_profiles_matrix(
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any]:
        return build_matrix(session=session)

    @app.get("/processing-profiles/audit-log", response_model=None)
    def processing_profile_audit_log(
        session: Annotated[Session, Depends(get_session)],
        limit: int = 50,
        profile_id: str | None = None,
        action: str | None = None,
        provider: str | None = None,
        task_type: str | None = None,
    ) -> dict[str, list[dict[str, Any]]]:
        from ragrig.repositories.processing_profile import list_audit_log as _db_audit

        entries = _db_audit(
            session,
            limit=limit,
            profile_id=profile_id,
            action=action,
            provider=provider,
            task_type=task_type,
        )
        return {"entries": entries}

    @app.get("/processing-profiles/audit-log/{audit_id}", response_model=None)
    def processing_profile_audit_entry(
        audit_id: str,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any] | JSONResponse:
        from ragrig.repositories.processing_profile import get_audit_entry_by_id as _db_get_audit

        entry = _db_get_audit(session, audit_id)
        if entry is None:
            return JSONResponse(status_code=404, content={"error": "audit_entry_not_found"})
        return {
            "id": str(entry.id),
            "profile_id": entry.profile_id,
            "action": entry.action,
            "actor": entry.actor,
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
            "old_state": entry.old_state,
            "new_state": entry.new_state,
        }

    @app.post("/processing-profiles/preview-diff", response_model=None)
    def processing_profile_preview_diff(
        request: DiffPreviewRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any] | JSONResponse:
        from ragrig.repositories.processing_profile import compute_diff as _db_diff

        metadata_json = (
            {str(k): v for k, v in (request.metadata or {}).items()}
            if request.metadata is not None
            else None
        )

        diff = _db_diff(
            session,
            profile_id=request.profile_id,
            status=request.status.value if request.status else None,
            display_name=request.display_name,
            description=request.description,
            provider=request.provider,
            model_id=request.model_id,
            kind=request.kind,
            tags=request.tags,
            metadata_json=metadata_json,
        )
        if diff is None:
            return JSONResponse(status_code=404, content={"error": "override_not_found"})
        return diff

    @app.post("/processing-profiles/rollback", response_model=None)
    def processing_profile_rollback(
        request: RollbackRequest,
        session: Annotated[Session, Depends(get_session)],
    ) -> dict[str, Any] | JSONResponse:
        from ragrig.processing_profile import resolve_provider_availability
        from ragrig.processing_profile.registry import _db_override_to_dataclass
        from ragrig.repositories.processing_profile import (
            rollback_override as _db_rollback,
        )

        try:
            override = _db_rollback(
                session,
                audit_id=request.audit_id,
                actor=request.actor,
            )
            session.commit()
        except ValueError as exc:
            msg = str(exc)
            if "not found" in msg:
                return JSONResponse(status_code=404, content={"error": msg})
            return JSONResponse(status_code=409, content={"error": msg})

        profile = _db_override_to_dataclass(override)
        entry = profile.to_api_dict()
        entry["provider_available"] = resolve_provider_availability(profile.provider)
        return entry

    return app


app = create_app()
