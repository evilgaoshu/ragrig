from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ragrig.db.models import TaskRecord


def create_task_record(
    session: Session,
    *,
    task_type: str,
    payload_json: dict[str, Any],
    status: str = "pending",
    attempt_count: int = 0,
    previous_task_id: str | uuid.UUID | None = None,
    next_task_id: str | uuid.UUID | None = None,
    retry_idempotency_key: str | None = None,
) -> TaskRecord:
    resolved_previous_task_id = _optional_uuid(
        previous_task_id if previous_task_id is not None else payload_json.get("previous_task_id")
    )
    resolved_next_task_id = _optional_uuid(
        next_task_id if next_task_id is not None else payload_json.get("next_task_id")
    )
    task = TaskRecord(
        task_type=task_type,
        payload_json=payload_json,
        status=status,
        result_json=None,
        error=None,
        started_at=None,
        finished_at=None,
        progress=None,
        attempt_count=attempt_count,
        previous_task_id=resolved_previous_task_id,
        next_task_id=resolved_next_task_id,
        retry_idempotency_key=retry_idempotency_key or payload_json.get("retry_idempotency_key"),
    )
    session.add(task)
    session.flush()
    return task


def get_task_record(session: Session, task_id: str | uuid.UUID) -> TaskRecord | None:
    if isinstance(task_id, uuid.UUID):
        resolved = task_id
    else:
        try:
            resolved = uuid.UUID(str(task_id))
        except (TypeError, ValueError, AttributeError):
            return None
    return session.get(TaskRecord, resolved)


def update_task_status(
    session: Session,
    *,
    task_id: str | uuid.UUID,
    status: str,
    result_json: dict[str, Any] | None = None,
    error: str | None = None,
    progress: dict[str, Any] | None = None,
) -> TaskRecord | None:
    task = get_task_record(session, task_id)
    if task is None:
        return None
    now = datetime.now(timezone.utc)
    task.status = status
    task.result_json = result_json
    task.error = error
    if progress is not None:
        task.progress = progress
    if status == "running":
        task.started_at = task.started_at or now
        task.finished_at = None
        task.attempt_count += 1
    elif status in {"completed", "failed"}:
        task.finished_at = now
    session.add(task)
    session.flush()
    return task


def _optional_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    if isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))
