from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ragrig.config import Settings, get_settings
from ragrig.deps import AuthContext
from ragrig.repositories import get_knowledge_base_by_name, resolve_effective_kb_role
from ragrig.retrieval import RetrievalError
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


def role_meets(role: str | None, minimum: str) -> bool:
    role_order = {"owner": 3, "admin": 2, "editor": 1, "viewer": 0, "none": -1}
    return role_order.get(role or "none", -1) >= role_order.get(minimum, 999)


def knowledge_base_access_error(
    *,
    settings: Settings,
    session: Session,
    auth: AuthContext,
    knowledge_base_id: uuid.UUID,
    minimum: str,
    allow_anonymous_reader: bool = False,
) -> JSONResponse | None:
    if not settings.ragrig_auth_enabled:
        return None
    if auth.is_anonymous:
        if allow_anonymous_reader and minimum == "viewer":
            return None
        return JSONResponse(
            status_code=401,
            content={"error": "authentication required"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    if auth.user_id is None:
        if minimum == "viewer":
            return None
        return JSONResponse(
            status_code=403,
            content={"error": f"{minimum} role or above required"},
        )
    if auth.role is None:
        return JSONResponse(
            status_code=403,
            content={"error": f"{minimum} role or above required"},
        )
    role = resolve_effective_kb_role(
        session,
        user_id=auth.user_id,
        knowledge_base_id=knowledge_base_id,
        workspace_role=auth.role,
    )
    if not role_meets(role, minimum):
        return JSONResponse(
            status_code=403,
            content={"error": f"{minimum} role or above required for this knowledge base"},
        )
    return None


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
    resolved = path.resolve()
    configured_roots = tuple(
        Path(value.strip())
        for value in settings.ragrig_evaluation_extra_allowed_roots.split(",")
        if value.strip()
    )
    all_roots = allowed_roots + configured_roots
    for root in all_roots:
        root_resolved = root.resolve()
        if resolved == root_resolved or root_resolved in resolved.parents:
            return path, None
    allowed = ", ".join(str(root) for root in all_roots)
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
