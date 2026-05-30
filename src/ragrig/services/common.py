from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ragrig.config import Settings, get_settings
from ragrig.deps import AuthContext
from ragrig.repositories import get_knowledge_base_by_name
from ragrig.retrieval import RetrievalError
from ragrig.routers.runtime import knowledge_base_access_error
from ragrig.vectorstore import get_vector_backend


def serialize_error(exc: RetrievalError) -> dict[str, Any]:
    return {
        "error": {
            "code": exc.code,
            "message": str(exc),
            "details": exc.details,
        }
    }


def create_runtime_settings(settings: Settings | None = None) -> Settings:
    active_settings = settings or get_settings()
    payload = active_settings.model_dump()
    payload["database_url"] = active_settings.runtime_database_url
    return Settings(**payload)


def resolve_vector_backend(settings: Settings) -> Any:
    if settings.vector_backend == "pgvector":
        return None
    return get_vector_backend(settings)


def resolve_acl_context(
    *,
    settings: Settings,
    auth: AuthContext,
    requested_principal_ids: list[str] | None,
    requested_enforce_acl: bool,
) -> tuple[list[str] | None, bool]:
    if not settings.ragrig_auth_enabled:
        return requested_principal_ids, requested_enforce_acl
    return auth.principal_ids, True


def knowledge_base_role_error_by_name(
    *,
    settings: Settings,
    session: Session,
    auth: AuthContext,
    kb_name: str,
    workspace_id: uuid.UUID,
    minimum: str,
) -> JSONResponse | None:
    kb = get_knowledge_base_by_name(session, kb_name, workspace_id=workspace_id)
    if kb is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"knowledge base '{kb_name}' not found"},
        )
    return knowledge_base_access_error(
        settings=settings,
        session=session,
        auth=auth,
        knowledge_base_id=kb.id,
        minimum=minimum,
    )


def resolve_evaluation_path(
    raw_path: str | None,
    *,
    default_path: Path,
    allowed_roots: tuple[Path, ...],
    settings: Settings,
) -> tuple[Path | None, JSONResponse | None]:
    path = Path(raw_path) if raw_path else default_path
    if not settings.ragrig_auth_enabled:
        return path, None
    resolved = path.resolve()
    for root in allowed_roots:
        root_resolved = root.resolve()
        if resolved == root_resolved or root_resolved in resolved.parents:
            return path, None
    allowed = ", ".join(str(root) for root in allowed_roots)
    return None, JSONResponse(
        status_code=400,
        content={"error": f"evaluation path must be under one of: {allowed}"},
    )


def record_usage_for_request(
    session: Session,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID | None,
    cost_latency: dict[str, Any] | None,
    request_metadata: dict[str, Any] | None = None,
    *,
    settings: Settings,
) -> None:
    try:
        from ragrig.usage import evaluate_budget, record_usage_events

        operations = (cost_latency or {}).get("operations") or []
        if not isinstance(operations, list):
            return
        record_usage_events(
            session,
            workspace_id=workspace_id,
            user_id=user_id,
            operations=operations,
            request_metadata=request_metadata,
        )
        evaluate_budget(session, workspace_id=workspace_id, settings=settings)
    except Exception:  # pragma: no cover - usage is best-effort
        import logging

        logging.getLogger(__name__).exception("usage accounting failed")
