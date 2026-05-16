from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.auth import (
    DEFAULT_WORKSPACE_ID,
    SESSION_TOKEN_PREFIX,
    create_invitation,
    login_user,
    register_user,
    verify_session_token,
)
from ragrig.config import Settings, get_settings
from ragrig.db.models import User, WorkspaceInvitation, WorkspaceMembership
from ragrig.db.session import get_session
from ragrig.deps import AuthContext, require_admin_auth, require_auth

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str | None = None
    invitation_token: str | None = None


class InvitationRequest(BaseModel):
    email: str | None = None
    role: str = Field(default="editor", pattern=r"^(owner|admin|editor|viewer)$")
    days: int = Field(default=7, ge=1, le=90)


class InvitationResponse(BaseModel):
    id: str
    email: str | None
    role: str
    status: str
    expires_at: str
    token: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class AuthResponse(BaseModel):
    token: str
    user_id: str
    email: str
    display_name: str | None
    workspace_id: str
    role: str | None


class MeResponse(BaseModel):
    user_id: str
    email: str | None
    display_name: str | None
    workspace_id: str
    role: str | None


class MemberResponse(BaseModel):
    user_id: str
    email: str | None
    display_name: str | None
    role: str
    status: str


class PatchMemberRequest(BaseModel):
    role: str = Field(pattern=r"^(owner|admin|editor|viewer)$")


def _get_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    token = authorization.removeprefix("Bearer ").strip()
    return token if token.startswith(SESSION_TOKEN_PREFIX) else None


def _role_for(session: Session, user_id: uuid.UUID, workspace_id: uuid.UUID) -> str | None:
    m = session.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.user_id == user_id)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.status == "active")
        .limit(1)
    )
    return m.role if m else None


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthResponse:
    if settings.ragrig_auth_enabled and not settings.ragrig_open_registration:
        if not body.invitation_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="registration requires an invitation token",
            )
    try:
        created = register_user(
            session,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            session_days=settings.ragrig_auth_session_days,
            invitation_token=body.invitation_token,
        )
    except ValueError as exc:
        status_code = (
            status.HTTP_409_CONFLICT
            if "already registered" in str(exc)
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    session.commit()
    user = session.get(User, created.session.user_id)
    role = _role_for(session, created.session.user_id, created.session.workspace_id)
    return AuthResponse(
        token=created.token,
        user_id=str(created.session.user_id),
        email=user.email or "",
        display_name=user.display_name,
        workspace_id=str(created.session.workspace_id),
        role=role,
    )


@router.post("/login", response_model=AuthResponse)
def login(
    body: LoginRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthResponse:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    created = login_user(
        session,
        email=body.email,
        password=body.password,
        session_days=settings.ragrig_auth_session_days,
        ip=ip,
        user_agent=ua,
    )
    if created is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )
    session.commit()
    user = session.get(User, created.session.user_id)
    role = _role_for(session, created.session.user_id, created.session.workspace_id)
    return AuthResponse(
        token=created.token,
        user_id=str(created.session.user_id),
        email=user.email or "",
        display_name=user.display_name,
        workspace_id=str(created.session.workspace_id),
        role=role,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    session: Annotated[Session, Depends(get_session)] = None,  # type: ignore[assignment]
) -> None:
    token = _get_token(authorization)
    if not token:
        return
    user_session = verify_session_token(session, token)
    if user_session is None:
        return
    user_session.revoked_at = datetime.now(UTC)
    session.add(user_session)
    session.commit()


@router.get("/me", response_model=MeResponse)
def me(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    session: Annotated[Session, Depends(get_session)] = None,  # type: ignore[assignment]
    settings: Annotated[Settings, Depends(get_settings)] = None,  # type: ignore[assignment]
) -> MeResponse:
    token = _get_token(authorization)
    if not token:
        if not settings.ragrig_auth_enabled:
            return MeResponse(
                user_id="anonymous",
                email=None,
                display_name="Anonymous",
                workspace_id=str(DEFAULT_WORKSPACE_ID),
                role="owner",
            )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")

    user_session = verify_session_token(session, token)
    if user_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired token"
        )

    session.commit()
    user = session.get(User, user_session.user_id)
    role = _role_for(session, user_session.user_id, user_session.workspace_id)
    return MeResponse(
        user_id=str(user_session.user_id),
        email=user.email if user else None,
        display_name=user.display_name if user else None,
        workspace_id=str(user_session.workspace_id),
        role=role,
    )


