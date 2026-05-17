"""Workspace backup and restore.

A "simplified" backup for SMB deployments. Dumps configuration + history that
admins typically lose sleep over — workspaces, knowledge-base definitions,
source configs (including webhook secrets), conversation history, answer
feedback, budgets, and audit events — to a single JSON document.

Large derived data (document text, chunks, embeddings) is intentionally
excluded — those re-derive from sources via re-ingestion. This keeps backups
small, human-readable, and version-control friendly.

Round-trip guarantees:

- IDs (UUIDs) are preserved so foreign keys remain consistent across systems.
- API key ``secret_hash`` is included; the *secret* itself was never stored.
- Restore is **upsert by id** — running it twice with the same payload is a
  no-op; running it against a different workspace creates a fresh copy.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.db.models import (
    AnswerFeedback,
    ApiKey,
    AuditEvent,
    Conversation,
    ConversationTurn,
    KnowledgeBase,
    Source,
    Workspace,
)

# UsageEvent / Budget land in P3c; import lazily so this module loads even
# before that migration ships.
try:
    from ragrig.db.models import Budget, UsageEvent  # type: ignore
except ImportError:  # pragma: no cover - depends on merge order
    Budget = None  # type: ignore
    UsageEvent = None  # type: ignore

BACKUP_SCHEMA_VERSION = 1


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _row_to_dict(row: Any, *, exclude: tuple[str, ...] = ()) -> dict[str, Any]:
    columns = row.__table__.columns
    return {
        col.name: _serialize(getattr(row, col.name)) for col in columns if col.name not in exclude
    }


def dump_workspace(session: Session, *, workspace_id: uuid.UUID) -> dict[str, Any]:
    """Capture a workspace and its dependent rows as a JSON-serializable dict.

    Raises ``ValueError`` if the workspace does not exist.
    """
    workspace = session.get(Workspace, workspace_id)
    if workspace is None:
        raise ValueError(f"workspace {workspace_id} not found")

    knowledge_bases = list(
        session.scalars(select(KnowledgeBase).where(KnowledgeBase.workspace_id == workspace_id))
    )
    kb_ids = [kb.id for kb in knowledge_bases]

    sources: list[Source] = []
    if kb_ids:
        sources = list(session.scalars(select(Source).where(Source.knowledge_base_id.in_(kb_ids))))

    conversations = list(
        session.scalars(select(Conversation).where(Conversation.workspace_id == workspace_id))
    )
    conv_ids = [c.id for c in conversations]
    turns: list[ConversationTurn] = []
    if conv_ids:
        turns = list(
            session.scalars(
                select(ConversationTurn).where(ConversationTurn.conversation_id.in_(conv_ids))
            )
        )

    feedback = list(
        session.scalars(select(AnswerFeedback).where(AnswerFeedback.workspace_id == workspace_id))
    )
    budgets: list[Any] = []
    usage: list[Any] = []
    if Budget is not None:
        budgets = list(session.scalars(select(Budget).where(Budget.workspace_id == workspace_id)))
    if UsageEvent is not None:
        usage = list(
            session.scalars(select(UsageEvent).where(UsageEvent.workspace_id == workspace_id))
        )
    api_keys = list(session.scalars(select(ApiKey).where(ApiKey.workspace_id == workspace_id)))
    audit = list(session.scalars(select(AuditEvent).where(AuditEvent.workspace_id == workspace_id)))

    return {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "exported_at": datetime.now(UTC).isoformat(),
        "workspace": _row_to_dict(workspace),
        "knowledge_bases": [_row_to_dict(kb) for kb in knowledge_bases],
        "sources": [_row_to_dict(s) for s in sources],
        "conversations": [_row_to_dict(c) for c in conversations],
        "conversation_turns": [_row_to_dict(t) for t in turns],
        "answer_feedback": [_row_to_dict(f) for f in feedback],
        "budgets": [_row_to_dict(b) for b in budgets],
        "usage_events": [_row_to_dict(u) for u in usage],
        "api_keys": [_row_to_dict(k) for k in api_keys],
        "audit_events": [_row_to_dict(a) for a in audit],
    }


def _coerce_uuid(value: Any) -> uuid.UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).rstrip("Z")
    return datetime.fromisoformat(text)


def _apply_dict(target_cls, payload: dict[str, Any]) -> dict[str, Any]:
    """Coerce a serialized row dict into kwargs suitable for the model."""
    kwargs: dict[str, Any] = {}
    for col in target_cls.__table__.columns:
        if col.name not in payload:
            continue
        value = payload[col.name]
        type_str = str(col.type).upper()
        if "UUID" in type_str:
            kwargs[col.name] = _coerce_uuid(value)
        elif "TIMESTAMP" in type_str or "DATETIME" in type_str:
            kwargs[col.name] = _coerce_datetime(value)
        else:
            kwargs[col.name] = value
    return kwargs


def restore_workspace(session: Session, payload: dict[str, Any]) -> dict[str, int]:
    """Upsert workspace + dependents from a backup payload.

    Returns a counts summary. Existing rows (by id) are updated in place; new
    ids are inserted. Foreign-key dependencies are honored by insertion order.
    """
    schema = int(payload.get("schema_version") or 0)
    if schema != BACKUP_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported backup schema_version: {schema} (expected {BACKUP_SCHEMA_VERSION})"
        )

    counts = {
        "workspace": 0,
        "knowledge_bases": 0,
        "sources": 0,
        "conversations": 0,
        "conversation_turns": 0,
        "answer_feedback": 0,
        "budgets": 0,
        "usage_events": 0,
        "api_keys": 0,
        "audit_events": 0,
    }

    workspace_payload = payload.get("workspace")
    if not workspace_payload:
        raise ValueError("backup is missing workspace block")

    workspace_kwargs = _apply_dict(Workspace, workspace_payload)
    workspace_id = workspace_kwargs.get("id")
    existing_ws = session.get(Workspace, workspace_id) if workspace_id else None
    if existing_ws is None:
        session.add(Workspace(**workspace_kwargs))
    else:
        for key, value in workspace_kwargs.items():
            setattr(existing_ws, key, value)
    counts["workspace"] = 1

    def upsert_many(target_cls, rows, counter_key):
        for row_payload in rows or []:
            kwargs = _apply_dict(target_cls, row_payload)
            row_id = kwargs.get("id")
            existing = session.get(target_cls, row_id) if row_id else None
            if existing is None:
                session.add(target_cls(**kwargs))
            else:
                for key, value in kwargs.items():
                    setattr(existing, key, value)
            counts[counter_key] += 1
        session.flush()

    upsert_many(KnowledgeBase, payload.get("knowledge_bases"), "knowledge_bases")
    upsert_many(Source, payload.get("sources"), "sources")
    upsert_many(Conversation, payload.get("conversations"), "conversations")
    upsert_many(ConversationTurn, payload.get("conversation_turns"), "conversation_turns")
    upsert_many(AnswerFeedback, payload.get("answer_feedback"), "answer_feedback")
    if Budget is not None:
        upsert_many(Budget, payload.get("budgets"), "budgets")
    if UsageEvent is not None:
        upsert_many(UsageEvent, payload.get("usage_events"), "usage_events")
    upsert_many(ApiKey, payload.get("api_keys"), "api_keys")
    upsert_many(AuditEvent, payload.get("audit_events"), "audit_events")

    return counts
