"""Processing profile registry, override, matrix, audit, diff, and rollback routes."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.responses import Response

from ragrig.db.session import get_session
from ragrig.deps import AuthContext, require_admin_auth
from ragrig.processing_profile import (
    ProfileStatus,
    TaskType,
    build_api_profile_list,
    build_matrix,
    create_override,
    delete_override,
    get_override,
    list_overrides,
    resolve_provider_availability,
    update_override,
)
from ragrig.processing_profile.models import ProcessingKind
from ragrig.processing_profile.registry import _db_override_to_dataclass
from ragrig.repositories.processing_profile import (
    compute_diff,
    get_audit_entry_by_id,
    list_audit_log,
    rollback_override,
)

router = APIRouter(tags=["processing-profiles"])


class CreateProcessingProfileRequest(BaseModel):
    profile_id: str
    extension: str
    task_type: TaskType
    display_name: str
    description: str
    provider: str
    model_id: str | None = None
    kind: str = "deterministic"
    tags: list[str] | None = None
    metadata: dict[str, object] | None = None
    created_by: str | None = None


class PatchProcessingProfileRequest(BaseModel):
    status: ProfileStatus | None = None
    display_name: str | None = None
    description: str | None = None
    provider: str | None = None
    model_id: str | None = None
    kind: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, object] | None = None


class DiffPreviewRequest(BaseModel):
    profile_id: str
    status: ProfileStatus | None = None
    display_name: str | None = None
    description: str | None = None
    provider: str | None = None
    model_id: str | None = None
    kind: str | None = None
    tags: list[str] | None = None
    metadata: dict[str, object] | None = None


class RollbackRequest(BaseModel):
    audit_id: str
    actor: str | None = None


def _processing_kind(kind: str) -> ProcessingKind:
    if kind == "LLM-assisted":
        return ProcessingKind.LLM_ASSISTED
    return ProcessingKind.DETERMINISTIC


@router.get("/processing-profiles", response_model=None)
def processing_profiles(
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, list[dict[str, Any]]]:
    return {"profiles": build_api_profile_list(session=session)}


@router.get("/processing-profiles/overrides", response_model=None)
def processing_profile_overrides(
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, list[dict[str, Any]]]:
    return {"overrides": [profile.to_api_dict() for profile in list_overrides(session=session)]}


@router.get("/processing-profiles/overrides/{profile_id}", response_model=None)
def processing_profile_override_detail(
    profile_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any] | JSONResponse:
    profile = get_override(profile_id, session=session)
    if profile is None:
        return JSONResponse(status_code=404, content={"error": "override_not_found"})
    entry = profile.to_api_dict()
    entry["provider_available"] = resolve_provider_availability(profile.provider)
    return entry


@router.post("/processing-profiles", response_model=None)
def create_processing_profile(
    request: CreateProcessingProfileRequest,
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> dict[str, Any] | JSONResponse:
    try:
        profile = create_override(
            profile_id=request.profile_id,
            extension=request.extension,
            task_type=request.task_type,
            display_name=request.display_name,
            description=request.description,
            provider=request.provider,
            model_id=request.model_id,
            kind=_processing_kind(request.kind),
            tags=request.tags,
            metadata=request.metadata,
            created_by=request.created_by,
            session=session,
        )
        session.commit()
    except ValueError as exc:
        return JSONResponse(status_code=409, content={"error": str(exc)})
    entry = profile.to_api_dict()
    entry["provider_available"] = resolve_provider_availability(profile.provider)
    return entry


@router.patch("/processing-profiles/overrides/{profile_id}", response_model=None)
def patch_processing_profile(
    profile_id: str,
    request: PatchProcessingProfileRequest,
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> dict[str, Any] | JSONResponse:
    if get_override(profile_id, session=session) is None:
        return JSONResponse(status_code=404, content={"error": "override_not_found"})
    kind = _processing_kind(request.kind) if request.kind is not None else None
    try:
        profile = update_override(
            profile_id,
            status=request.status,
            display_name=request.display_name,
            description=request.description,
            provider=request.provider,
            model_id=request.model_id,
            kind=kind,
            tags=request.tags,
            metadata=request.metadata,
            session=session,
        )
        session.commit()
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"error": str(exc)})
    entry = profile.to_api_dict()
    entry["provider_available"] = resolve_provider_availability(profile.provider)
    return entry


@router.delete("/processing-profiles/overrides/{profile_id}", response_model=None)
def delete_processing_profile(
    profile_id: str,
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> Response | JSONResponse:
    deleted = delete_override(profile_id, session=session)
    if not deleted:
        return JSONResponse(status_code=404, content={"error": "override_not_found"})
    session.commit()
    return Response(status_code=204)


@router.get("/processing-profiles/matrix", response_model=None)
def processing_profiles_matrix(
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any]:
    return build_matrix(session=session)


@router.get("/processing-profiles/audit-log", response_model=None)
def processing_profile_audit_log(
    session: Annotated[Session, Depends(get_session)],
    limit: int = 50,
    profile_id: str | None = None,
    action: str | None = None,
    provider: str | None = None,
    task_type: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    entries = list_audit_log(
        session,
        limit=limit,
        profile_id=profile_id,
        action=action,
        provider=provider,
        task_type=task_type,
    )
    return {"entries": entries}


@router.get("/processing-profiles/audit-log/{audit_id}", response_model=None)
def processing_profile_audit_entry(
    audit_id: str,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any] | JSONResponse:
    entry = get_audit_entry_by_id(session, audit_id)
    if entry is None:
        return JSONResponse(status_code=404, content={"error": "audit_entry_not_found"})
    return {
        "id": str(entry.id),
        "profile_id": entry.profile_id,
        "action": entry.action,
        "actor": entry.actor,
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
        "old_state": entry.old_state,
        "new_state": entry.new_state,
    }


@router.post("/processing-profiles/preview-diff", response_model=None)
def processing_profile_preview_diff(
    request: DiffPreviewRequest,
    session: Annotated[Session, Depends(get_session)],
) -> dict[str, Any] | JSONResponse:
    metadata_json = (
        {str(key): value for key, value in (request.metadata or {}).items()}
        if request.metadata is not None
        else None
    )

    diff = compute_diff(
        session,
        profile_id=request.profile_id,
        status=request.status.value if request.status else None,
        display_name=request.display_name,
        description=request.description,
        provider=request.provider,
        model_id=request.model_id,
        kind=request.kind,
        tags=request.tags,
        metadata_json=metadata_json,
    )
    if diff is None:
        return JSONResponse(status_code=404, content={"error": "override_not_found"})
    return diff


@router.post("/processing-profiles/rollback", response_model=None)
def processing_profile_rollback(
    request: RollbackRequest,
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> dict[str, Any] | JSONResponse:
    try:
        override = rollback_override(
            session,
            audit_id=request.audit_id,
            actor=request.actor,
        )
        session.commit()
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg:
            return JSONResponse(status_code=404, content={"error": msg})
        return JSONResponse(status_code=409, content={"error": msg})

    profile = _db_override_to_dataclass(override)
    entry = profile.to_api_dict()
    entry["provider_available"] = resolve_provider_availability(profile.provider)
    return entry