# ── User management ──────────────────────────────────────────────────────────


@router.get("/workspace/members", response_model=list[MemberResponse])
def list_members(
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> list[MemberResponse]:
    """List all active members in the caller's workspace."""
    rows = session.scalars(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == auth.workspace_id)
        .where(WorkspaceMembership.status == "active")
    ).all()
    result = []
    for m in rows:
        user = session.get(User, m.user_id)
        result.append(
            MemberResponse(
                user_id=str(m.user_id),
                email=user.email if user else None,
                display_name=user.display_name if user else None,
                role=m.role,
                status=m.status,
            )
        )
    return result


@router.patch(
    "/workspace/members/{target_user_id}",
    response_model=MemberResponse,
)
def update_member_role(
    target_user_id: uuid.UUID,
    body: PatchMemberRequest,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> MemberResponse:
    """Change a workspace member's role. Requires admin or owner."""
    m = session.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == auth.workspace_id)
        .where(WorkspaceMembership.user_id == target_user_id)
        .where(WorkspaceMembership.status == "active")
    )
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    # Prevent non-owners from promoting to owner
    if body.role == "owner" and auth.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only owners can assign the owner role",
        )

    m.role = body.role
    session.add(m)
    session.commit()

    user = session.get(User, m.user_id)
    return MemberResponse(
        user_id=str(m.user_id),
        email=user.email if user else None,
        display_name=user.display_name if user else None,
        role=m.role,
        status=m.status,
    )


@router.delete(
    "/workspace/members/{target_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_member(
    target_user_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> None:
    """Remove a workspace member. Requires admin or owner."""
    m = session.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == auth.workspace_id)
        .where(WorkspaceMembership.user_id == target_user_id)
        .where(WorkspaceMembership.status == "active")
    )
    if m is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")

    # Prevent removing yourself
    if auth.user_id is not None and auth.user_id == target_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot remove yourself from the workspace",
        )

    m.status = "deleted"
    session.add(m)
    session.commit()


# ── Workspace invitations ─────────────────────────────────────────────────────


@router.post(
    "/workspace/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_workspace_invitation(
    body: InvitationRequest,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> InvitationResponse:
    """Create an invitation link. Requires admin or owner."""
    if body.role == "owner" and auth.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only owners can invite with owner role",
        )
    user_id = auth.user_id if auth.user_id else None
    created = create_invitation(
        session,
        workspace_id=auth.workspace_id,
        created_by_user_id=user_id,
        email=body.email,
        role=body.role,
        days=body.days,
    )
    session.commit()
    return InvitationResponse(
        id=str(created.invitation.id),
        email=created.invitation.email,
        role=created.invitation.role,
        status=created.invitation.status,
        expires_at=created.invitation.expires_at.isoformat(),
        token=created.token,
    )


@router.get("/workspace/invitations", response_model=list[InvitationResponse])
def list_workspace_invitations(
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> list[InvitationResponse]:
    """List pending invitations for this workspace. Requires admin or owner."""
    rows = session.scalars(
        select(WorkspaceInvitation)
        .where(WorkspaceInvitation.workspace_id == auth.workspace_id)
        .where(WorkspaceInvitation.status == "pending")
        .order_by(WorkspaceInvitation.created_at.desc())
    ).all()
    return [
        InvitationResponse(
            id=str(inv.id),
            email=inv.email,
            role=inv.role,
            status=inv.status,
            expires_at=inv.expires_at.isoformat(),
        )
        for inv in rows
    ]


@router.delete(
    "/workspace/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_workspace_invitation(
    invitation_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> None:
    """Revoke a pending invitation. Requires admin or owner."""
    inv = session.scalar(
        select(WorkspaceInvitation)
        .where(WorkspaceInvitation.id == invitation_id)
        .where(WorkspaceInvitation.workspace_id == auth.workspace_id)
    )
    if inv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invitation not found")
    if inv.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="invitation is not pending"
        )
    inv.status = "revoked"
    session.add(inv)
    session.commit()
