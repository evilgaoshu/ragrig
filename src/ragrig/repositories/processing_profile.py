from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.db.models import ProcessingProfileAuditLog, ProcessingProfileOverride

SENSITIVE_FIELDS = {
    "api_key",
    "access_key",
    "secret",
    "session_token",
    "token",
    "password",
    "private_key",
    "credential",
    "dsn",
    "service_account",
}


def _sanitize_state(state: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive fields from a state dict for audit logging."""
    sanitized: dict[str, Any] = {}
    for key, value in state.items():
        if any(part in key.lower() for part in SENSITIVE_FIELDS):
            sanitized[key] = "[REDACTED]"
        elif key == "metadata_json" and isinstance(value, dict):
            sanitized[key] = _sanitize_metadata_json(value)
        else:
            sanitized[key] = value
    return sanitized


def _sanitize_metadata_json(metadata: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        if any(part in key.lower() for part in SENSITIVE_FIELDS):
            sanitized[key] = "[REDACTED]"
        else:
            sanitized[key] = value
    return sanitized


def _override_to_state(override: ProcessingProfileOverride) -> dict[str, Any]:
    return {
        "profile_id": override.profile_id,
        "extension": override.extension,
        "task_type": override.task_type,
        "display_name": override.display_name,
        "description": override.description,
        "provider": override.provider,
        "model_id": override.model_id,
        "status": override.status,
        "kind": override.kind,
        "tags": override.tags,
        "metadata_json": override.metadata_json,
        "created_by": override.created_by,
        "deleted_at": override.deleted_at.isoformat() if override.deleted_at else None,
        "created_at": override.created_at.isoformat() if override.created_at else None,
        "updated_at": override.updated_at.isoformat() if override.updated_at else None,
    }


def _write_audit_log(
    session: Session,
    *,
    profile_id: str,
    action: str,
    actor: str | None,
    old_state: dict[str, Any] | None,
    new_state: dict[str, Any] | None,
) -> None:
    entry = ProcessingProfileAuditLog(
        profile_id=profile_id,
        action=action,
        actor=actor,
        timestamp=datetime.now(timezone.utc),
        old_state=_sanitize_state(old_state) if old_state else None,
        new_state=_sanitize_state(new_state) if new_state else None,
    )
    session.add(entry)
    session.flush()


def get_active_overrides(session: Session) -> list[ProcessingProfileOverride]:
    return list(
        session.scalars(
            select(ProcessingProfileOverride).where(
                ProcessingProfileOverride.deleted_at.is_(None),
                ProcessingProfileOverride.status != "disabled",
            )
        )
    )


def get_all_overrides(session: Session) -> list[ProcessingProfileOverride]:
    return list(
        session.scalars(
            select(ProcessingProfileOverride).where(ProcessingProfileOverride.deleted_at.is_(None))
        )
    )


def get_override_by_id(session: Session, profile_id: str) -> ProcessingProfileOverride | None:
    return session.scalar(
        select(ProcessingProfileOverride).where(
            ProcessingProfileOverride.profile_id == profile_id,
            ProcessingProfileOverride.deleted_at.is_(None),
        )
    )


def find_conflicting_override(
    session: Session, extension: str, task_type: str
) -> ProcessingProfileOverride | None:
    """Return an active, non-deleted override for the given extension/task_type pair."""
    return session.scalar(
        select(ProcessingProfileOverride).where(
            ProcessingProfileOverride.extension == extension,
            ProcessingProfileOverride.task_type == task_type,
            ProcessingProfileOverride.deleted_at.is_(None),
            ProcessingProfileOverride.status != "disabled",
        )
    )


def create_override_in_db(
    session: Session,
    *,
    profile_id: str,
    extension: str,
    task_type: str,
    display_name: str,
    description: str,
    provider: str,
    model_id: str | None = None,
    kind: str = "deterministic",
    tags: list[str] | None = None,
    metadata_json: dict[str, Any] | None = None,
    status: str = "active",
    created_by: str | None = None,
) -> ProcessingProfileOverride:
    """Create an override row and write an audit log entry."""
    existing = get_override_by_id(session, profile_id)
    if existing is not None:
        raise ValueError(f"override profile '{profile_id}' already exists")

    conflicting = find_conflicting_override(session, extension, task_type)
    if conflicting is not None:
        raise ValueError(
            f"an active override for extension '{extension}' and task_type"
            f" '{task_type}' already exists (profile_id: '{conflicting.profile_id}')"
        )

    override = ProcessingProfileOverride(
        profile_id=profile_id,
        extension=extension,
        task_type=task_type,
        display_name=display_name,
        description=description,
        provider=provider,
        model_id=model_id,
        kind=kind,
        tags=tags or [],
        metadata_json=metadata_json or {},
        status=status,
        created_by=created_by,
    )
    session.add(override)
    session.flush()

    _write_audit_log(
        session,
        profile_id=profile_id,
        action="create",
        actor=created_by,
        old_state=None,
        new_state=_override_to_state(override),
    )
    return override


def update_override_in_db(
    session: Session,
    profile_id: str,
    *,
    status: str | None = None,
    display_name: str | None = None,
    description: str | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    kind: str | None = None,
    tags: list[str] | None = None,
    metadata_json: dict[str, Any] | None = None,
    actor: str | None = None,
) -> ProcessingProfileOverride:
    """Update an override row and write an audit log entry."""
    override = get_override_by_id(session, profile_id)
    if override is None:
        raise ValueError(f"override profile '{profile_id}' not found")

    old_state = _override_to_state(override)

    if status is not None:
        override.status = status
    if display_name is not None:
        override.display_name = display_name
    if description is not None:
        override.description = description
    if provider is not None:
        override.provider = provider
    if model_id is not None:
        override.model_id = model_id
    if kind is not None:
        override.kind = kind
    if tags is not None:
        override.tags = tags
    if metadata_json is not None:
        override.metadata_json = metadata_json

    session.flush()

    _write_audit_log(
        session,
        profile_id=profile_id,
        action="update",
        actor=actor,
        old_state=old_state,
        new_state=_override_to_state(override),
    )
    return override


def delete_override_in_db(
    session: Session,
    profile_id: str,
    *,
    actor: str | None = None,
    soft: bool = True,
) -> bool:
    """Delete or soft-delete an override and write an audit log entry."""
    override = get_override_by_id(session, profile_id)
    if override is None:
        return False

    old_state = _override_to_state(override)

    if soft:
        override.deleted_at = datetime.now(timezone.utc)
    else:
        session.delete(override)

    session.flush()

    new_state = None if not soft else _override_to_state(override)
    _write_audit_log(
        session,
        profile_id=profile_id,
        action="delete",
        actor=actor,
        old_state=old_state,
        new_state=new_state,
    )
    return True


def list_audit_log(
    session: Session,
    *,
    limit: int = 50,
    profile_id: str | None = None,
    action: str | None = None,
    provider: str | None = None,
) -> list[dict[str, Any]]:
    """Return recent audit log entries, optionally filtered."""
    stmt = select(ProcessingProfileAuditLog).order_by(ProcessingProfileAuditLog.timestamp.desc())
    if profile_id:
        stmt = stmt.where(ProcessingProfileAuditLog.profile_id == profile_id)
    if action:
        stmt = stmt.where(ProcessingProfileAuditLog.action == action)
    stmt = stmt.limit(limit)

    entries = list(session.scalars(stmt))
    result: list[dict[str, Any]] = []

    for entry in entries:
        item = {
            "id": str(entry.id),
            "profile_id": entry.profile_id,
            "action": entry.action,
            "actor": entry.actor,
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
            "old_state": entry.old_state,
            "new_state": entry.new_state,
        }
        if provider and item.get("new_state", {}).get("provider") != provider:
            continue
        result.append(item)

    return result
