"""Retention management API endpoints.

POST /admin/retention/run
    Run the global retention sweep (KB version purge + audit event TTL).
    Requires admin or owner role.

PATCH /knowledge-bases/{kb_name}/retention
    Set or clear the per-KB document-version retention policy.
    Requires admin or owner role.

GET /knowledge-bases/{kb_name}/retention
    Show the current retention policy for a KB.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.config import Settings, get_settings
from ragrig.db.models import KnowledgeBase
from ragrig.db.session import get_session
from ragrig.deps import AuthContext, require_admin_auth
from ragrig.retention import run_all_retention

router = APIRouter(tags=["retention"])


class RetentionPolicyRequest(BaseModel):
    retention_days: int | None = Field(
        default=None,
        ge=1,
        description="Days to retain old document versions. null clears the policy.",
    )


class RetentionPolicyResponse(BaseModel):
    knowledge_base: str
    retention_days: int | None


@router.post("/admin/retention/run", status_code=status.HTTP_200_OK)
def run_retention(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> dict[str, Any]:
    """Trigger a full retention sweep. Requires admin or owner."""
    result = run_all_retention(session, settings)
    return result


@router.patch(
    "/knowledge-bases/{kb_name}/retention",
    response_model=RetentionPolicyResponse,
)
def set_kb_retention(
    kb_name: str,
    body: RetentionPolicyRequest,
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> RetentionPolicyResponse:
    """Set or clear the document-version retention policy for a knowledge base."""
    kb = session.scalar(
        select(KnowledgeBase)
        .where(KnowledgeBase.name == kb_name)
        .where(KnowledgeBase.workspace_id == _auth.workspace_id)
        .limit(1)
    )
    if kb is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"knowledge base '{kb_name}' not found",
        )
    kb.retention_days = body.retention_days
    session.add(kb)
    session.commit()
    return RetentionPolicyResponse(
        knowledge_base=kb_name,
        retention_days=kb.retention_days,
    )


@router.get(
    "/knowledge-bases/{kb_name}/retention",
    response_model=RetentionPolicyResponse,
)
def get_kb_retention(
    kb_name: str,
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> RetentionPolicyResponse:
    """Return the current retention policy for a knowledge base."""
    kb = session.scalar(
        select(KnowledgeBase)
        .where(KnowledgeBase.name == kb_name)
        .where(KnowledgeBase.workspace_id == _auth.workspace_id)
        .limit(1)
    )
    if kb is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"knowledge base '{kb_name}' not found",
        )
    return RetentionPolicyResponse(
        knowledge_base=kb_name,
        retention_days=kb.retention_days,
    )
