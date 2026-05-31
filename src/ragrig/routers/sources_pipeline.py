"""Source configuration, source ingest, workflow audit, and pipeline retry routes."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ragrig.config import Settings, get_settings
from ragrig.db.session import get_session
from ragrig.deps import AuthContext, require_write_auth
from ragrig.observability import summarize_pipeline_cost_latency
from ragrig.repositories import get_knowledge_base_by_name, list_audit_events
from ragrig.routers.runtime import (
    get_session_factory,
    get_task_executor,
    get_workspace_id,
    redact_summary,
)
from ragrig.services.common import knowledge_base_access_error
from ragrig.tasks import (
    TaskRetryError,
    enqueue_task,
    get_task_payload,
    retry_task,
    run_ingestion_dag_task,
    run_source_ingest_task,
)
from ragrig.web_console import (
    dry_run_source,
    get_pipeline_run_detail,
    get_pipeline_run_item_detail,
    list_pipeline_run_items,
    list_pipeline_runs,
    list_sources,
    resume_pipeline_dag,
    retry_pipeline_run,
    retry_pipeline_run_item,
    save_source_config,
    validate_source_config,
)
from ragrig.workflows import IngestionDagRejected, create_ingestion_dag_run

router = APIRouter(tags=["sources", "pipeline"])


class SourceConfigValidateRequest(BaseModel):
    plugin_id: str
    config: dict[str, Any] = Field(default_factory=dict)
    knowledge_base: str = "default"


class SourceConfigSaveRequest(BaseModel):
    plugin_id: str
    config: dict[str, Any] = Field(default_factory=dict)
    knowledge_base: str = "default"
    operator: str | None = None


class SourceDryRunRequest(BaseModel):
    plugin_id: str
    config: dict[str, Any] = Field(default_factory=dict)


class SourceRunIngestRequest(BaseModel):
    plugin_id: str
    config: dict[str, Any] = Field(default_factory=dict)
    knowledge_base: str = "default"
    operator: str | None = None


class RetryRequest(BaseModel):
    operator: str | None = None
    new_snapshot: bool = False


class IngestionDagRequest(BaseModel):
    knowledge_base: str = "fixture-local"
    root_path: str
    include_patterns: list[str] | None = None
    exclude_patterns: list[str] | None = None
    max_file_size_bytes: int = Field(default=10 * 1024 * 1024, gt=0)
    failure_node: str | None = None


@router.get("/audit-events", response_model=None)
def workflow_audit_events(
    session: Annotated[Session, Depends(get_session)],
    limit: int = 50,
    event_type: str | None = None,
    run_id: str | None = None,
    item_id: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """List workflow audit events (source_save, dry_run, retry, resume)."""
    events = list_audit_events(
        session,
        event_type=event_type,
        limit=limit,
        run_id=run_id,
        item_id=item_id,
    )
    return {
        "entries": [
            {
                "id": str(event.id),
                "event_type": event.event_type,
                "actor": event.actor,
                "knowledge_base_id": (
                    str(event.knowledge_base_id) if event.knowledge_base_id else None
                ),
                "run_id": str(event.run_id) if event.run_id else None,
                "item_id": str(event.item_id) if event.item_id else None,
                "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
                "payload": redact_summary(event.payload_json),
            }
            for event in events
        ]
    }


@router.post("/sources/validate-config", response_model=None)
def source_validate_config(
    request: SourceConfigValidateRequest,
) -> dict[str, Any]:
    """Validate a source configuration draft with dependency/credential checks."""
    return validate_source_config(
        plugin_id=request.plugin_id,
        config=request.config,
    )


@router.post("/sources", response_model=None)
def source_save_config(
    request: SourceConfigSaveRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
) -> dict[str, Any] | JSONResponse:
    """Validate and save a source configuration."""
    try:
        existing_kb = get_knowledge_base_by_name(
            session,
            request.knowledge_base,
            workspace_id=workspace_id,
        )
        if existing_kb is not None:
            access_error = knowledge_base_access_error(
                settings=settings,
                session=session,
                auth=auth,
                knowledge_base_id=existing_kb.id,
                minimum="editor",
            )
            if access_error is not None:
                return access_error
        result = save_source_config(
            session,
            plugin_id=request.plugin_id,
            config=request.config,
            knowledge_base_name=request.knowledge_base,
            operator=request.operator,
            workspace_id=workspace_id,
        )
    except Exception as exc:
        return JSONResponse(
            status_code=400,
            content={"error": str(exc)},
        )
    return result


@router.post("/sources/dry-run", response_model=None)
def source_dry_run(
    request: SourceDryRunRequest,
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_write_auth)],
) -> dict[str, Any] | JSONResponse:
    """Dry-run ingestion scan for a source.

    Lists candidate files, skip reasons, and expected pipeline_run without
    writing document_versions/chunks/embeddings.
    """
    try:
        result = dry_run_source(
            session,
            plugin_id=request.plugin_id,
            config=request.config,
        )
    except Exception as exc:
        return JSONResponse(
            status_code=400,
            content={"error": str(exc)},
        )
    return result


@router.post("/sources/run-ingest", response_model=None)
def source_run_ingest(
    request: SourceRunIngestRequest,
    auth: Annotated[AuthContext, Depends(require_write_auth)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    session_factory: Annotated[Callable[[], Session], Depends(get_session_factory)],
    task_executor: Annotated[Any, Depends(get_task_executor)],
) -> dict[str, Any] | JSONResponse:
    """Enqueue source ingestion as a background task.

    Returns immediately with a task_id. Poll GET /tasks/{task_id} for status.
    """
    missing_refs = [
        f"{key}: env:{value.removeprefix('env:')} not set"
        for key, value in (request.config or {}).items()
        if isinstance(value, str)
        and value.startswith("env:")
        and not os.environ.get(value.removeprefix("env:"))
    ]
    if missing_refs:
        return JSONResponse(
            status_code=400,
            content={"error": f"unresolved env refs: {'; '.join(missing_refs)}"},
        )

    try:
        existing_kb = get_knowledge_base_by_name(
            session,
            request.knowledge_base,
            workspace_id=workspace_id,
        )
        if existing_kb is not None:
            access_error = knowledge_base_access_error(
                settings=settings,
                session=session,
                auth=auth,
                knowledge_base_id=existing_kb.id,
                minimum="editor",
            )
            if access_error is not None:
                return access_error
        task_id = enqueue_task(
            session_factory=session_factory,
            task_executor=task_executor,
            task_type="source_ingest",
            payload_json={
                "plugin_id": request.plugin_id,
                "knowledge_base": request.knowledge_base,
                "workspace_id": str(workspace_id),
                "config": request.config,
                "operator": request.operator,
            },
            runner=lambda: run_source_ingest_task(
                session_factory=session_factory,
                plugin_id=request.plugin_id,
                config=request.config,
                knowledge_base_name=request.knowledge_base,
                operator=request.operator,
                workspace_id=workspace_id,
            ),
        )
    except Exception as exc:
        return JSONResponse(
            status_code=400,
            content={"error": str(exc)},
        )
    return JSONResponse(status_code=202, content={"task_id": task_id, "status": "queued"})


@router.get("/sources", response_model=None)
def sources(
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
) -> dict[str, list[dict[str, Any]]]:
    return {"items": list_sources(session, workspace_id=workspace_id)}


@router.get("/pipeline-runs", response_model=None)
def pipeline_runs(
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
) -> dict[str, list[dict[str, Any]]]:
    return {"items": list_pipeline_runs(session, workspace_id=workspace_id)}


@router.get("/pipeline-runs/{pipeline_run_id}", response_model=None)
def pipeline_run_detail(
    pipeline_run_id: str,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
) -> dict[str, Any] | JSONResponse:
    detail = get_pipeline_run_detail(session, pipeline_run_id, workspace_id=workspace_id)
    if detail is None:
        return JSONResponse(status_code=404, content={"error": "pipeline_run_not_found"})
    return detail


@router.get("/pipeline-runs/{pipeline_run_id}/items", response_model=None)
def pipeline_run_items(
    pipeline_run_id: str,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
) -> dict[str, list[dict[str, Any]]]:
    return {
        "items": list_pipeline_run_items(
            session,
            pipeline_run_id,
            workspace_id=workspace_id,
        )
    }


@router.get("/observability/cost-latency", response_model=None)
def cost_latency_observability(
    session: Annotated[Session, Depends(get_session)],
    knowledge_base: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    bounded_limit = max(1, min(limit, 100))
    return summarize_pipeline_cost_latency(
        session,
        knowledge_base_name=knowledge_base,
        limit=bounded_limit,
    )


@router.get("/tasks/{task_id}", response_model=None)
def task_status(
    task_id: str,
    session_factory: Annotated[Callable[[], Session], Depends(get_session_factory)],
    include: str | None = None,
) -> dict[str, Any] | JSONResponse:
    include_values = {item.strip() for item in include.split(",")} if include else set()
    payload = get_task_payload(
        session_factory=session_factory,
        task_id=task_id,
        include_pipeline_run="pipeline_run" in include_values,
    )
    if payload is None:
        return JSONResponse(status_code=404, content={"error": "task_not_found"})
    return payload


@router.post("/tasks/{task_id}/retry", response_model=None)
def retry_task_status(
    task_id: str,
    _auth: Annotated[AuthContext, Depends(require_write_auth)],
    session_factory: Annotated[Callable[[], Session], Depends(get_session_factory)],
    task_executor: Annotated[Any, Depends(get_task_executor)],
) -> dict[str, Any] | JSONResponse:
    try:
        result = retry_task(
            session_factory=session_factory,
            task_executor=task_executor,
            task_id=task_id,
        )
    except TaskRetryError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": exc.code,
                "message": exc.message,
                "retryable": False,
            },
        )
    return JSONResponse(status_code=202, content=result)


@router.post("/pipeline-dags/ingestion", response_model=None)
def ingestion_dag_run(
    request: IngestionDagRequest,
    _auth: Annotated[AuthContext, Depends(require_write_auth)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    session_factory: Annotated[Callable[[], Session], Depends(get_session_factory)],
    task_executor: Annotated[Any, Depends(get_task_executor)],
) -> dict[str, Any] | JSONResponse:
    try:
        with session_factory() as session:
            run = create_ingestion_dag_run(
                session,
                knowledge_base_name=request.knowledge_base,
                workspace_id=workspace_id,
                root_path=Path(request.root_path),
                include_patterns=request.include_patterns,
                exclude_patterns=request.exclude_patterns,
                max_file_size_bytes=request.max_file_size_bytes,
                failure_node=request.failure_node,
            )
            pipeline_run_id = str(run.id)
        task_id = enqueue_task(
            session_factory=session_factory,
            task_executor=task_executor,
            task_type="pipeline_dag_ingestion",
            payload_json={
                **request.model_dump(),
                "workspace_id": str(workspace_id),
                "pipeline_run_id": pipeline_run_id,
            },
            runner=lambda: run_ingestion_dag_task(
                session_factory=session_factory,
                pipeline_run_id=pipeline_run_id,
            ),
        )
    except (ValueError, IngestionDagRejected) as exc:
        return JSONResponse(
            status_code=400,
            content={"status": "rejected", "degraded": True, "reason": str(exc)},
        )
    return JSONResponse(
        status_code=202,
        content={"task_id": task_id, "pipeline_run_id": pipeline_run_id},
    )


@router.get("/pipeline-run-items/{item_id}", response_model=None)
def pipeline_run_item_detail(
    item_id: str,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
) -> dict[str, Any] | JSONResponse:
    """Inspect a single pipeline run item."""
    detail = get_pipeline_run_item_detail(session, item_id, workspace_id=workspace_id)
    if detail is None:
        return JSONResponse(status_code=404, content={"error": "pipeline_run_item_not_found"})
    return detail


@router.post("/pipeline-run-items/{item_id}/retry", response_model=None)
def pipeline_run_item_retry(
    item_id: str,
    request: RetryRequest,
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_write_auth)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
) -> dict[str, Any] | JSONResponse:
    """Retry a single failed pipeline run item.

    Re-processes the failed document using the same run's config snapshot.
    Does not modify historical run data.
    """
    result = retry_pipeline_run_item(
        session,
        item_id=item_id,
        operator=request.operator,
        workspace_id=workspace_id,
    )
    if result is None:
        return JSONResponse(status_code=404, content={"error": "pipeline_run_item_not_found"})
    return result


@router.post("/pipeline-runs/{run_id}/retry", response_model=None)
def pipeline_run_retry(
    run_id: str,
    request: RetryRequest,
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_write_auth)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
) -> dict[str, Any] | JSONResponse:
    """Retry all failed items in a pipeline run.

    Reuses the same config snapshot by default. Set new_snapshot=True to create
    a new snapshot from current config.
    """
    result = retry_pipeline_run(
        session,
        run_id=run_id,
        operator=request.operator,
        new_snapshot=request.new_snapshot,
        workspace_id=workspace_id,
    )
    if result is None:
        return JSONResponse(status_code=404, content={"error": "pipeline_run_not_found"})
    return result


@router.post("/pipeline-runs/{run_id}/dag-resume", response_model=None)
def pipeline_dag_resume(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_write_auth)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
) -> dict[str, Any] | JSONResponse:
    result = resume_pipeline_dag(session, run_id=run_id, workspace_id=workspace_id)
    if result is None:
        return JSONResponse(status_code=404, content={"error": "ingestion_dag_not_found"})
    return result
