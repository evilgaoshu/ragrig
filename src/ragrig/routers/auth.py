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
    login_user,
    register_user,
    verify_session_token,
)
from ragrig.config import Settings, get_settings
from ragrig.db.models import User, WorkspaceMembership
from ragrig.db.session import get_session

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    display_name: str | None = None


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
    try:
        created = register_user(
            session,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            session_days=settings.ragrig_auth_session_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

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
