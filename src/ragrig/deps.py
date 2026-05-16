"""FastAPI dependency helpers for authentication and workspace resolution."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from ragrig.auth import (
    API_KEY_TOKEN_PREFIX,
    DEFAULT_WORKSPACE_ID,
    SESSION_TOKEN_PREFIX,
    verify_api_key,
    verify_session_token,
)
from ragrig.config import Settings, get_settings
from ragrig.db.session import get_session


class AuthContext:
    """Resolved auth identity attached to a request."""

    def __init__(
        self,
        *,
        workspace_id: uuid.UUID,
        user_id: uuid.UUID | None,
        is_anonymous: bool,
        scopes: list[str],
    ) -> None:
        self.workspace_id = workspace_id
        self.user_id = user_id
        self.is_anonymous = is_anonymous
        self.scopes = scopes


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
        )

    if authorization:
        token = authorization.removeprefix("Bearer ").strip()
        if token.startswith(SESSION_TOKEN_PREFIX):
            user_session = verify_session_token(session, token)
            if user_session is not None:
                return AuthContext(
                    workspace_id=user_session.workspace_id,
                    user_id=user_session.user_id,
                    is_anonymous=False,
                    scopes=list(user_session.scopes),
                )
        elif token.startswith(API_KEY_TOKEN_PREFIX):
            api_key = verify_api_key(session, token)
            if api_key is not None:
                return AuthContext(
                    workspace_id=api_key.workspace_id,
                    user_id=None,
                    is_anonymous=False,
                    scopes=list(api_key.scopes),
                )

    return AuthContext(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=None,
        is_anonymous=True,
        scopes=[],
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
    """Dependency that requires a valid authenticated identity (not anonymous)."""
    if auth.is_anonymous:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return auth


def get_workspace_id_from_auth(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> uuid.UUID:
    """Return the workspace_id for the current request.

    When auth is enabled and the caller is anonymous, returns DEFAULT_WORKSPACE_ID
    (read-only public access). Protected write routes should use require_auth instead.
    """
    return auth.workspace_id
