"""Knowledge base website import and upload routes."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ragrig.config import Settings, get_settings
from ragrig.db.session import get_session
from ragrig.deps import AuthContext, require_write_auth
from ragrig.ingestion.web_import import WebsiteImportError
from ragrig.local_pilot import import_website_pages
from ragrig.ratelimit import RateLimiter
from ragrig.repositories import get_knowledge_base_by_name
from ragrig.routers.runtime import (
    SessionFactory,
    get_rate_limiter,
    get_session_factory,
    get_task_executor,
    get_workspace_id,
    knowledge_base_access_error,
)
from ragrig.tasks import (
    cleanup_staging_dir,
    create_upload_pipeline_run,
    enqueue_task,
    run_upload_pipeline,
    validate_and_stage_uploads,
)

router = APIRouter(tags=["knowledge-ingest"])


class WebsiteImportRequest(BaseModel):
    urls: list[str]
    sitemap_url: str | None = None
    bearer_token: str | None = None
    cookies: dict[str, str] | None = None
    basic_auth_username: str | None = None
    basic_auth_password: str | None = None


@router.post("/knowledge-bases/{kb_name}/website-import", response_model=None)
def knowledge_base_website_import(
    kb_name: str,
    request: WebsiteImportRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
) -> JSONResponse:
    kb = get_knowledge_base_by_name(session, kb_name, workspace_id=workspace_id)
    if kb is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"knowledge base '{kb_name}' not found"},
        )
    access_error = knowledge_base_access_error(
        settings=settings,
        session=session,
        auth=auth,
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


@router.post("/knowledge-bases/{kb_name}/upload", response_model=None)
async def knowledge_base_upload(
    kb_name: str,
    session: Annotated[Session, Depends(get_session)],
    files: Annotated[list[UploadFile], File(...)],
    settings: Annotated[Settings, Depends(get_settings)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    rate_limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    session_factory: Annotated[SessionFactory, Depends(get_session_factory)],
    task_executor: Annotated[Any, Depends(get_task_executor)],
) -> JSONResponse:
    rate_limiter.check_ingest(str(workspace_id))
    kb = get_knowledge_base_by_name(session, kb_name, workspace_id=workspace_id)
    if kb is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"knowledge base '{kb_name}' not found"},
        )
    access_error = knowledge_base_access_error(
        settings=settings,
        session=session,
        auth=auth,
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
        session_factory=session_factory,
        task_executor=task_executor,
        task_type="knowledge_base_upload",
        payload_json={
            "knowledge_base": kb_name,
            "workspace_id": str(workspace_id),
            "pipeline_run_id": pipeline_run_id,
            "staged_files": accepted.staged_files,
        },
        runner=lambda: run_upload_pipeline(
            session_factory=session_factory,
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
