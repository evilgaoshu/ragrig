from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.acl import AuditEventType
from ragrig.db.models import AuditEvent

_FORBIDDEN_KEYS = {
    "answer_prompt",
    "chunk_text",
    "extracted_text",
    "full_prompt",
    "messages",
    "password",
    "prompt",
    "raw_prompt",
    "raw_secret",
    "secret",
    "text",
    "token",
}


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        key_text = str(key)
        if key_text.lower() in _FORBIDDEN_KEYS:
            safe[key_text] = "[REDACTED]"
        elif isinstance(value, dict):
            safe[key_text] = _safe_payload(value)
        elif isinstance(value, list):
            safe[key_text] = [
                _safe_payload(item) if isinstance(item, dict) else item for item in value[:50]
            ]
        elif isinstance(value, str) and len(value) > 240:
            safe[key_text] = value[:237] + "..."
        else:
            safe[key_text] = value
    return safe


def create_audit_event(
    session: Session,
    *,
    event_type: AuditEventType,
    actor: str | None = None,
    workspace_id=None,
    knowledge_base_id=None,
    document_id=None,
    chunk_id=None,
    run_id=None,
    item_id=None,
    payload_json: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        event_type=event_type,
        actor=actor,
        workspace_id=workspace_id,
        knowledge_base_id=knowledge_base_id,
        document_id=document_id,
        chunk_id=chunk_id,
        run_id=run_id,
        item_id=item_id,
        payload_json=_safe_payload(payload_json or {}),
    )
    session.add(event)
    session.flush()
    return event


def list_audit_events(
    session: Session,
    *,
    workspace_id=None,
    event_type: AuditEventType | None = None,
    actor: str | None = None,
    since: Any | None = None,
    until: Any | None = None,
    limit: int = 100,
    offset: int = 0,
    run_id: str | None = None,
    item_id: str | None = None,
) -> list[AuditEvent]:
    statement = select(AuditEvent).order_by(AuditEvent.occurred_at.desc())
    if workspace_id is not None:
        statement = statement.where(AuditEvent.workspace_id == workspace_id)
    if event_type is not None:
        statement = statement.where(AuditEvent.event_type == event_type)
    if actor is not None:
        statement = statement.where(AuditEvent.actor == actor)
    if since is not None:
        statement = statement.where(AuditEvent.occurred_at >= since)
    if until is not None:
        statement = statement.where(AuditEvent.occurred_at <= until)
    if run_id is not None:
        statement = statement.where(AuditEvent.run_id == run_id)
    if item_id is not None:
        statement = statement.where(AuditEvent.item_id == item_id)
    statement = statement.offset(offset).limit(limit)
    return list(session.scalars(statement))


__all__ = ["create_audit_event", "list_audit_events"]
