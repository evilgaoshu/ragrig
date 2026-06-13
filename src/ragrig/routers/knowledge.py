"""Knowledge base, document, understanding, and knowledge graph routes."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ragrig.config import Settings, get_settings
from ragrig.db.session import get_session
from ragrig.deps import AuthContext, get_auth_context, require_admin_auth, require_write_auth
from ragrig.knowledge_base_config import (
    RetrievalPreferenceRequest,
    RoleModelConfigRequest,
    StageModelPolicyRequest,
)
from ragrig.knowledge_graph import (
    KnowledgeGraphBuildRequest,
)
from ragrig.routers.runtime import (
    get_workspace_id,
)
from ragrig.services import knowledge as knowledge_service
from ragrig.understanding import (
    UnderstandAllRequest,
    UnderstandingRequest,
    UnderstandingRunFilter,
)

router = APIRouter(tags=["knowledge"])


class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class KnowledgeGraphRelationFeedbackRequest(BaseModel):
    verdict: str = Field(pattern=r"^(incorrect|correct|needs_review)$")
    note: str | None = Field(default=None, max_length=500)


class KbPermissionRequest(BaseModel):
    role: str = Field(pattern=r"^(admin|editor|viewer|none)$")


@router.get("/knowledge-bases", response_model=None)
def knowledge_bases(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
) -> dict[str, list[dict[str, Any]]]:
    return knowledge_service.knowledge_bases(
        session,
        settings=settings,
        workspace_id=workspace_id,
    )


@router.post("/knowledge-bases", response_model=None)
def create_knowledge_base(
    request: KnowledgeBaseCreateRequest,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    _auth: Annotated[AuthContext, Depends(require_write_auth)],
) -> JSONResponse:
    content, status_code = knowledge_service.create_knowledge_base(
        session,
        name=request.name,
        workspace_id=workspace_id,
    )
    return JSONResponse(status_code=status_code, content=content)


@router.get("/knowledge-bases/{kb_name}/permissions", response_model=None)
def list_kb_permissions_endpoint(
    kb_name: str,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> JSONResponse:
    """List all per-KB permission overrides for a knowledge base."""
    return JSONResponse(
        status_code=200,
        content=knowledge_service.list_permissions(
            session,
            kb_name=kb_name,
            workspace_id=workspace_id,
        ),
    )


@router.put("/knowledge-bases/{kb_name}/permissions/{user_id}", response_model=None)
def set_kb_permission_endpoint(
    kb_name: str,
    user_id: str,
    request: KbPermissionRequest,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> JSONResponse:
    """Upsert a per-KB role override for a user."""
    return JSONResponse(
        status_code=200,
        content=knowledge_service.set_permission(
            session,
            kb_name=kb_name,
            user_id=user_id,
            role=request.role,
            workspace_id=workspace_id,
        ),
    )


@router.delete("/knowledge-bases/{kb_name}/permissions/{user_id}", response_model=None)
def delete_kb_permission_endpoint(
    kb_name: str,
    user_id: str,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> JSONResponse:
    """Remove the per-KB permission override for a user."""
    return JSONResponse(
        status_code=200,
        content=knowledge_service.delete_permission(
            session,
            kb_name=kb_name,
            user_id=user_id,
            workspace_id=workspace_id,
        ),
    )


@router.get("/documents", response_model=None)
def documents(
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
) -> dict[str, list[dict[str, Any]]]:
    return knowledge_service.documents(session, workspace_id=workspace_id)


@router.get("/understanding-runs", response_model=None)
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
    return knowledge_service.web_understanding_runs(
        session,
        knowledge_base_id=knowledge_base_id,
        limit=limit,
        provider=provider,
        model=model,
        profile_id=profile_id,
        status=status,
        started_after=started_after,
        started_before=started_before,
    )


@router.get("/understanding-runs/{run_id}", response_model=None)
def web_understanding_run_detail(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    return knowledge_service.understanding_run_detail(session, run_id)


@router.get("/understanding-runs/{run_id}/export", response_model=None)
def export_understanding_run_endpoint(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    return knowledge_service.export_understanding_run_payload(session, run_id)


@router.get("/knowledge-bases/{kb_id}/understanding-runs/export", response_model=None)
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
    return knowledge_service.export_understanding_runs_payload(
        session,
        kb_id=kb_id,
        filters=filters,
    )


@router.get("/understanding-runs/{run_id}/diff", response_model=None)
def diff_understanding_runs_endpoint(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
    against: str,
) -> dict[str, Any]:
    return knowledge_service.diff_understanding_runs(session, run_id=run_id, against=against)


@router.get("/document-versions/{document_version_id}/chunks", response_model=None)
def document_version_chunks(
    document_version_id: str,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
) -> dict[str, list[dict[str, Any]]]:
    return knowledge_service.document_version_chunks(
        session,
        document_version_id=document_version_id,
        workspace_id=workspace_id,
    )


@router.post("/document-versions/{document_version_id}/understand", response_model=None)
def understand_document_version(
    document_version_id: str,
    request: UnderstandingRequest,
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_write_auth)],
) -> dict[str, Any]:
    return knowledge_service.understand_document_version(
        session,
        document_version_id=document_version_id,
        request=request,
    )


@router.get("/document-versions/{document_version_id}/understanding", response_model=None)
def get_document_understanding(
    document_version_id: str,
    session: Annotated[Session, Depends(get_session)],
    allow_missing: bool = False,
) -> dict[str, Any]:
    return knowledge_service.get_document_understanding(
        session,
        document_version_id=document_version_id,
        allow_missing=allow_missing,
    )


@router.post("/knowledge-bases/{kb_id}/understand-all", response_model=None)
def understand_all(
    kb_id: str,
    request: UnderstandAllRequest,
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_write_auth)],
    x_operator: Annotated[str | None, Header()] = None,
) -> dict[str, Any]:
    return knowledge_service.understand_all(
        session,
        kb_id=kb_id,
        request=request,
        operator=x_operator,
    )


@router.get("/knowledge-bases/{kb_id}/understanding-coverage", response_model=None)
def understanding_coverage(
    kb_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    return knowledge_service.understanding_coverage(session, kb_id=kb_id)


@router.get("/knowledge-bases/{kb_id}/knowledge-map", response_model=None)
def knowledge_map(
    kb_id: str,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    profile_id: str = "*.understand.default",
) -> dict[str, Any]:
    return knowledge_service.knowledge_map(
        session,
        kb_id=kb_id,
        profile_id=profile_id,
        settings=settings,
        workspace_id=workspace_id,
        auth=auth,
    )


@router.get("/knowledge-bases/{kb_id}/knowledge-graph", response_model=None)
def knowledge_graph(
    kb_id: str,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict[str, Any]:
    return knowledge_service.knowledge_graph(
        session,
        kb_id=kb_id,
        settings=settings,
        workspace_id=workspace_id,
        auth=auth,
    )


@router.post("/knowledge-bases/{kb_id}/knowledge-graph/rebuild", response_model=None)
def rebuild_knowledge_graph_endpoint(
    kb_id: str,
    request: KnowledgeGraphBuildRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
) -> dict[str, Any]:
    return knowledge_service.rebuild_knowledge_graph_payload(
        session,
        kb_id=kb_id,
        request=request,
        settings=settings,
        workspace_id=workspace_id,
        auth=auth,
    )


@router.post(
    "/knowledge-bases/{kb_id}/knowledge-graph/relations/{relation_id}/feedback",
    response_model=None,
)
def submit_knowledge_graph_relation_feedback(
    kb_id: str,
    relation_id: str,
    request: KnowledgeGraphRelationFeedbackRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
) -> dict[str, Any]:
    return knowledge_service.submit_relation_feedback(
        session,
        kb_id=kb_id,
        relation_id=relation_id,
        verdict=request.verdict,
        note=request.note,
        settings=settings,
        workspace_id=workspace_id,
        auth=auth,
    )


@router.get("/knowledge-bases/{kb_id}/retrieval-preferences", response_model=None)
def get_retrieval_preferences(
    kb_id: str,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict[str, Any]:
    return knowledge_service.get_retrieval_preferences(
        session,
        kb_id=kb_id,
        settings=settings,
        workspace_id=workspace_id,
        auth=auth,
    )


@router.put("/knowledge-bases/{kb_id}/retrieval-preferences", response_model=None)
def put_retrieval_preferences(
    kb_id: str,
    request: RetrievalPreferenceRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
) -> dict[str, Any]:
    return knowledge_service.put_retrieval_preferences(
        session,
        kb_id=kb_id,
        request=request,
        settings=settings,
        workspace_id=workspace_id,
        auth=auth,
    )


@router.get("/knowledge-bases/{kb_id}/role-model-config", response_model=None)
def get_role_model_config(
    kb_id: str,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict[str, Any]:
    return knowledge_service.get_role_model_config(
        session,
        kb_id=kb_id,
        settings=settings,
        workspace_id=workspace_id,
        auth=auth,
    )


@router.put("/knowledge-bases/{kb_id}/role-model-config", response_model=None)
def put_role_model_config(
    kb_id: str,
    request: RoleModelConfigRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
) -> dict[str, Any]:
    return knowledge_service.put_role_model_config(
        session,
        kb_id=kb_id,
        request=request,
        settings=settings,
        workspace_id=workspace_id,
        auth=auth,
    )


@router.get("/knowledge-bases/{kb_id}/stage-model-policy", response_model=None)
def get_stage_model_policy(
    kb_id: str,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict[str, Any]:
    return knowledge_service.get_stage_model_policy(
        session,
        kb_id=kb_id,
        settings=settings,
        workspace_id=workspace_id,
        auth=auth,
    )


@router.put("/knowledge-bases/{kb_id}/stage-model-policy", response_model=None)
def put_stage_model_policy(
    kb_id: str,
    request: StageModelPolicyRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
) -> dict[str, Any]:
    return knowledge_service.put_stage_model_policy(
        session,
        kb_id=kb_id,
        request=request,
        settings=settings,
        workspace_id=workspace_id,
        auth=auth,
    )


@router.get("/knowledge-bases/{kb_id}/understanding-runs", response_model=None)
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
    return knowledge_service.understanding_runs(session, kb_id=kb_id, filters=filters)
