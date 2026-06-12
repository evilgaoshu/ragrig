from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from ragrig.auth import ensure_default_workspace
from ragrig.config import Settings
from ragrig.db.models import KnowledgeBase, KnowledgeGraphRelation, UnderstandingRun
from ragrig.deps import AuthContext
from ragrig.knowledge_base_config import (
    RetrievalPreferenceRequest,
    RoleModelConfigRequest,
    kb_retrieval_preferences,
    kb_role_model_config,
    public_role_model_config,
    validate_role_model_config,
)
from ragrig.knowledge_graph import (
    KnowledgeGraphBuildRequest,
    KnowledgeGraphNotFoundError,
    get_knowledge_graph,
    rebuild_knowledge_graph,
)
from ragrig.repositories import (
    create_audit_event,
    delete_kb_permission,
    get_knowledge_base_by_name,
    get_or_create_knowledge_base,
    list_kb_permissions,
    set_kb_permission,
)
from ragrig.services.common import ServiceError, require_knowledge_base_access
from ragrig.understanding import (
    DocumentVersionNotFoundError,
    ProviderUnavailableError,
    UnderstandAllRequest,
    UnderstandingRequest,
    UnderstandingRunFilter,
    build_knowledge_map,
    compare_understanding_runs,
    export_understanding_run,
    export_understanding_runs,
    generate_document_understanding,
    get_understanding_by_version,
    get_understanding_coverage,
    get_understanding_runs,
    knowledge_map_to_dict,
    understand_all_versions,
)
from ragrig.web_console import (
    get_understanding_run_detail,
    list_document_version_chunks,
    list_documents,
    list_knowledge_bases,
    list_understanding_runs,
)


def knowledge_base_by_id_for_workspace(
    *,
    session: Session,
    kb_id: str,
    workspace_id: uuid.UUID,
) -> KnowledgeBase:
    try:
        knowledge_base_id = uuid.UUID(str(kb_id))
    except ValueError as exc:
        raise ServiceError(
            status_code=404,
            content={"error": "knowledge_base_not_found"},
        ) from exc
    knowledge_base = session.get(KnowledgeBase, knowledge_base_id)
    if knowledge_base is None or knowledge_base.workspace_id != workspace_id:
        raise ServiceError(
            status_code=404,
            content={"error": "knowledge_base_not_found"},
        )
    return knowledge_base


def summarize_relation_feedback(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"incorrect": 0, "correct": 0, "needs_review": 0}
    for item in items:
        verdict = item.get("verdict")
        if verdict in counts:
            counts[verdict] += 1
    return {
        "total": sum(counts.values()),
        "incorrect": counts["incorrect"],
        "correct": counts["correct"],
        "needs_review": counts["needs_review"],
        "latest_verdict": items[-1].get("verdict") if items else None,
        "latest_at": items[-1].get("created_at") if items else None,
    }


def _resolve_kb_with_access(
    *,
    session: Session,
    settings: Settings,
    workspace_id: uuid.UUID,
    auth: AuthContext,
    kb_id: str,
    minimum: str,
) -> KnowledgeBase:
    knowledge_base = knowledge_base_by_id_for_workspace(
        session=session,
        kb_id=kb_id,
        workspace_id=workspace_id,
    )
    require_knowledge_base_access(
        settings=settings,
        session=session,
        auth=auth,
        knowledge_base_id=knowledge_base.id,
        minimum=minimum,
    )
    return knowledge_base


def knowledge_bases(
    session: Session,
    *,
    settings: Settings,
    workspace_id: uuid.UUID,
) -> dict[str, list[dict[str, Any]]]:
    return {
        "items": list_knowledge_bases(
            session,
            settings=settings,
            workspace_id=workspace_id,
        )
    }


def create_knowledge_base(
    session: Session,
    *,
    name: str,
    workspace_id: uuid.UUID,
) -> tuple[dict[str, Any], int]:
    normalized_name = name.strip()
    if not normalized_name:
        raise ServiceError(
            status_code=400,
            content={"error": "knowledge base name is required"},
        )
    ensure_default_workspace(session)
    existed = (
        get_knowledge_base_by_name(session, normalized_name, workspace_id=workspace_id) is not None
    )
    kb = get_or_create_knowledge_base(session, normalized_name, workspace_id=workspace_id)
    session.commit()
    return {"id": str(kb.id), "name": kb.name, "created": not existed}, 200 if existed else 201


