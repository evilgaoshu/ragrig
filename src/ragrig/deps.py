"""FastAPI dependency helpers for authentication and workspace resolution."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.auth import (
    API_KEY_TOKEN_PREFIX,
    DEFAULT_WORKSPACE_ID,
    SESSION_TOKEN_PREFIX,
    verify_api_key,
    verify_session_token,
)
from ragrig.config import Settings, get_settings
from ragrig.db.models import WorkspaceMembership
from ragrig.db.session import get_session

_ROLE_ORDER: dict[str, int] = {
    "owner": 3,
    "admin": 2,
    "editor": 1,
    "viewer": 0,
}


class AuthContext:
    """Resolved auth identity attached to a request."""

    def __init__(
        self,
        *,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID | None,
        is_anonymous: bool,
        scopes: list[str],
        role: str | None = None,
    ) -> None:
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.is_anonymous = is_anonymous
        self.scopes = scopes
        self.role = role

    def has_role(self, minimum: str) -> bool:
        """Return True if the context role meets or exceeds *minimum*."""
        if self.role is None:
            return False
        return _ROLE_ORDER.get(self.role, -1) >= _ROLE_ORDER.get(minimum, 999)


def _lookup_role(
    session: Session,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
) -> str | None:
    m = session.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.user_id == user_id)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.status == "active")
        .limit(1)
    )
    return m.role if m else None


def _resolve_auth(
    authorization: str | None,
    session: Session,
    settings: Settings,
) -> AuthContext:
    if not settings.ragrig_auth_enabled:
        return AuthContext(
            workspace_id=DEFAULT_WORKSPACE_ID,
            user_id=None,
            is_anonymous=True,
            scopes=["*"],
            role="owner",
        )

    if authorization:
        token = authorization.removeprefix("Bearer ").strip()
        if token.startswith(SESSION_TOKEN_PREFIX):
            user_session = verify_session_token(session, token)
            if user_session is not None:
                role = _lookup_role(session, user_session.user_id, user_session.workspace_id)
                return AuthContext(
                    workspace_id=user_session.workspace_id,
                    user_id=user_session.user_id,
                    is_anonymous=False,
                    scopes=list(user_session.scopes),
                    role=role,
                )
        elif token.startswith(API_KEY_TOKEN_PREFIX):
            api_key = verify_api_key(session, token)
            if api_key is not None:
                return AuthContext(
                    workspace_id=api_key.workspace_id,
                    user_id=None,
                    is_anonymous=False,
                    scopes=list(api_key.scopes),
                    role=None,
                )

    return AuthContext(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=None,
        is_anonymous=True,
        scopes=[],
        role=None,
    )


def get_auth_context(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    session: Annotated[Session, Depends(get_session)] = None,  # type: ignore[assignment]
    settings: Annotated[Settings, Depends(get_settings)] = None,  # type: ignore[assignment]
) -> AuthContext:
    return _resolve_auth(authorization, session, settings)


def require_auth(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> AuthContext:
    """Require a valid authenticated identity (not anonymous)."""
    if auth.is_anonymous:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return auth


def require_write_auth(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)] = None,  # type: ignore[assignment]
) -> AuthContext:
    """Require editor-or-above role on write routes.

    When auth is disabled (local dev), all requests pass as owner.
    When auth is enabled, viewer and anonymous callers receive 403.
    """
    if settings is not None and not settings.ragrig_auth_enabled:
        return auth
    if auth.is_anonymous:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not auth.has_role("editor"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="editor role or above required",
        )
    return auth


def require_admin_auth(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)] = None,  # type: ignore[assignment]
) -> AuthContext:
    """Require admin-or-above role on sensitive routes.

    When auth is disabled (local dev), all requests pass as owner.
    When auth is enabled, viewer/editor and anonymous callers receive 403.
    """
    if settings is not None and not settings.ragrig_auth_enabled:
        return auth
    if auth.is_anonymous:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not auth.has_role("admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin role or above required",
        )
    return auth


def get_workspace_id_from_auth(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> uuid.UUID:
    """Return the workspace_id for the current request.

    When auth is enabled and the caller is anonymous, returns DEFAULT_WORKSPACE_ID
    (read-only public access). Protected write routes should use require_write_auth instead.
    """
    return auth.workspace_id
