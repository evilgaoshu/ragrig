from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Sequence

import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.db.models import ApiKey, User, UserSession, Workspace, WorkspaceMembership

DEFAULT_WORKSPACE_ID = uuid.UUID("00000000-0000-0000-0000-00000000defa")
DEFAULT_WORKSPACE_SLUG = "default"
DEFAULT_WORKSPACE_DISPLAY_NAME = "Default Workspace"
API_KEY_TOKEN_PREFIX = "rag_live"
SESSION_TOKEN_PREFIX = "rag_session"
_DEFAULT_LOCAL_PEPPER = "ragrig-local-dev-auth-pepper"


@dataclass(frozen=True)
class CreatedApiKey:
    api_key: ApiKey
    token: str


@dataclass(frozen=True)
class CreatedUserSession:
    session: UserSession
    token: str


def normalize_workspace_slug(slug: str) -> str:
    normalized = slug.strip().lower()
    if not normalized:
        raise ValueError("workspace slug must not be empty")
    return normalized


def ensure_default_workspace(session: Session) -> Workspace:
    workspace = session.scalar(
        select(Workspace).where(Workspace.slug == DEFAULT_WORKSPACE_SLUG).limit(1)
    )
    if workspace is not None:
        return workspace

    workspace = Workspace(
        id=DEFAULT_WORKSPACE_ID,
        slug=DEFAULT_WORKSPACE_SLUG,
        display_name=DEFAULT_WORKSPACE_DISPLAY_NAME,
        status="active",
        metadata_json={},
    )
    session.add(workspace)
    session.flush()
    return workspace


def principal_user_subject(user_id: str | uuid.UUID) -> str:
    return f"user:{user_id}"


def principal_group_subjects(group_ids: Sequence[str]) -> list[str]:
    return [f"group:{group_id}" for group_id in group_ids]


def create_api_key(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    name: str,
    created_by_user_id: uuid.UUID | None = None,
    scopes: Sequence[str] | None = None,
    principal_user_id: str | None = None,
    principal_group_ids: Sequence[str] | None = None,
    expires_at: datetime | None = None,
    pepper: str | bytes | None = None,
) -> CreatedApiKey:
    prefix = secrets.token_hex(8)
    secret = secrets.token_urlsafe(32)
    token = f"{API_KEY_TOKEN_PREFIX}_{prefix}_{secret}"
    api_key = ApiKey(
        workspace_id=workspace_id,
        created_by_user_id=created_by_user_id,
        name=name,
        prefix=prefix,
        secret_hash=_hash_secret(secret, pepper=pepper),
        scopes=list(scopes or []),
        principal_user_id=principal_user_id,
        principal_group_ids=list(principal_group_ids or []),
        expires_at=expires_at,
    )
    session.add(api_key)
    session.flush()
    return CreatedApiKey(api_key=api_key, token=token)


def verify_api_key(
    session: Session,
    token: str,
    *,
    workspace_id: uuid.UUID | None = None,
    required_scope: str | None = None,
    now: datetime | None = None,
    pepper: str | bytes | None = None,
) -> ApiKey | None:
    parsed = _parse_api_key_token(token)
    if parsed is None:
        return None
    prefix, secret = parsed
    api_key = session.scalar(select(ApiKey).where(ApiKey.prefix == prefix).limit(1))
    if api_key is None:
        return None
    if workspace_id is not None and api_key.workspace_id != workspace_id:
        return None
    if api_key.revoked_at is not None:
        return None
    if _is_expired(api_key.expires_at, now=now):
        return None
    if required_scope is not None and required_scope not in api_key.scopes:
        return None
    if not hmac.compare_digest(api_key.secret_hash, _hash_secret(secret, pepper=pepper)):
        return None

    api_key.last_used_at = now or datetime.now(UTC)
    session.add(api_key)
    session.flush()
    return api_key


def create_user_session(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    expires_at: datetime,
    scopes: Sequence[str] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    pepper: str | bytes | None = None,
) -> CreatedUserSession:
    token = f"{SESSION_TOKEN_PREFIX}_{secrets.token_urlsafe(32)}"
    user_session = UserSession(
        workspace_id=workspace_id,
        user_id=user_id,
        token_hash=_hash_secret(token, pepper=pepper),
        scopes=list(scopes or []),
        ip_hash=_hash_audit_value(ip, pepper=pepper),
        user_agent_hash=_hash_audit_value(user_agent, pepper=pepper),
        expires_at=expires_at,
    )
    session.add(user_session)
    session.flush()
    return CreatedUserSession(session=user_session, token=token)


def verify_session_token(
    session: Session,
    token: str,
    *,
    workspace_id: uuid.UUID | None = None,
    required_scope: str | None = None,
    now: datetime | None = None,
    pepper: str | bytes | None = None,
) -> UserSession | None:
    token_hash = _hash_secret(token, pepper=pepper)
    user_session = session.scalar(
        select(UserSession).where(UserSession.token_hash == token_hash).limit(1)
    )
    if user_session is None:
        return None
    if workspace_id is not None and user_session.workspace_id != workspace_id:
        return None
    if user_session.revoked_at is not None:
        return None
    if _is_expired(user_session.expires_at, now=now):
        return None
    if required_scope is not None and required_scope not in user_session.scopes:
        return None

    user_session.last_seen_at = now or datetime.now(UTC)
    session.add(user_session)
    session.flush()
    return user_session