def list_permissions(
    session: Session,
    *,
    kb_name: str,
    workspace_id: uuid.UUID,
) -> dict[str, list[dict[str, Any]]]:
    kb = get_knowledge_base_by_name(session, kb_name, workspace_id=workspace_id)
    if kb is None:
        raise ServiceError(
            status_code=404,
            content={"error": f"knowledge base '{kb_name}' not found"},
        )
    return {"items": list_kb_permissions(session, knowledge_base_id=kb.id)}


def set_permission(
    session: Session,
    *,
    kb_name: str,
    user_id: str,
    role: str,
    workspace_id: uuid.UUID,
) -> dict[str, str]:
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError as exc:
        raise ServiceError(
            status_code=400,
            content={"error": f"invalid user_id: {user_id!r}"},
        ) from exc
    kb = get_knowledge_base_by_name(session, kb_name, workspace_id=workspace_id)
    if kb is None:
        raise ServiceError(
            status_code=404,
            content={"error": f"knowledge base '{kb_name}' not found"},
        )
    set_kb_permission(
        session,
        knowledge_base_id=kb.id,
        user_id=user_uuid,
        role=role,
    )
    session.commit()
    return {"knowledge_base": kb_name, "user_id": user_id, "role": role}


def delete_permission(
    session: Session,
    *,
    kb_name: str,
    user_id: str,
    workspace_id: uuid.UUID,
) -> dict[str, Any]:
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError as exc:
        raise ServiceError(
            status_code=400,
            content={"error": f"invalid user_id: {user_id!r}"},
        ) from exc
    kb = get_knowledge_base_by_name(session, kb_name, workspace_id=workspace_id)
    if kb is None:
        raise ServiceError(
            status_code=404,
            content={"error": f"knowledge base '{kb_name}' not found"},
        )
    existed = delete_kb_permission(
        session,
        knowledge_base_id=kb.id,
        user_id=user_uuid,
    )
    if not existed:
        raise ServiceError(
            status_code=404,
            content={"error": "no permission override found for this user"},
        )
    session.commit()
    return {"knowledge_base": kb_name, "user_id": user_id, "deleted": True}


def documents(session: Session, *, workspace_id: uuid.UUID) -> dict[str, list[dict[str, Any]]]:
    return {"items": list_documents(session, workspace_id=workspace_id)}


def web_understanding_runs(
    session: Session,
    *,
    knowledge_base_id: str | None,
    limit: int,
    provider: str | None,
    model: str | None,
    profile_id: str | None,
    status: str | None,
    started_after: str | None,
    started_before: str | None,
) -> dict[str, list[dict[str, Any]]]:
    return {
        "items": list_understanding_runs(
            session,
            knowledge_base_id=knowledge_base_id,
            limit=limit,
            provider=provider,
            model=model,
            profile_id=profile_id,
            status=status,
            started_after=started_after,
            started_before=started_before,
        ),
    }


def understanding_run_detail(session: Session, run_id: str) -> dict[str, Any]:
    detail = get_understanding_run_detail(session, run_id)
    if detail is None:
        raise ServiceError(status_code=404, content={"error": "understanding_run_not_found"})
    return detail


def export_understanding_run_payload(
    session: Session,
    run_id: str,
) -> dict[str, Any]:
    result = export_understanding_run(session, run_id)
    if result is None:
        raise ServiceError(status_code=404, content={"error": "understanding_run_not_found"})
    return result


def export_understanding_runs_payload(
    session: Session,
    *,
    kb_id: str,
    filters: UnderstandingRunFilter,
) -> dict[str, Any]:
    return export_understanding_runs(session, kb_id, filters=filters)


def diff_understanding_runs(
    session: Session,
    *,
    run_id: str,
    against: str,
) -> dict[str, Any]:
    result = compare_understanding_runs(session, run_id, against)
    if result is None:
        raise ServiceError(status_code=404, content={"error": "understanding_run_not_found"})
    return result


def document_version_chunks(
    session: Session,
    *,
    document_version_id: str,
    workspace_id: uuid.UUID,
) -> dict[str, list[dict[str, Any]]]:
    return {
        "items": list_document_version_chunks(
            session,
            document_version_id,
            workspace_id=workspace_id,
        )
    }


