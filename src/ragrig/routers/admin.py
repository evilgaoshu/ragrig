"""Admin console endpoints: status snapshot + workspace backup/restore.

These are intentionally simple — they're the surface admin UIs and ops
scripts call. Larger ops actions (rotation, retention, evaluation) live in
their own routers.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ragrig.backup import dump_workspace, restore_workspace
from ragrig.db.models import (
    AnswerFeedback,
    AuditEvent,
    Conversation,
    KnowledgeBase,
    Source,
    Workspace,
)
from ragrig.db.session import get_session
from ragrig.deps import AuthContext, require_admin_auth

router = APIRouter(prefix="/admin", tags=["admin"])


class RestoreRequest(BaseModel):
    payload: dict[str, Any]


def _count(session: Session, model) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


@router.get("/status", response_model=None)
def admin_status(
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> dict[str, Any]:
    """High-signal counts for the admin console landing page."""
    counts = {
        "workspaces": _count(session, Workspace),
        "knowledge_bases": _count(session, KnowledgeBase),
        "sources": _count(session, Source),
        "conversations": _count(session, Conversation),
        "answer_feedback": _count(session, AnswerFeedback),
        "audit_events": _count(session, AuditEvent),
    }
    return {"counts": counts}


@router.get("/backup/{workspace_id}", response_model=None)
def admin_backup(
    workspace_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> dict[str, Any]:
    """Return a JSON dump of the workspace and its dependents.

    Clients save this as a ``.json`` file. Re-import via ``POST /admin/restore``.
    """
    try:
        return dump_workspace(session, workspace_id=workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/restore", response_model=None)
def admin_restore(
    body: RestoreRequest,
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> dict[str, Any]:
    """Upsert a previously exported workspace payload.

    Returns per-table row counts written. Existing rows are updated in place
    when their ids match — running restore twice is idempotent.
    """
    try:
        counts = restore_workspace(session, body.payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return {"status": "ok", "written": counts}