def _parse_api_key_token(token: str) -> tuple[str, str] | None:
    parts = token.split("_", 3)
    if len(parts) != 4 or parts[0] != "rag" or parts[1] != "live":
        return None
    prefix = parts[2]
    secret = parts[3]
    if not prefix or not secret:
        return None
    return prefix, secret


def _hash_secret(secret: str, *, pepper: str | bytes | None = None) -> str:
    digest = hmac.new(_pepper_bytes(pepper), secret.encode("utf-8"), hashlib.sha256).digest()
    encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"hmac-sha256:{encoded}"


def _hash_audit_value(value: str | None, *, pepper: str | bytes | None = None) -> str | None:
    if value is None:
        return None
    return _hash_secret(value, pepper=pepper)


def _pepper_bytes(pepper: str | bytes | None) -> bytes:
    if pepper is None:
        pepper = os.getenv("RAGRIG_AUTH_SECRET_PEPPER", _DEFAULT_LOCAL_PEPPER)
    if isinstance(pepper, bytes):
        return pepper
    return pepper.encode("utf-8")


def _is_expired(expires_at: datetime | None, *, now: datetime | None = None) -> bool:
    if expires_at is None:
        return False
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= current


def expires_in(**kwargs: int) -> datetime:
    return datetime.now(UTC) + timedelta(**kwargs)


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def register_user(
    session: Session,
    *,
    email: str,
    password: str,
    display_name: str | None = None,
    session_days: int = 30,
    pepper: str | bytes | None = None,
) -> CreatedUserSession:
    """Create a user, add them as owner of the default workspace, and return a session."""
    normalized_email = email.strip().lower()
    existing = session.scalar(select(User).where(User.email == normalized_email).limit(1))
    if existing is not None:
        raise ValueError("email already registered")

    user = User(
        email=normalized_email,
        display_name=display_name or normalized_email.split("@")[0],
        password_hash=hash_password(password),
        status="active",
    )
    session.add(user)
    session.flush()

    workspace = ensure_default_workspace(session)

    existing_membership = session.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == workspace.id)
        .where(WorkspaceMembership.user_id == user.id)
        .limit(1)
    )
    if existing_membership is None:
        is_first_user = (
            session.scalar(
                select(WorkspaceMembership)
                .where(WorkspaceMembership.workspace_id == workspace.id)
                .limit(1)
            )
            is None
        )
        role = "owner" if is_first_user else "viewer"
        membership = WorkspaceMembership(
            workspace_id=workspace.id,
            user_id=user.id,
            role=role,
            status="active",
        )
        session.add(membership)
        session.flush()

    return create_user_session(
        session,
        workspace_id=workspace.id,
        user_id=user.id,
        expires_at=expires_in(days=session_days),
        scopes=["*"],
        pepper=pepper,
    )


def login_user(
    session: Session,
    *,
    email: str,
    password: str,
    session_days: int = 30,
    ip: str | None = None,
    user_agent: str | None = None,
    pepper: str | bytes | None = None,
) -> CreatedUserSession | None:
    """Verify credentials and return a new session, or None on failure."""
    normalized_email = email.strip().lower()
    user = session.scalar(select(User).where(User.email == normalized_email).limit(1))
    if user is None or user.status != "active":
        return None
    if not user.password_hash or not verify_password(password, user.password_hash):
        return None

    membership = session.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.user_id == user.id)
        .where(WorkspaceMembership.status == "active")
        .limit(1)
    )
    workspace_id = membership.workspace_id if membership else DEFAULT_WORKSPACE_ID

    return create_user_session(
        session,
        workspace_id=workspace_id,
        user_id=user.id,
        expires_at=expires_in(days=session_days),
        scopes=["*"],
        ip=ip,
        user_agent=user_agent,
        pepper=pepper,
    )


def resolve_workspace_id(
    session: Session,
    *,
    authorization: str | None = None,
    pepper: str | bytes | None = None,
) -> uuid.UUID:
    """Resolve workspace ID from an Authorization header or fall back to default.

    Accepts:
    - "Bearer rag_live_<prefix>_<secret>" → verifies API key, returns its workspace_id
    - None or unrecognized format → returns DEFAULT_WORKSPACE_ID (local dev / no-auth)

    Never raises. Falls back to default workspace on any verification failure.
    """
    if authorization:
        token = authorization.removeprefix("Bearer ").strip()
        if token.startswith(API_KEY_TOKEN_PREFIX):
            api_key = verify_api_key(session, token, pepper=pepper)
            if api_key is not None:
                return api_key.workspace_id
        elif token.startswith(SESSION_TOKEN_PREFIX):
            user_session = verify_session_token(session, token, pepper=pepper)
            if user_session is not None:
                return user_session.workspace_id
    return DEFAULT_WORKSPACE_ID
