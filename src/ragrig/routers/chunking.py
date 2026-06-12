from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ragrig.db.session import get_session
from ragrig.deps import AuthContext, require_write_auth
from ragrig.routers.runtime import get_workspace_id
from ragrig.services import chunking as chunking_service

router = APIRouter(tags=["chunking"])


class ChunkPreviewRequest(BaseModel):
    text: str | None = Field(default=None, max_length=2_000_000)
    document_version_id: str | None = None
    template_id: str = "char_window_v1"
    parameters: dict[str, Any] = Field(default_factory=dict)


class ChunkOverrideDraftRequest(BaseModel):
    char_start: int
    char_end: int
    split_reason: str
    heading: str | None = None
    source_block_type: str = "unknown"
    source_block_id: str | None = None
    section_id: str | None = None
    table_id: str | None = None
    parser_page_number: int | None = None


class ChunkOverrideSaveRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    template_id: str
    template_parameters: dict[str, Any] = Field(default_factory=dict)
    chunks: list[ChunkOverrideDraftRequest]
    operations: list[dict[str, Any]] = Field(min_length=1, max_length=100)


class ChunkOverrideResetRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    template_id: str = "char_window_v1"
    template_parameters: dict[str, Any] = Field(default_factory=dict)


def _actor(auth: AuthContext, operator: str | None) -> str | None:
    if operator:
        return operator
    if auth.user_id:
        return str(auth.user_id)
    return "local-owner" if auth.is_anonymous and auth.role == "owner" else "api-key"


@router.get("/chunking/templates", response_model=None)
def chunk_templates() -> dict[str, Any]:
    return chunking_service.list_templates()


@router.post("/chunking/preview", response_model=None)
def preview_chunks(
    request: ChunkPreviewRequest,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
) -> dict[str, Any]:
    return chunking_service.preview(
        session,
        workspace_id=workspace_id,
        text=request.text,
        document_version_id=request.document_version_id,
        template_id=request.template_id,
        parameters=request.parameters,
    )


@router.get("/document-versions/{document_version_id}/chunk-review", response_model=None)
def chunk_review(
    document_version_id: str,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
) -> dict[str, Any]:
    return chunking_service.review(
        session,
        workspace_id=workspace_id,
        document_version_id=document_version_id,
    )


@router.put("/document-versions/{document_version_id}/chunk-override", response_model=None)
def save_chunk_override(
    document_version_id: str,
    request: ChunkOverrideSaveRequest,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
    x_operator: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    return chunking_service.save_override(
        session,
        workspace_id=workspace_id,
        document_version_id=document_version_id,
        actor=_actor(auth, x_operator),
        reason=request.reason,
        template_id=request.template_id,
        template_parameters=request.template_parameters,
        drafts=[chunk.model_dump() for chunk in request.chunks],
        operations=request.operations,
    )


@router.post("/document-versions/{document_version_id}/chunk-override/reset", response_model=None)
def reset_chunk_override(
    document_version_id: str,
    request: ChunkOverrideResetRequest,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
    x_operator: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    return chunking_service.reset_override(
        session,
        workspace_id=workspace_id,
        document_version_id=document_version_id,
        actor=_actor(auth, x_operator),
        reason=request.reason,
        template_id=request.template_id,
        template_parameters=request.template_parameters,
    )


@router.post("/document-versions/{document_version_id}/chunk-override/reindex", response_model=None)
def reindex_chunk_override(
    document_version_id: str,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
    x_operator: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    return chunking_service.reindex_override(
        session,
        workspace_id=workspace_id,
        document_version_id=document_version_id,
        actor=_actor(auth, x_operator),
    )


__all__ = ["router"]
