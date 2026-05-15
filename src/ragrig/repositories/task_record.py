from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from ragrig.db.models import TaskRecord


def create_task_record(
    session: Session,
    *,
    task_type: str,
    payload_json: dict[str, Any],
    status: str = "pending",
) -> TaskRecord:
    task = TaskRecord(
        task_type=task_type,
        payload_json=payload_json,
        status=status,
        result_json=None,
        error=None,
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
) -> TaskRecord | None:
    task = get_task_record(session, task_id)
    if task is None:
        return None
    task.status = status
    task.result_json = result_json
    task.error = error
    session.add(task)
    session.flush()
    return task
