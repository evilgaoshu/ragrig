"""Shared FastAPI runtime dependencies for routers.

Most routers can rely on ``ragrig.db.session.get_session`` plus FastAPI's app
dependency overrides. A few routes also need the runtime session factory or the
task executor that ``create_app()`` wires. Those live on ``app.state`` and are
exposed here as request-scoped dependencies.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from ragrig.deps import get_workspace_id_from_auth

SessionFactory = Callable[[], Session]
DatabaseCheck = Callable[[], None]


def set_runtime_state(
    app,
    *,
    session_factory: SessionFactory,
    task_executor: Any,
    database_check: DatabaseCheck | None = None,
    rate_limiter: Any | None = None,
) -> None:
    app.state.ragrig_session_factory = session_factory
    app.state.ragrig_task_executor = task_executor
    if database_check is not None:
        app.state.ragrig_database_check = database_check
    if rate_limiter is not None:
        app.state.ragrig_rate_limiter = rate_limiter


def get_session_factory(request: Request) -> SessionFactory:
    factory = getattr(request.app.state, "ragrig_session_factory", None)
    if factory is None:  # pragma: no cover - indicates app wiring drift
        raise RuntimeError("RAGRig runtime session factory is not configured")
    return factory


def get_task_executor(request: Request) -> Any:
    task_executor = getattr(request.app.state, "ragrig_task_executor", None)
    if task_executor is None:  # pragma: no cover - indicates app wiring drift
        raise RuntimeError("RAGRig runtime task executor is not configured")
    return task_executor


def get_database_check(request: Request) -> DatabaseCheck:
    database_check = getattr(request.app.state, "ragrig_database_check", None)
    if database_check is None:  # pragma: no cover - indicates app wiring drift
        raise RuntimeError("RAGRig runtime database check is not configured")
    return database_check


def get_rate_limiter(request: Request) -> Any:
    rate_limiter = getattr(request.app.state, "ragrig_rate_limiter", None)
    if rate_limiter is None:  # pragma: no cover - indicates app wiring drift
        raise RuntimeError("RAGRig runtime rate limiter is not configured")
    return rate_limiter


def get_workspace_id(
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id_from_auth)],
) -> uuid.UUID:
    return workspace_id


def redact_summary(payload: dict[str, Any]) -> dict[str, Any]:
    forbidden = {
        "password",
        "api_key",
        "token",
        "secret",
        "raw_secret",
        "private_key",
        "access_key",
    }
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        safe_key = str(key)
        if safe_key.lower() in forbidden:
            safe[safe_key] = "[REDACTED]"
        elif isinstance(value, dict):
            safe[safe_key] = redact_summary(value)
        elif isinstance(value, list):
            safe[safe_key] = [
                redact_summary(item) if isinstance(item, dict) else item for item in value[:50]
            ]
        elif isinstance(value, str) and len(value) > 240:
            safe[safe_key] = value[:237] + "..."
        else:
            safe[safe_key] = value
    return safe