def understand_document_version(
    session: Session,
    *,
    document_version_id: str,
    request: UnderstandingRequest,
) -> dict[str, Any]:
    try:
        record = generate_document_understanding(
            session,
            document_version_id=document_version_id,
            provider=request.provider,
            model=request.model or "",
            profile_id=request.profile_id,
        )
    except DocumentVersionNotFoundError as exc:
        raise ServiceError(
            status_code=404,
            content={"error": exc.code, "message": str(exc)},
        ) from exc
    except ProviderUnavailableError as exc:
        raise ServiceError(
            status_code=503,
            content={"error": exc.code, "message": str(exc)},
        ) from exc
    return {
        "id": record.id,
        "document_version_id": record.document_version_id,
        "profile_id": record.profile_id,
        "provider": record.provider,
        "model": record.model,
        "input_hash": record.input_hash,
        "status": record.status,
        "result": record.result,
        "error": record.error,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def get_document_understanding(
    session: Session,
    *,
    document_version_id: str,
    allow_missing: bool,
) -> dict[str, Any]:
    record = get_understanding_by_version(session, document_version_id)
    if record is None:
        content = {
            "error": "understanding_not_found",
            "message": f"No understanding result for document version '{document_version_id}'.",
        }
        if allow_missing:
            return content
        raise ServiceError(status_code=404, content=content)
    return {
        "id": record.id,
        "document_version_id": record.document_version_id,
        "profile_id": record.profile_id,
        "provider": record.provider,
        "model": record.model,
        "input_hash": record.input_hash,
        "status": record.status,
        "result": record.result,
        "error": record.error,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def understand_all(
    session: Session,
    *,
    kb_id: str,
    request: UnderstandAllRequest,
    operator: str | None,
) -> dict[str, Any]:
    try:
        result = understand_all_versions(
            session,
            knowledge_base_id=kb_id,
            provider=request.provider,
            model=request.model,
            profile_id=request.profile_id,
            trigger_source="api",
            operator=operator,
        )
    except ProviderUnavailableError as exc:
        raise ServiceError(
            status_code=503,
            content={"error": exc.code, "message": str(exc)},
        ) from exc

    kb_uuid = uuid.UUID(kb_id)
    latest_run = (
        session.query(UnderstandingRun)
        .filter(UnderstandingRun.knowledge_base_id == kb_uuid)
        .order_by(UnderstandingRun.started_at.desc())
        .first()
    )
    return {
        "run_id": str(latest_run.id) if latest_run else None,
        "total": result.total,
        "created": result.created,
        "skipped": result.skipped,
        "failed": result.failed,
        "errors": [{"version_id": e.version_id, "error": e.error} for e in result.errors],
    }


def understanding_coverage(session: Session, *, kb_id: str) -> dict[str, Any]:
    coverage = get_understanding_coverage(session, kb_id)
    return {
        "total_versions": coverage.total_versions,
        "completed": coverage.completed,
        "missing": coverage.missing,
        "stale": coverage.stale,
        "failed": coverage.failed,
        "completeness_score": coverage.completeness_score,
        "recent_errors": [
            {
                "document_version_id": e.document_version_id,
                "profile_id": e.profile_id,
                "provider": e.provider,
                "error": e.error,
            }
            for e in coverage.recent_errors
        ],
    }


def knowledge_map(
    session: Session,
    *,
    kb_id: str,
    profile_id: str,
    settings: Settings,
    workspace_id: uuid.UUID,
    auth: AuthContext,
) -> dict[str, Any]:
    _resolve_kb_with_access(
        session=session,
        settings=settings,
        workspace_id=workspace_id,
        auth=auth,
        kb_id=kb_id,
        minimum="viewer",
    )
    result = build_knowledge_map(session, kb_id, profile_id=profile_id)
    if result is None:
        raise ServiceError(status_code=404, content={"error": "knowledge_base_not_found"})
    return knowledge_map_to_dict(result)


def knowledge_graph(
    session: Session,
    *,
    kb_id: str,
    settings: Settings,
    workspace_id: uuid.UUID,
    auth: AuthContext,
) -> dict[str, Any]:
    _resolve_kb_with_access(
        session=session,
        settings=settings,
        workspace_id=workspace_id,
        auth=auth,
        kb_id=kb_id,
        minimum="viewer",
    )
    try:
        return get_knowledge_graph(session, kb_id).model_dump(mode="json")
    except KnowledgeGraphNotFoundError as exc:
        raise ServiceError(
            status_code=404,
            content={"error": "knowledge_base_not_found"},
        ) from exc


def rebuild_knowledge_graph_payload(
    session: Session,
    *,
    kb_id: str,
    request: KnowledgeGraphBuildRequest,
    settings: Settings,
    workspace_id: uuid.UUID,
    auth: AuthContext,
) -> dict[str, Any]:
    knowledge_base = _resolve_kb_with_access(
        session=session,
        settings=settings,
        workspace_id=workspace_id,
        auth=auth,
        kb_id=kb_id,
        minimum="editor",
    )
    try:
        result = rebuild_knowledge_graph(
            session,
            kb_id,
            profile_id=request.profile_id,
            extractor_version=request.extractor_version,
            reset=request.reset,
            actor=str(auth.user_id) if auth.user_id is not None else "anonymous",
        )
    except KnowledgeGraphNotFoundError as exc:
        raise ServiceError(
            status_code=404,
            content={"error": "knowledge_base_not_found"},
        ) from exc
    except Exception as exc:
        session.rollback()
        trace_id = str(uuid.uuid4())
        knowledge_base = session.get(KnowledgeBase, knowledge_base.id)
        if knowledge_base is not None:
            failed_trace = {
                "status": "failed",
                "trace_id": trace_id,
                "degraded_reason": "graph_extraction_failed",
                "error": str(exc),
            }
            knowledge_base.metadata_json = {
                **(knowledge_base.metadata_json or {}),
                "knowledge_graph": failed_trace,
            }
            create_audit_event(
                session,
                event_type="kg_extract",
                actor=str(auth.user_id) if auth.user_id is not None else "anonymous",
                workspace_id=workspace_id,
                knowledge_base_id=knowledge_base.id,
                payload_json=failed_trace,
            )
            session.commit()
        raise ServiceError(
            status_code=500,
            content={"error": "graph_extraction_failed", "trace_id": trace_id},
        ) from exc
    return result.model_dump(mode="json")


def submit_relation_feedback(
    session: Session,
    *,
    kb_id: str,
    relation_id: str,
    verdict: str,
    note: str | None,
    settings: Settings,
    workspace_id: uuid.UUID,
    auth: AuthContext,
) -> dict[str, Any]:
    knowledge_base = _resolve_kb_with_access(
        session=session,
        settings=settings,
        workspace_id=workspace_id,
        auth=auth,
        kb_id=kb_id,
        minimum="editor",
    )
    try:
        relation_uuid = uuid.UUID(str(relation_id))
    except ValueError as exc:
        raise ServiceError(status_code=404, content={"error": "relation_not_found"}) from exc
    relation = session.get(KnowledgeGraphRelation, relation_uuid)
    if relation is None or relation.knowledge_base_id != knowledge_base.id:
        raise ServiceError(status_code=404, content={"error": "relation_not_found"})

    metadata = dict(relation.metadata_json or {})
    feedback_items = [item for item in metadata.get("feedback", []) if isinstance(item, dict)]
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    actor = str(auth.user_id) if auth.user_id is not None else "anonymous"
    entry: dict[str, Any] = {
        "verdict": verdict,
        "created_at": created_at,
        "actor": actor,
    }
    if note and note.strip():
        entry["note"] = note.strip()
    feedback_items.append(entry)
    metadata["feedback"] = feedback_items[-50:]
    metadata["feedback_summary"] = summarize_relation_feedback(feedback_items)
    relation.metadata_json = metadata
    create_audit_event(
        session,
        event_type="kg_relation_feedback",
        actor=actor,
        workspace_id=workspace_id,
        knowledge_base_id=knowledge_base.id,
        payload_json={
            "relation_id": str(relation.id),
            "verdict": verdict,
            "note": note,
        },
    )
    session.commit()
    return {
        "status": "recorded",
        "relation_id": str(relation.id),
        "feedback": entry,
        "feedback_summary": metadata["feedback_summary"],
    }


def get_retrieval_preferences(
    session: Session,
    *,
    kb_id: str,
    settings: Settings,
    workspace_id: uuid.UUID,
    auth: AuthContext,
) -> dict[str, Any]:
    knowledge_base = _resolve_kb_with_access(
        session=session,
        settings=settings,
        workspace_id=workspace_id,
        auth=auth,
        kb_id=kb_id,
        minimum="viewer",
    )
    return {
        "knowledge_base_id": str(knowledge_base.id),
        "knowledge_base": knowledge_base.name,
        "preferences": kb_retrieval_preferences(knowledge_base),
    }


def put_retrieval_preferences(
    session: Session,
    *,
    kb_id: str,
    request: RetrievalPreferenceRequest,
    settings: Settings,
    workspace_id: uuid.UUID,
    auth: AuthContext,
) -> dict[str, Any]:
    knowledge_base = _resolve_kb_with_access(
        session=session,
        settings=settings,
        workspace_id=workspace_id,
        auth=auth,
        kb_id=kb_id,
        minimum="editor",
    )
    preferences = request.model_dump(mode="json")
    metadata = dict(knowledge_base.metadata_json or {})
    metadata["retrieval_preferences"] = preferences
    knowledge_base.metadata_json = metadata
    actor = str(auth.user_id) if auth.user_id is not None else "anonymous"
    create_audit_event(
        session,
        event_type="retrieval_preference_update",
        actor=actor,
        workspace_id=workspace_id,
        knowledge_base_id=knowledge_base.id,
        payload_json={
            "mode": preferences["mode"],
            "graph_weight": preferences["graph_weight"],
            "graph_depth": preferences["graph_depth"],
        },
    )
    session.commit()
    return {
        "status": "saved",
        "knowledge_base_id": str(knowledge_base.id),
        "knowledge_base": knowledge_base.name,
        "preferences": preferences,
    }


def get_role_model_config(
    session: Session,
    *,
    kb_id: str,
    settings: Settings,
    workspace_id: uuid.UUID,
    auth: AuthContext,
) -> dict[str, Any]:
    knowledge_base = _resolve_kb_with_access(
        session=session,
        settings=settings,
        workspace_id=workspace_id,
        auth=auth,
        kb_id=kb_id,
        minimum="viewer",
    )
    config = kb_role_model_config(knowledge_base) or {}
    return {
        "knowledge_base_id": str(knowledge_base.id),
        "knowledge_base": knowledge_base.name,
        "config": public_role_model_config(config),
        "roles": sorted(str(role) for role in config),
    }


def put_role_model_config(
    session: Session,
    *,
    kb_id: str,
    request: RoleModelConfigRequest,
    settings: Settings,
    workspace_id: uuid.UUID,
    auth: AuthContext,
) -> dict[str, Any]:
    knowledge_base = _resolve_kb_with_access(
        session=session,
        settings=settings,
        workspace_id=workspace_id,
        auth=auth,
        kb_id=kb_id,
        minimum="editor",
    )
    validation_error = validate_role_model_config(request.config)
    if validation_error is not None:
        raise ServiceError(
            status_code=400,
            content={
                "error": {
                    "code": "invalid_role_model_config",
                    "message": validation_error,
                }
            },
        )
    metadata = dict(knowledge_base.metadata_json or {})
    metadata["role_model_config"] = request.config
    knowledge_base.metadata_json = metadata
    actor = str(auth.user_id) if auth.user_id is not None else "anonymous"
    create_audit_event(
        session,
        event_type="role_model_config_update",
        actor=actor,
        workspace_id=workspace_id,
        knowledge_base_id=knowledge_base.id,
        payload_json={"roles": sorted(str(role) for role in request.config)},
    )
    session.commit()
    return {
        "status": "saved",
        "knowledge_base_id": str(knowledge_base.id),
        "knowledge_base": knowledge_base.name,
        "config": public_role_model_config(request.config),
        "roles": sorted(str(role) for role in request.config),
    }


def understanding_runs(
    session: Session,
    *,
    kb_id: str,
    filters: UnderstandingRunFilter,
) -> dict[str, Any]:
    runs = get_understanding_runs(session, kb_id, filters=filters)
    return {"runs": [run.model_dump() for run in runs]}
