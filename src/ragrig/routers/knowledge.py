"""Knowledge base, document, understanding, and knowledge graph routes."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ragrig.auth import ensure_default_workspace
from ragrig.config import Settings, get_settings
from ragrig.db.models import KnowledgeBase, KnowledgeGraphRelation, UnderstandingRun
from ragrig.db.session import get_session
from ragrig.deps import AuthContext, get_auth_context, require_admin_auth, require_write_auth
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
from ragrig.routers.runtime import (
    get_workspace_id,
    knowledge_base_access_error,
)
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

router = APIRouter(tags=["knowledge"])


class KnowledgeBaseCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class KnowledgeGraphRelationFeedbackRequest(BaseModel):
    verdict: str = Field(pattern=r"^(incorrect|correct|needs_review)$")
    note: str | None = Field(default=None, max_length=500)


class KbPermissionRequest(BaseModel):
    role: str = Field(pattern=r"^(admin|editor|viewer|none)$")


def _knowledge_base_by_id_for_workspace(
    *,
    session: Session,
    kb_id: str,
    workspace_id: uuid.UUID,
) -> tuple[KnowledgeBase | None, JSONResponse | None]:
    try:
        knowledge_base_id = uuid.UUID(str(kb_id))
    except ValueError:
        return None, JSONResponse(
            status_code=404,
            content={"error": "knowledge_base_not_found"},
        )
    knowledge_base = session.get(KnowledgeBase, knowledge_base_id)
    if knowledge_base is None or knowledge_base.workspace_id != workspace_id:
        return None, JSONResponse(
            status_code=404,
            content={"error": "knowledge_base_not_found"},
        )
    return knowledge_base, None


def _summarize_relation_feedback(items: list[dict[str, Any]]) -> dict[str, Any]:
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


@router.get("/knowledge-bases", response_model=None)
def knowledge_bases(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
) -> dict[str, list[dict[str, Any]]]:
    return {
        "items": list_knowledge_bases(
            session,
            settings=settings,
            workspace_id=workspace_id,
        )
    }


@router.post("/knowledge-bases", response_model=None)
def create_knowledge_base(
    request: KnowledgeBaseCreateRequest,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    _auth: Annotated[AuthContext, Depends(require_write_auth)],
) -> JSONResponse:
    name = request.name.strip()
    if not name:
        return JSONResponse(status_code=400, content={"error": "knowledge base name is required"})
    ensure_default_workspace(session)
    existed = get_knowledge_base_by_name(session, name, workspace_id=workspace_id) is not None
    kb = get_or_create_knowledge_base(session, name, workspace_id=workspace_id)
    session.commit()
    return JSONResponse(
        status_code=200 if existed else 201,
        content={"id": str(kb.id), "name": kb.name, "created": not existed},
    )


@router.get("/knowledge-bases/{kb_name}/permissions", response_model=None)
def list_kb_permissions_endpoint(
    kb_name: str,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> JSONResponse:
    """List all per-KB permission overrides for a knowledge base."""
    kb = get_knowledge_base_by_name(session, kb_name, workspace_id=workspace_id)
    if kb is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"knowledge base '{kb_name}' not found"},
        )
    return JSONResponse(
        status_code=200,
        content={"items": list_kb_permissions(session, knowledge_base_id=kb.id)},
    )


@router.put("/knowledge-bases/{kb_name}/permissions/{user_id}", response_model=None)
def set_kb_permission_endpoint(
    kb_name: str,
    user_id: str,
    request: KbPermissionRequest,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> JSONResponse:
    """Upsert a per-KB role override for a user."""
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": f"invalid user_id: {user_id!r}"})
    kb = get_knowledge_base_by_name(session, kb_name, workspace_id=workspace_id)
    if kb is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"knowledge base '{kb_name}' not found"},
        )
    set_kb_permission(
        session,
        knowledge_base_id=kb.id,
        user_id=user_uuid,
        role=request.role,
    )
    session.commit()
    return JSONResponse(
        status_code=200,
        content={"knowledge_base": kb_name, "user_id": user_id, "role": request.role},
    )


@router.delete("/knowledge-bases/{kb_name}/permissions/{user_id}", response_model=None)
def delete_kb_permission_endpoint(
    kb_name: str,
    user_id: str,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> JSONResponse:
    """Remove the per-KB permission override for a user."""
    try:
        user_uuid = uuid.UUID(user_id)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": f"invalid user_id: {user_id!r}"})
    kb = get_knowledge_base_by_name(session, kb_name, workspace_id=workspace_id)
    if kb is None:
        return JSONResponse(
            status_code=404,
            content={"error": f"knowledge base '{kb_name}' not found"},
        )
    existed = delete_kb_permission(
        session,
        knowledge_base_id=kb.id,
        user_id=user_uuid,
    )
    if not existed:
        return JSONResponse(
            status_code=404,
            content={"error": "no permission override found for this user"},
        )
    session.commit()
    return JSONResponse(
        status_code=200,
        content={"knowledge_base": kb_name, "user_id": user_id, "deleted": True},
    )


@router.get("/documents", response_model=None)
def documents(
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
) -> dict[str, list[dict[str, Any]]]:
    return {"items": list_documents(session, workspace_id=workspace_id)}


@router.get("/understanding-runs", response_model=None)
def web_understanding_runs(
    session: Annotated[Session, Depends(get_session)],
    knowledge_base_id: str | None = None,
    limit: int = 20,
    provider: str | None = None,
    model: str | None = None,
    profile_id: str | None = None,
    status: str | None = None,
    started_after: str | None = None,
    started_before: str | None = None,
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


@router.get("/understanding-runs/{run_id}", response_model=None)
def web_understanding_run_detail(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any] | JSONResponse:
    detail = get_understanding_run_detail(session, run_id)
    if detail is None:
        return JSONResponse(status_code=404, content={"error": "understanding_run_not_found"})
    return detail


@router.get("/understanding-runs/{run_id}/export", response_model=None)
def export_understanding_run_endpoint(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any] | JSONResponse:
    result = export_understanding_run(session, run_id)
    if result is None:
        return JSONResponse(status_code=404, content={"error": "understanding_run_not_found"})
    return result


@router.get("/knowledge-bases/{kb_id}/understanding-runs/export", response_model=None)
def export_understanding_runs_endpoint(
    kb_id: str,
    session: Annotated[Session, Depends(get_session)],
    provider: str | None = None,
    model: str | None = None,
    profile_id: str | None = None,
    status: str | None = None,
    started_after: str | None = None,
    started_before: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    filters = UnderstandingRunFilter(
        provider=provider,
        model=model,
        profile_id=profile_id,
        status=status,
        started_after=started_after,
        started_before=started_before,
        limit=limit,
    )
    return export_understanding_runs(session, kb_id, filters=filters)


@router.get("/understanding-runs/{run_id}/diff", response_model=None)
def diff_understanding_runs_endpoint(
    run_id: str,
    session: Annotated[Session, Depends(get_session)],
    against: str,
) -> dict[str, Any] | JSONResponse:
    result = compare_understanding_runs(session, run_id, against)
    if result is None:
        return JSONResponse(status_code=404, content={"error": "understanding_run_not_found"})
    return result


@router.get("/document-versions/{document_version_id}/chunks", response_model=None)
def document_version_chunks(
    document_version_id: str,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
) -> dict[str, list[dict[str, Any]]]:
    return {
        "items": list_document_version_chunks(
            session,
            document_version_id,
            workspace_id=workspace_id,
        )
    }


@router.post("/document-versions/{document_version_id}/understand", response_model=None)
def understand_document_version(
    document_version_id: str,
    request: UnderstandingRequest,
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_write_auth)],
) -> dict[str, Any] | JSONResponse:
    try:
        record = generate_document_understanding(
            session,
            document_version_id=document_version_id,
            provider=request.provider,
            model=request.model or "",
            profile_id=request.profile_id,
        )
    except DocumentVersionNotFoundError as exc:
        return JSONResponse(status_code=404, content={"error": exc.code, "message": str(exc)})
    except ProviderUnavailableError as exc:
        return JSONResponse(status_code=503, content={"error": exc.code, "message": str(exc)})
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


@router.get("/document-versions/{document_version_id}/understanding", response_model=None)
def get_document_understanding(
    document_version_id: str,
    session: Annotated[Session, Depends(get_session)],
    allow_missing: bool = False,
) -> dict[str, Any] | JSONResponse:
    record = get_understanding_by_version(session, document_version_id)
    if record is None:
        content = {
            "error": "understanding_not_found",
            "message": f"No understanding result for document version '{document_version_id}'.",
        }
        if allow_missing:
            return JSONResponse(status_code=200, content=content)
        return JSONResponse(
            status_code=404,
            content=content,
        )
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


@router.post("/knowledge-bases/{kb_id}/understand-all", response_model=None)
def understand_all(
    kb_id: str,
    request: UnderstandAllRequest,
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_write_auth)],
    x_operator: Annotated[str | None, Header()] = None,
) -> dict[str, Any] | JSONResponse:
    operator = x_operator
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
        return JSONResponse(status_code=503, content={"error": exc.code, "message": str(exc)})

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


@router.get("/knowledge-bases/{kb_id}/understanding-coverage", response_model=None)
def understanding_coverage(
    kb_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
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


@router.get("/knowledge-bases/{kb_id}/knowledge-map", response_model=None)
def knowledge_map(
    kb_id: str,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    profile_id: str = "*.understand.default",
) -> dict[str, Any] | JSONResponse:
    knowledge_base, kb_error = _knowledge_base_by_id_for_workspace(
        session=session,
        kb_id=kb_id,
        workspace_id=workspace_id,
    )
    if kb_error is not None:
        return kb_error
    assert knowledge_base is not None
    access_error = knowledge_base_access_error(
        settings=settings,
        session=session,
        auth=auth,
        knowledge_base_id=knowledge_base.id,
        minimum="viewer",
    )
    if access_error is not None:
        return access_error
    result = build_knowledge_map(session, kb_id, profile_id=profile_id)
    if result is None:
        return JSONResponse(status_code=404, content={"error": "knowledge_base_not_found"})
    return knowledge_map_to_dict(result)


@router.get("/knowledge-bases/{kb_id}/knowledge-graph", response_model=None)
def knowledge_graph(
    kb_id: str,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict[str, Any] | JSONResponse:
    knowledge_base, kb_error = _knowledge_base_by_id_for_workspace(
        session=session,
        kb_id=kb_id,
        workspace_id=workspace_id,
    )
    if kb_error is not None:
        return kb_error
    assert knowledge_base is not None
    access_error = knowledge_base_access_error(
        settings=settings,
        session=session,
        auth=auth,
        knowledge_base_id=knowledge_base.id,
        minimum="viewer",
    )
    if access_error is not None:
        return access_error
    try:
        return get_knowledge_graph(session, kb_id).model_dump(mode="json")
    except (ValueError, KnowledgeGraphNotFoundError):
        return JSONResponse(status_code=404, content={"error": "knowledge_base_not_found"})


@router.post("/knowledge-bases/{kb_id}/knowledge-graph/rebuild", response_model=None)
def rebuild_knowledge_graph_endpoint(
    kb_id: str,
    request: KnowledgeGraphBuildRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
) -> dict[str, Any] | JSONResponse:
    knowledge_base, kb_error = _knowledge_base_by_id_for_workspace(
        session=session,
        kb_id=kb_id,
        workspace_id=workspace_id,
    )
    if kb_error is not None:
        return kb_error
    assert knowledge_base is not None
    access_error = knowledge_base_access_error(
        settings=settings,
        session=session,
        auth=auth,
        knowledge_base_id=knowledge_base.id,
        minimum="editor",
    )
    if access_error is not None:
        return access_error
    try:
        result = rebuild_knowledge_graph(
            session,
            kb_id,
            profile_id=request.profile_id,
            extractor_version=request.extractor_version,
            reset=request.reset,
        )
    except (ValueError, KnowledgeGraphNotFoundError):
        return JSONResponse(status_code=404, content={"error": "knowledge_base_not_found"})
    return result.model_dump(mode="json")


@router.post(
    "/knowledge-bases/{kb_id}/knowledge-graph/relations/{relation_id}/feedback",
    response_model=None,
)
def submit_knowledge_graph_relation_feedback(
    kb_id: str,
    relation_id: str,
    request: KnowledgeGraphRelationFeedbackRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
) -> dict[str, Any] | JSONResponse:
    knowledge_base, kb_error = _knowledge_base_by_id_for_workspace(
        session=session,
        kb_id=kb_id,
        workspace_id=workspace_id,
    )
    if kb_error is not None:
        return kb_error
    assert knowledge_base is not None
    access_error = knowledge_base_access_error(
        settings=settings,
        session=session,
        auth=auth,
        knowledge_base_id=knowledge_base.id,
        minimum="editor",
    )
    if access_error is not None:
        return access_error
    try:
        relation_uuid = uuid.UUID(str(relation_id))
    except ValueError:
        return JSONResponse(status_code=404, content={"error": "relation_not_found"})
    relation = session.get(KnowledgeGraphRelation, relation_uuid)
    if relation is None or relation.knowledge_base_id != knowledge_base.id:
        return JSONResponse(status_code=404, content={"error": "relation_not_found"})

    metadata = dict(relation.metadata_json or {})
    feedback_items = [item for item in metadata.get("feedback", []) if isinstance(item, dict)]
    created_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    actor = str(auth.user_id) if auth.user_id is not None else "anonymous"
    entry: dict[str, Any] = {
        "verdict": request.verdict,
        "created_at": created_at,
        "actor": actor,
    }
    if request.note and request.note.strip():
        entry["note"] = request.note.strip()
    feedback_items.append(entry)
    metadata["feedback"] = feedback_items[-50:]
    metadata["feedback_summary"] = _summarize_relation_feedback(feedback_items)
    relation.metadata_json = metadata
    create_audit_event(
        session,
        event_type="kg_relation_feedback",
        actor=actor,
        workspace_id=workspace_id,
        knowledge_base_id=knowledge_base.id,
        payload_json={
            "relation_id": str(relation.id),
            "verdict": request.verdict,
            "note": request.note,
        },
    )
    session.commit()
    return {
        "status": "recorded",
        "relation_id": str(relation.id),
        "feedback": entry,
        "feedback_summary": metadata["feedback_summary"],
    }


@router.get("/knowledge-bases/{kb_id}/retrieval-preferences", response_model=None)
def get_retrieval_preferences(
    kb_id: str,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict[str, Any] | JSONResponse:
    knowledge_base, kb_error = _knowledge_base_by_id_for_workspace(
        session=session,
        kb_id=kb_id,
        workspace_id=workspace_id,
    )
    if kb_error is not None:
        return kb_error
    assert knowledge_base is not None
    access_error = knowledge_base_access_error(
        settings=settings,
        session=session,
        auth=auth,
        knowledge_base_id=knowledge_base.id,
        minimum="viewer",
    )
    if access_error is not None:
        return access_error
    return {
        "knowledge_base_id": str(knowledge_base.id),
        "knowledge_base": knowledge_base.name,
        "preferences": kb_retrieval_preferences(knowledge_base),
    }


@router.put("/knowledge-bases/{kb_id}/retrieval-preferences", response_model=None)
def put_retrieval_preferences(
    kb_id: str,
    request: RetrievalPreferenceRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
) -> dict[str, Any] | JSONResponse:
    knowledge_base, kb_error = _knowledge_base_by_id_for_workspace(
        session=session,
        kb_id=kb_id,
        workspace_id=workspace_id,
    )
    if kb_error is not None:
        return kb_error
    assert knowledge_base is not None
    access_error = knowledge_base_access_error(
        settings=settings,
        session=session,
        auth=auth,
        knowledge_base_id=knowledge_base.id,
        minimum="editor",
    )
    if access_error is not None:
        return access_error
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


@router.get("/knowledge-bases/{kb_id}/role-model-config", response_model=None)
def get_role_model_config(
    kb_id: str,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict[str, Any] | JSONResponse:
    knowledge_base, kb_error = _knowledge_base_by_id_for_workspace(
        session=session,
        kb_id=kb_id,
        workspace_id=workspace_id,
    )
    if kb_error is not None:
        return kb_error
    assert knowledge_base is not None
    access_error = knowledge_base_access_error(
        settings=settings,
        session=session,
        auth=auth,
        knowledge_base_id=knowledge_base.id,
        minimum="viewer",
    )
    if access_error is not None:
        return access_error
    config = kb_role_model_config(knowledge_base) or {}
    return {
        "knowledge_base_id": str(knowledge_base.id),
        "knowledge_base": knowledge_base.name,
        "config": public_role_model_config(config),
        "roles": sorted(str(role) for role in config),
    }


@router.put("/knowledge-bases/{kb_id}/role-model-config", response_model=None)
def put_role_model_config(
    kb_id: str,
    request: RoleModelConfigRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
) -> dict[str, Any] | JSONResponse:
    knowledge_base, kb_error = _knowledge_base_by_id_for_workspace(
        session=session,
        kb_id=kb_id,
        workspace_id=workspace_id,
    )
    if kb_error is not None:
        return kb_error
    assert knowledge_base is not None
    access_error = knowledge_base_access_error(
        settings=settings,
        session=session,
        auth=auth,
        knowledge_base_id=knowledge_base.id,
        minimum="editor",
    )
    if access_error is not None:
        return access_error
    validation_error = validate_role_model_config(request.config)
    if validation_error is not None:
        return JSONResponse(
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


@router.get("/knowledge-bases/{kb_id}/understanding-runs", response_model=None)
def understanding_runs(
    kb_id: str,
    session: Annotated[Session, Depends(get_session)],
    provider: str | None = None,
    model: str | None = None,
    profile_id: str | None = None,
    status: str | None = None,
    started_after: str | None = None,
    started_before: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    filters = UnderstandingRunFilter(
        provider=provider,
        model=model,
        profile_id=profile_id,
        status=status,
        started_after=started_after,
        started_before=started_before,
        limit=limit,
    )
    runs = get_understanding_runs(session, kb_id, filters=filters)
    return {
        "runs": [r.model_dump() for r in runs],
    }
