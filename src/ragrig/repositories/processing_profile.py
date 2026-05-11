from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.db.models import ProcessingProfileAuditLog, ProcessingProfileOverride
from ragrig.processing_profile.sanitizer import (
    REDACTED as _sanitizer_REDACTED,
)
from ragrig.processing_profile.sanitizer import (
    SanitizationSummary as _SanitizationSummary,
)
from ragrig.processing_profile.sanitizer import (
    is_sensitive_key as _shared_is_sensitive_key,
)
from ragrig.processing_profile.sanitizer import (
    is_sensitive_value as _shared_is_sensitive_value,
)
from ragrig.processing_profile.sanitizer import (
    redact_metadata as _shared_redact_metadata,
)
from ragrig.processing_profile.sanitizer import (
    redact_state as _shared_redact_state,
)

# ── Backward-compatible re-exports and wrappers ──
# All logic lives in ragrig.processing_profile.sanitizer (single source of truth).

SENSITIVE_KEY_PARTS = {
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

# Legacy alias for backward compatibility.
SENSITIVE_FIELDS = SENSITIVE_KEY_PARTS

REDACTED = _sanitizer_REDACTED  # re-export from shared module


def _is_sensitive_key(key: str) -> bool:
    """Check whether a key looks like a sensitive field name.

    Thin wrapper around the shared helper in ``processing_profile.sanitizer``.
    """
    return _shared_is_sensitive_key(key)


def _is_sensitive_value(value: object) -> bool:
    """Check whether a scalar value looks like a secret (Bearer token, PEM, etc.).

    Thin wrapper around the shared helper in ``processing_profile.sanitizer``.
    """
    return _shared_is_sensitive_value(value)


def _sanitize_metadata_json(
    metadata: dict[str, Any],
    prefix: str = "metadata_json",
) -> tuple[dict[str, Any], int, list[str], _SanitizationSummary]:
    """Recursively redact sensitive fields from a metadata dict.

    Thin wrapper around the shared ``redact_metadata`` helper.
    """
    return _shared_redact_metadata(metadata, prefix=prefix)


def _sanitize_state(state: dict[str, Any]) -> dict[str, Any]:
    """Redact sensitive fields from a state dict for audit logging.

    Thin wrapper around the shared ``redact_state`` helper.
    """
    return _shared_redact_state(state)


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


def get_audit_entry_by_id(session: Session, audit_id: str) -> ProcessingProfileAuditLog | None:
    """Fetch a single audit log entry by its UUID."""
    try:
        entry_uuid = uuid.UUID(audit_id)
    except (ValueError, AttributeError):
        return None
    return session.scalar(
        select(ProcessingProfileAuditLog).where(ProcessingProfileAuditLog.id == entry_uuid)
    )


def compute_diff(
    session: Session,
    *,
    profile_id: str,
    status: str | None = None,
    display_name: str | None = None,
    description: str | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    kind: str | None = None,
    tags: list[str] | None = None,
    metadata_json: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Compute a diff between the current override state and proposed changes.

    Returns a dict with old (sanitized), new (sanitized), changed_paths,
    and redaction metadata.  Returns None if the override is not found.
    """
    override = get_override_by_id(session, profile_id)
    if override is None:
        return None

    old_state = _override_to_state(override)

    new_state = dict(old_state)
    if status is not None:
        new_state["status"] = status
    if display_name is not None:
        new_state["display_name"] = display_name
    if description is not None:
        new_state["description"] = description
    if provider is not None:
        new_state["provider"] = provider
    if model_id is not None:
        new_state["model_id"] = model_id
    if kind is not None:
        new_state["kind"] = kind
    if tags is not None:
        new_state["tags"] = tags
    if metadata_json is not None:
        new_state["metadata_json"] = metadata_json

    changed_paths = _compute_changed_paths(old_state, new_state)

    # Sanitize both states, collecting redaction info from old.
    old_sanitized = _sanitize_state(old_state)
    new_sanitized = _sanitize_state(new_state)
    redaction_meta = old_sanitized.pop("_redaction", None) or new_sanitized.pop("_redaction", None)

    result: dict[str, Any] = {
        "old": old_sanitized,
        "new": new_sanitized,
        "changed_paths": changed_paths,
    }
    if redaction_meta:
        result["redaction_count"] = redaction_meta["count"]
        result["redacted_paths"] = redaction_meta["paths"]

    return result


def _compute_changed_paths(old_state: dict[str, Any], new_state: dict[str, Any]) -> list[str]:
    """Compute the list of keys (including nested dot-paths) that differ.

    Order is stable: sorted alphabetically.
    """
    changed: list[str] = []
    _compute_changed_paths_recursive(old_state, new_state, "", changed)
    return sorted(changed)


def _compute_changed_paths_recursive(
    old_obj: object,
    new_obj: object,
    prefix: str,
    changed: list[str],
) -> None:
    if isinstance(old_obj, dict) and isinstance(new_obj, dict):
        all_keys = set(old_obj.keys()) | set(new_obj.keys())
        for key in sorted(all_keys):
            path = f"{prefix}.{key}" if prefix else key
            old_val = old_obj.get(key)
            new_val = new_obj.get(key)
            if isinstance(old_val, (dict, list)) or isinstance(new_val, (dict, list)):
                _compute_changed_paths_recursive(old_val, new_val, path, changed)
            elif old_val != new_val:
                changed.append(path)
    elif isinstance(old_obj, list) and isinstance(new_obj, list):
        if len(old_obj) != len(new_obj):
            changed.append(prefix)
            return
        for idx in range(len(old_obj)):
            path = f"{prefix}[{idx}]"
            _compute_changed_paths_recursive(old_obj[idx], new_obj[idx], path, changed)
    elif old_obj != new_obj:
        if prefix:
            changed.append(prefix)


def rollback_override(
    session: Session,
    *,
    audit_id: str,
    actor: str | None = None,
) -> ProcessingProfileOverride:
    """Rollback an override to the state recorded in an audit log entry.

    Returns the updated override.
    Raises ValueError for: audit entry not found, profile deleted, profile disabled,
    or the audit entry has no usable state.
    """
    audit_entry = get_audit_entry_by_id(session, audit_id)
    if audit_entry is None:
        raise ValueError(f"audit entry '{audit_id}' not found")

    override = session.scalar(
        select(ProcessingProfileOverride).where(
            ProcessingProfileOverride.profile_id == audit_entry.profile_id
        )
    )
    if override is None:
        raise ValueError(
            f"target override profile '{audit_entry.profile_id}' not found "
            f"(may have been hard-deleted)"
        )

    if override.deleted_at is not None:
        raise ValueError(f"target override profile '{audit_entry.profile_id}' is deleted")

    if override.status == "disabled":
        raise ValueError(
            f"target override profile '{audit_entry.profile_id}' is disabled; "
            f"re-enable it before rollback"
        )

    old_state_for_audit = _override_to_state(override)

    rollback_state = audit_entry.old_state or audit_entry.new_state
    if rollback_state is None:
        raise ValueError(
            f"audit entry '{audit_id}' has no restorable state "
            f"(both old_state and new_state are null)"
        )

    rollback_state = {k: v for k, v in rollback_state.items() if k != "profile_id"}

    if "display_name" in rollback_state:
        override.display_name = rollback_state["display_name"]
    if "description" in rollback_state:
        override.description = rollback_state["description"]
    if "provider" in rollback_state:
        override.provider = rollback_state["provider"]
    if "model_id" in rollback_state:
        override.model_id = rollback_state["model_id"]
    if "status" in rollback_state:
        override.status = rollback_state["status"]
    if "kind" in rollback_state:
        override.kind = rollback_state["kind"]
    if "tags" in rollback_state:
        override.tags = rollback_state["tags"]
    if "metadata_json" in rollback_state:
        override.metadata_json = rollback_state["metadata_json"]

    session.flush()

    _write_rollback_audit_log(
        session,
        profile_id=override.profile_id,
        actor=actor,
        old_state=old_state_for_audit,
        new_state=_override_to_state(override),
        source_audit_id=audit_id,
    )

    return override


def _write_rollback_audit_log(
    session: Session,
    *,
    profile_id: str,
    actor: str | None,
    old_state: dict[str, Any],
    new_state: dict[str, Any],
    source_audit_id: str,
) -> None:
    entry = ProcessingProfileAuditLog(
        profile_id=profile_id,
        action="rollback",
        actor=actor,
        timestamp=datetime.now(timezone.utc),
        old_state=_sanitize_state(old_state),
        new_state=_sanitize_state(new_state),
    )
    # Store source_audit_id in a generic metadata-like field.
    # The audit log table has no dedicated source_audit_id column,
    # so we embed it as a key in new_state.
    if entry.new_state is not None:
        entry.new_state["source_audit_id"] = source_audit_id
    session.add(entry)
    session.flush()


def list_audit_log(
    session: Session,
    *,
    limit: int = 50,
    profile_id: str | None = None,
    action: str | None = None,
    provider: str | None = None,
    task_type: str | None = None,
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
        new_state = item.get("new_state") or {}
        if provider and new_state.get("provider") != provider:
            continue
        if task_type and new_state.get("task_type") != task_type:
            continue
        result.append(item)

    return result
