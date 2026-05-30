from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ragrig.api.schemas import (
    AgentAccessExportRequest,
    AzureBlobExportRequest,
    BackblazeB2ExportRequest,
    CloudflareR2ExportRequest,
    GcsExportRequest,
    ObjectStorageExportRequest,
    WebhookExportRequest,
)
from ragrig.config import Settings, get_settings
from ragrig.db.session import get_session
from ragrig.deps import AuthContext, require_write_auth
from ragrig.plugins.sinks.agent_access.connector import export_to_agent_endpoint
from ragrig.plugins.sinks.azure_blob.connector import export_to_azure_blob
from ragrig.plugins.sinks.backblaze_b2.connector import export_to_backblaze_b2
from ragrig.plugins.sinks.cloudflare_r2.connector import export_to_cloudflare_r2
from ragrig.plugins.sinks.gcs.connector import export_to_gcs
from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage
from ragrig.plugins.sinks.webhook.connector import export_to_webhook
from ragrig.routers.runtime import get_workspace_id
from ragrig.services.common import knowledge_base_role_error_by_name

router = APIRouter(tags=["sink-exports"])


def _sink_access_error(
    *,
    settings: Settings,
    session: Session,
    auth: AuthContext,
    kb_name: str,
    workspace_id: uuid.UUID,
) -> JSONResponse | None:
    return knowledge_base_role_error_by_name(
        settings=settings,
        session=session,
        auth=auth,
        kb_name=kb_name,
        workspace_id=workspace_id,
        minimum="editor",
    )


@router.post("/knowledge-bases/{kb_name}/sink-export/agent-access", response_model=None)
def knowledge_base_sink_agent_access(
    kb_name: str,
    request: AgentAccessExportRequest,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    access_error = _sink_access_error(
        settings=settings,
        session=session,
        auth=auth,
        kb_name=kb_name,
        workspace_id=workspace_id,
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


@router.post("/knowledge-bases/{kb_name}/sink-export/webhook", response_model=None)
def knowledge_base_sink_webhook(
    kb_name: str,
    request: WebhookExportRequest,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    access_error = _sink_access_error(
        settings=settings,
        session=session,
        auth=auth,
        kb_name=kb_name,
        workspace_id=workspace_id,
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


@router.post("/knowledge-bases/{kb_name}/sink-export/object-storage", response_model=None)
def knowledge_base_sink_object_storage(
    kb_name: str,
    request: ObjectStorageExportRequest,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    access_error = _sink_access_error(
        settings=settings,
        session=session,
        auth=auth,
        kb_name=kb_name,
        workspace_id=workspace_id,
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
        "use_path_style": request.use_path_style,
        "verify_tls": request.verify_tls,
    }
    if request.endpoint_url:
        config["endpoint_url"] = request.endpoint_url
    if request.access_key:
        config["access_key"] = request.access_key
    if request.secret_key:
        config["secret_key"] = request.secret_key
    if request.region:
        config["region"] = request.region
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


def _artifact_report_response(report) -> JSONResponse:
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


@router.post("/knowledge-bases/{kb_name}/sink-export/cloudflare-r2", response_model=None)
def knowledge_base_sink_cloudflare_r2(
    kb_name: str,
    request: CloudflareR2ExportRequest,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    access_error = _sink_access_error(
        settings=settings,
        session=session,
        auth=auth,
        kb_name=kb_name,
        workspace_id=workspace_id,
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
    return _artifact_report_response(report)


@router.post("/knowledge-bases/{kb_name}/sink-export/backblaze-b2", response_model=None)
def knowledge_base_sink_backblaze_b2(
    kb_name: str,
    request: BackblazeB2ExportRequest,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    access_error = _sink_access_error(
        settings=settings,
        session=session,
        auth=auth,
        kb_name=kb_name,
        workspace_id=workspace_id,
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
    return _artifact_report_response(report)


@router.post("/knowledge-bases/{kb_name}/sink-export/azure-blob", response_model=None)
def knowledge_base_sink_azure_blob(
    kb_name: str,
    request: AzureBlobExportRequest,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    access_error = _sink_access_error(
        settings=settings,
        session=session,
        auth=auth,
        kb_name=kb_name,
        workspace_id=workspace_id,
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
    return _artifact_report_response(report)


@router.post("/knowledge-bases/{kb_name}/sink-export/gcs", response_model=None)
def knowledge_base_sink_gcs(
    kb_name: str,
    request: GcsExportRequest,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> JSONResponse:
    access_error = _sink_access_error(
        settings=settings,
        session=session,
        auth=auth,
        kb_name=kb_name,
        workspace_id=workspace_id,
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
    return _artifact_report_response(report)
