"""Model, plugin, format, workflow, and operations artifact routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ragrig.config import Settings, get_settings
from ragrig.db.session import get_session
from ragrig.deps import AuthContext, require_write_auth
from ragrig.plugins.enterprise import list_enterprise_connectors, probe_enterprise_connector
from ragrig.providers.model_catalog import list_provider_models, measure_provider_latency
from ragrig.security_paths import PathPolicyError, resolve_local_ingestion_root
from ragrig.web_console import (
    PluginWizardValidationError,
    check_format,
    get_advanced_parser_corpus,
    get_answer_live_smoke,
    get_ops_diagnostics,
    get_recent_benchmark,
    get_retrieval_benchmark_integrity,
    get_sanitizer_contract_status,
    get_sanitizer_coverage,
    get_sanitizer_drift_history,
    get_sanitizer_drift_history_summary,
    get_understanding_export_diff,
    list_models,
    list_plugins,
    list_supported_formats,
    validate_plugin_config_for_wizard,
)
from ragrig.workflows import (
    WorkflowDefinition,
    WorkflowStep,
    WorkflowValidationError,
    list_workflow_operations,
    run_workflow,
)

router = APIRouter(tags=["catalog-ops"])


class EnterpriseConnectorProbeRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowStepRequest(BaseModel):
    step_id: str
    operation: str
    config: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    max_retries: int = Field(default=0, ge=0, le=5)
    retry_backoff_seconds: float = Field(default=0.0, ge=0, le=60)
    retry_backoff_multiplier: float = Field(default=2.0, ge=1, le=10)
    continue_on_error: bool = False


class WorkflowRunRequest(BaseModel):
    workflow_id: str
    steps: list[WorkflowStepRequest]
    dry_run: bool = False


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


@router.get("/models", response_model=None)
def models(
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    return list_models(session)


@router.get("/models/{provider_name:path}/available-models", response_model=None)
def provider_available_models(provider_name: str) -> dict[str, Any]:
    return list_provider_models(provider_name)


@router.post("/models/{provider_name:path}/speed-test", response_model=None)
def provider_speed_test(provider_name: str) -> dict[str, Any]:
    return measure_provider_latency(provider_name)


@router.get("/plugins", response_model=None)
def plugins() -> dict[str, list[dict[str, Any]]]:
    return {"items": list_plugins()}


@router.get("/enterprise-connectors", response_model=None)
def enterprise_connectors() -> dict[str, list[dict[str, object]]]:
    return {"items": list_enterprise_connectors()}


@router.post("/enterprise-connectors/{connector_id:path}/probe", response_model=None)
def enterprise_connector_probe(
    connector_id: str,
    request: EnterpriseConnectorProbeRequest,
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object] | JSONResponse:
    config = dict(request.config)
    try:
        if connector_id == "source.local" or (
            connector_id == "source.fileshare" and config.get("protocol") == "nfs_mounted"
        ):
            config["root_path"] = str(
                resolve_local_ingestion_root(str(config.get("root_path", "")), settings=settings)
            )
    except PathPolicyError as exc:
        return JSONResponse(
            status_code=400,
            content={
                "connector_id": connector_id,
                "status": "rejected",
                "network_called": False,
                "reason": str(exc),
            },
        )
    return probe_enterprise_connector(connector_id, config=config)


@router.get("/workflows/operations", response_model=None)
def workflow_operations() -> dict[str, list[dict[str, object]]]:
    return {"items": list_workflow_operations()}


@router.post("/workflows/runs", response_model=None)
def workflow_run(
    request: WorkflowRunRequest,
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_write_auth)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any] | JSONResponse:
    try:
        definition = WorkflowDefinition(
            workflow_id=request.workflow_id,
            steps=[
                WorkflowStep(
                    step_id=step.step_id,
                    operation=step.operation,
                    config=_validated_workflow_step_config(step, settings),
                    depends_on=step.depends_on,
                    max_retries=step.max_retries,
                    retry_backoff_seconds=step.retry_backoff_seconds,
                    retry_backoff_multiplier=step.retry_backoff_multiplier,
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
    except (WorkflowValidationError, PathPolicyError) as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})


def _validated_workflow_step_config(
    step: WorkflowStepRequest, settings: Settings
) -> dict[str, Any]:
    config = dict(step.config)
    if step.operation == "ingest.local":
        config["root_path"] = str(
            resolve_local_ingestion_root(str(config.get("root_path", "")), settings=settings)
        )
    elif step.operation == "ingest.fileshare" and config.get("protocol") == "nfs_mounted":
        config["root_path"] = str(
            resolve_local_ingestion_root(str(config.get("root_path", "")), settings=settings)
        )
    return config


@router.post("/plugins/{plugin_id}/validate-config", response_model=None)
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


@router.get("/supported-formats", response_model=None)
def supported_formats(
    status: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    return list_supported_formats(status=status)


@router.get("/supported-formats/check", response_model=None)
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


@router.get("/sanitizer-coverage", response_model=None)
def sanitizer_coverage() -> dict[str, Any] | None:
    """Return the sanitizer coverage summary for Web Console display."""
    return get_sanitizer_coverage()


@router.get("/sanitizer-drift-history", response_model=None)
def sanitizer_drift_history() -> dict[str, Any]:
    """Return the sanitizer drift history for Web Console display."""
    return get_sanitizer_drift_history()


@router.get("/sanitizer-drift-history-summary", response_model=None)
def sanitizer_drift_history_summary() -> dict[str, Any]:
    """Return the sanitizer drift history summary for Web Console display."""
    return get_sanitizer_drift_history_summary()


@router.get("/understanding-export-diff", response_model=None)
def understanding_export_diff() -> dict[str, Any]:
    """Return the latest understanding export diff for Web Console display."""
    return get_understanding_export_diff()


@router.get("/sanitizer-contract-status", response_model=None)
def sanitizer_contract_status() -> dict[str, Any]:
    """Return the latest sanitizer contract matrix status for Web Console display."""
    return get_sanitizer_contract_status()


@router.get("/retrieval/benchmark/recent", response_model=None)
def retrieval_benchmark_recent() -> dict[str, Any]:
    """Return the most recent retrieval benchmark result."""
    return get_recent_benchmark()


@router.get("/retrieval/benchmark/integrity", response_model=None)
def retrieval_benchmark_integrity() -> dict[str, Any]:
    """Return retrieval benchmark baseline integrity status."""
    return get_retrieval_benchmark_integrity()


@router.get("/ops/diagnostics", response_model=None)
def ops_diagnostics() -> dict[str, Any]:
    """Return the latest deploy/backup/restore/upgrade summary."""
    return get_ops_diagnostics()


@router.get("/answer/live-smoke", response_model=None)
def answer_live_smoke() -> dict[str, Any]:
    """Return the latest answer live smoke diagnostics for Web Console display."""
    return get_answer_live_smoke()


@router.get("/advanced-parser-corpus", response_model=None)
def advanced_parser_corpus() -> dict[str, Any]:
    """Return the latest advanced parser corpus status for Web Console display."""
    return get_advanced_parser_corpus()
