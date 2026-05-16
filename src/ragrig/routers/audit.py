"""Audit log query API.

Requires admin-or-above role. All events are scoped to the caller's workspace.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ragrig.db.session import get_session
from ragrig.deps import AuthContext, require_admin_auth
from ragrig.repositories.audit import list_audit_events

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEventResponse(BaseModel):
    id: str
    event_type: str
    actor: str | None
    workspace_id: str | None
    knowledge_base_id: str | None
    document_id: str | None
    chunk_id: str | None
    run_id: str | None
    item_id: str | None
    occurred_at: str
    payload: dict[str, Any]


@router.get("/events", response_model=list[AuditEventResponse])
def get_audit_events(
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_admin_auth)],
    event_type: Annotated[str | None, Query(description="Filter by event type")] = None,
    actor: Annotated[str | None, Query(description="Filter by actor subject")] = None,
    since: Annotated[datetime | None, Query(description="Earliest occurred_at (ISO 8601)")] = None,
    until: Annotated[datetime | None, Query(description="Latest occurred_at (ISO 8601)")] = None,
    run_id: Annotated[UUID | None, Query(description="Filter by pipeline run ID")] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Page size")] = 100,
    offset: Annotated[int, Query(ge=0, description="Page offset")] = 0,
) -> list[AuditEventResponse]:
    """Return audit events scoped to the caller's workspace.

    Results are ordered newest-first. Use *since*, *until*, *offset*, and *limit*
    for pagination and time-range queries.
    """
    events = list_audit_events(
        session,
        workspace_id=auth.workspace_id,
        event_type=event_type,  # type: ignore[arg-type]
        actor=actor,
        since=since,
        until=until,
        run_id=str(run_id) if run_id else None,
        limit=limit,
        offset=offset,
    )
    return [
        AuditEventResponse(
            id=str(e.id),
            event_type=e.event_type,
            actor=e.actor,
            workspace_id=str(e.workspace_id) if e.workspace_id else None,
            knowledge_base_id=str(e.knowledge_base_id) if e.knowledge_base_id else None,
            document_id=str(e.document_id) if e.document_id else None,
            chunk_id=str(e.chunk_id) if e.chunk_id else None,
            run_id=str(e.run_id) if e.run_id else None,
            item_id=str(e.item_id) if e.item_id else None,
            occurred_at=e.occurred_at.isoformat(),
            payload=e.payload_json,
        )
        for e in events
    ]
