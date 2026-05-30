from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ragrig.auth import (
    DEFAULT_WORKSPACE_ID,
    SESSION_TOKEN_PREFIX,
    create_api_key,
    create_invitation,
    create_user_session,
    ensure_default_workspace,
    expires_in,
    login_user,
    register_user,
    verify_session_token,
)
from ragrig.auth_ldap import LdapAuthError, authenticate_ldap
from ragrig.auth_mfa import (
    consume_backup_code,
    generate_backup_codes,
    generate_totp_secret,
    totp_provisioning_uri,
    totp_qr_png_b64,
    verify_totp,
)
from ragrig.auth_oidc import OidcAuthError, build_authorization_url, exchange_code, generate_state
from ragrig.config import Settings
from ragrig.db.models import (
    ApiKey,
    User,
    UserSession,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from ragrig.deps import AuthContext
from ragrig.email import EmailDeliveryError, send_invitation_email
from ragrig.observability import log_event

logger = logging.getLogger(__name__)

_oidc_states: dict[str, str] = {}


def _hash_identifier(value: str | None) -> str | None:
    if not value:
        return None
    return sha256(value.encode("utf-8")).hexdigest()


def _email_log_fields(email: str) -> dict[str, Any]:
    normalized = email.strip().lower()
    _, _, domain = normalized.partition("@")
    return {
        "email_sha256": _hash_identifier(normalized),
        "email_domain": domain or None,
    }


def get_session_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    token = authorization.removeprefix("Bearer ").strip()
    return token if token.startswith(SESSION_TOKEN_PREFIX) else None


def role_for(session: Session, user_id: uuid.UUID, workspace_id: uuid.UUID) -> str | None:
    membership = session.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.user_id == user_id)
        .where(WorkspaceMembership.workspace_id == workspace_id)
        .where(WorkspaceMembership.status == "active")
        .limit(1)
    )
    return membership.role if membership else None


def _auth_payload(
    *,
    token: str,
    user: User | None,
    user_id: uuid.UUID,
    workspace_id: uuid.UUID,
    role: str | None,
    mfa_required: bool = False,
) -> dict[str, Any]:
    return {
        "token": token,
        "user_id": str(user_id),
        "email": user.email or "" if user else "",
        "display_name": user.display_name if user else None,
        "workspace_id": str(workspace_id),
        "role": role,
        "mfa_required": mfa_required,
    }


def register_account(
    session: Session,
    *,
    email: str,
    password: str,
    display_name: str | None,
    invitation_token: str | None,
    settings: Settings,
) -> dict[str, Any]:
    if settings.ragrig_auth_enabled and not settings.ragrig_open_registration:
        if not invitation_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="registration requires an invitation token",
            )
    try:
        created = register_user(
            session,
            email=email,
            password=password,
            display_name=display_name,
            session_days=settings.ragrig_auth_session_days,
            invitation_token=invitation_token,
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
    role = role_for(session, created.session.user_id, created.session.workspace_id)
    return _auth_payload(
        token=created.token,
        user=user,
        user_id=created.session.user_id,
        workspace_id=created.session.workspace_id,
        role=role,
    )


def login_password(
    session: Session,
    *,
    email: str,
    password: str,
    settings: Settings,
    ip: str | None,
    user_agent: str | None,
) -> dict[str, Any]:
    created = login_user(
        session,
        email=email,
        password=password,
        session_days=settings.ragrig_auth_session_days,
        ip=ip,
        user_agent=user_agent,
    )
    if created is None:
        log_event(
            logger,
            logging.WARNING,
            "auth.login.failed",
            reason="invalid_credentials",
            ip_sha256=_hash_identifier(ip),
            user_agent_sha256=_hash_identifier(user_agent),
            **_email_log_fields(email),
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
        )
    user = session.get(User, created.session.user_id)

    if user is not None and user.mfa_enabled:
        created.session.revoked_at = datetime.now(UTC)
        session.add(created.session)
        pending = create_user_session(
            session,
            workspace_id=created.session.workspace_id,
            user_id=created.session.user_id,
            expires_at=expires_in(minutes=10),
            scopes=["mfa:pending"],
            ip=ip,
            user_agent=user_agent,
        )
        session.commit()
        log_event(
            logger,
            logging.INFO,
            "auth.login.completed",
            mfa_required=True,
            user_id=str(user.id),
            workspace_id=str(pending.session.workspace_id),
            **_email_log_fields(email),
        )
        return _auth_payload(
            token=pending.token,
            user=user,
            user_id=user.id,
            workspace_id=pending.session.workspace_id,
            role=None,
            mfa_required=True,
        )

    session.commit()
    role = role_for(session, created.session.user_id, created.session.workspace_id)
    log_event(
        logger,
        logging.INFO,
        "auth.login.completed",
        mfa_required=False,
        user_id=str(created.session.user_id),
        workspace_id=str(created.session.workspace_id),
        role=role,
        **_email_log_fields(email),
    )
    return _auth_payload(
        token=created.token,
        user=user,
        user_id=created.session.user_id,
        workspace_id=created.session.workspace_id,
        role=role,
    )


def logout_session(session: Session, authorization: str | None) -> None:
    token = get_session_token(authorization)
    if not token:
        return
    user_session = verify_session_token(session, token)
    if user_session is None:
        return
    user_session.revoked_at = datetime.now(UTC)
    session.add(user_session)
    session.commit()


def current_user(
    session: Session,
    *,
    authorization: str | None,
    settings: Settings,
) -> dict[str, Any]:
    token = get_session_token(authorization)
    if not token:
        if not settings.ragrig_auth_enabled:
            return {
                "user_id": "anonymous",
                "email": None,
                "display_name": "Anonymous",
                "workspace_id": str(DEFAULT_WORKSPACE_ID),
                "role": "owner",
            }
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="not authenticated")

    user_session = verify_session_token(session, token)
    if user_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
        )

    session.commit()
    user = session.get(User, user_session.user_id)
    role = role_for(session, user_session.user_id, user_session.workspace_id)
    return {
        "user_id": str(user_session.user_id),
        "email": user.email if user else None,
        "display_name": user.display_name if user else None,
        "workspace_id": str(user_session.workspace_id),
        "role": role,
    }


def list_members(session: Session, auth: AuthContext) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == auth.workspace_id)
        .where(WorkspaceMembership.status == "active")
    ).all()
    result: list[dict[str, Any]] = []
    for membership in rows:
        user = session.get(User, membership.user_id)
        result.append(
            {
                "user_id": str(membership.user_id),
                "email": user.email if user else None,
                "display_name": user.display_name if user else None,
                "role": membership.role,
                "status": membership.status,
            }
        )
    return result


def update_member_role(
    session: Session,
    auth: AuthContext,
    *,
    target_user_id: uuid.UUID,
    role: str,
) -> dict[str, Any]:
    membership = session.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == auth.workspace_id)
        .where(WorkspaceMembership.user_id == target_user_id)
        .where(WorkspaceMembership.status == "active")
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
    if role == "owner" and auth.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only owners can assign the owner role",
        )

    membership.role = role
    session.add(membership)
    session.commit()

    user = session.get(User, membership.user_id)
    return {
        "user_id": str(membership.user_id),
        "email": user.email if user else None,
        "display_name": user.display_name if user else None,
        "role": membership.role,
        "status": membership.status,
    }


def remove_member(session: Session, auth: AuthContext, *, target_user_id: uuid.UUID) -> None:
    membership = session.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == auth.workspace_id)
        .where(WorkspaceMembership.user_id == target_user_id)
        .where(WorkspaceMembership.status == "active")
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="member not found")
    if auth.user_id is not None and auth.user_id == target_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot remove yourself from the workspace",
        )
    membership.status = "deleted"
    session.add(membership)
    session.commit()


def create_workspace_invitation(
    session: Session,
    auth: AuthContext,
    *,
    email: str | None,
    role: str,
    days: int,
    settings: Settings,
) -> dict[str, Any]:
    if role == "owner" and auth.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only owners can invite with owner role",
        )
    created = create_invitation(
        session,
        workspace_id=auth.workspace_id,
        created_by_user_id=auth.user_id if auth.user_id else None,
        email=email,
        role=role,
        days=days,
    )
    session.commit()

    if created.invitation.email and created.token:
        workspace = session.get(Workspace, auth.workspace_id)
        inviter = session.get(User, auth.user_id) if auth.user_id else None
        try:
            send_invitation_email(
                settings,
                to_email=created.invitation.email,
                workspace_name=workspace.display_name if workspace else str(auth.workspace_id),
                inviter_name=inviter.display_name if inviter else None,
                role=created.invitation.role,
                token=created.token,
                expires_days=days,
            )
        except EmailDeliveryError as exc:
            logger.warning("invitation email delivery failed: %s", exc)

    return {
        "id": str(created.invitation.id),
        "email": created.invitation.email,
        "role": created.invitation.role,
        "status": created.invitation.status,
        "expires_at": created.invitation.expires_at.isoformat(),
        "token": created.token,
    }


def list_workspace_invitations(session: Session, auth: AuthContext) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(WorkspaceInvitation)
        .where(WorkspaceInvitation.workspace_id == auth.workspace_id)
        .where(WorkspaceInvitation.status == "pending")
        .order_by(WorkspaceInvitation.created_at.desc())
    ).all()
    return [
        {
            "id": str(invitation.id),
            "email": invitation.email,
            "role": invitation.role,
            "status": invitation.status,
            "expires_at": invitation.expires_at.isoformat(),
        }
        for invitation in rows
    ]


def revoke_workspace_invitation(
    session: Session,
    auth: AuthContext,
    *,
    invitation_id: uuid.UUID,
) -> None:
    invitation = session.scalar(
        select(WorkspaceInvitation)
        .where(WorkspaceInvitation.id == invitation_id)
        .where(WorkspaceInvitation.workspace_id == auth.workspace_id)
    )
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invitation not found")
    if invitation.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="invitation is not pending",
        )
    invitation.status = "revoked"
    session.add(invitation)
    session.commit()


def _upsert_external_user(
    session: Session,
    *,
    email: str,
    display_name: str | None,
    provider: str,
    uid: str,
    default_role: str,
) -> tuple[User, uuid.UUID, str | None]:
    normalized_email = email.strip().lower()
    user = session.scalar(select(User).where(User.email == normalized_email).limit(1))
    if user is None:
        user = User(
            email=normalized_email,
            display_name=display_name,
            password_hash=None,
            status="active",
            external_auth_provider=provider,
            external_auth_uid=uid,
        )
        session.add(user)
        session.flush()
        workspace = ensure_default_workspace(session)
        membership = session.scalar(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace.id)
            .where(WorkspaceMembership.user_id == user.id)
            .limit(1)
        )
        if membership is None:
            is_first = (
                session.scalar(
                    select(WorkspaceMembership)
                    .where(WorkspaceMembership.workspace_id == workspace.id)
                    .limit(1)
                )
                is None
            )
            membership = WorkspaceMembership(
                workspace_id=workspace.id,
                user_id=user.id,
                role="owner" if is_first else default_role,
                status="active",
            )
            session.add(membership)
            session.flush()
    else:
        user.display_name = display_name
        user.external_auth_provider = provider
        user.external_auth_uid = uid
        session.add(user)
        session.flush()

    membership = session.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.user_id == user.id)
        .where(WorkspaceMembership.status == "active")
        .limit(1)
    )
    return (
        user,
        membership.workspace_id if membership else DEFAULT_WORKSPACE_ID,
        (membership.role if membership else None),
    )


def login_ldap_user(
    session: Session,
    *,
    login: str,
    password: str,
    settings: Settings,
) -> dict[str, Any]:
    if not settings.ragrig_ldap_enabled:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="LDAP not enabled")
    try:
        info = authenticate_ldap(login, password, settings)
    except LdapAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user, workspace_id, role = _upsert_external_user(
        session,
        email=info.email,
        display_name=info.display_name,
        provider="ldap",
        uid=info.uid,
        default_role=settings.ragrig_ldap_default_role,
    )
    created = create_user_session(
        session,
        workspace_id=workspace_id,
        user_id=user.id,
        expires_at=expires_in(days=settings.ragrig_auth_session_days),
        scopes=["*"],
    )
    session.commit()
    return _auth_payload(
        token=created.token,
        user=user,
        user_id=user.id,
        workspace_id=workspace_id,
        role=role,
    )


def oidc_authorization(settings: Settings) -> dict[str, str]:
    if not settings.ragrig_oidc_enabled:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="OIDC not enabled")
    state = generate_state()
    try:
        url = build_authorization_url(settings, state)
    except OidcAuthError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    _oidc_states[state] = state
    return {"authorization_url": url, "state": state}


def oidc_callback(session: Session, *, code: str, state: str, settings: Settings) -> dict[str, Any]:
    if not settings.ragrig_oidc_enabled:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="OIDC not enabled")
    if state not in _oidc_states:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid or expired state",
        )
    _oidc_states.pop(state, None)

    try:
        info = exchange_code(settings, code)
    except OidcAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user, workspace_id, role = _upsert_external_user(
        session,
        email=info.email,
        display_name=info.display_name,
        provider=info.provider,
        uid=info.uid,
        default_role=settings.ragrig_oidc_default_role,
    )
    created = create_user_session(
        session,
        workspace_id=workspace_id,
        user_id=user.id,
        expires_at=expires_in(days=settings.ragrig_auth_session_days),
        scopes=["*"],
    )
    session.commit()
    return _auth_payload(
        token=created.token,
        user=user,
        user_id=user.id,
        workspace_id=workspace_id,
        role=role,
    )


def setup_mfa(session: Session, auth: AuthContext, settings: Settings) -> dict[str, Any]:
    if auth.user_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API keys cannot use MFA")
    user = session.get(User, auth.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    secret = generate_totp_secret()
    plain_codes, hashed_codes = generate_backup_codes(settings.ragrig_mfa_backup_code_count)
    uri = totp_provisioning_uri(secret, user.email or str(user.id), settings)
    qr_b64 = totp_qr_png_b64(uri)

    user.totp_secret = secret
    user.totp_backup_codes = hashed_codes
    session.add(user)
    session.commit()
    return {"provisioning_uri": uri, "qr_png_b64": qr_b64, "backup_codes": plain_codes}


def confirm_mfa(session: Session, auth: AuthContext, *, code: str) -> dict[str, bool]:
    if auth.user_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API keys cannot use MFA")
    user = session.get(User, auth.user_id)
    if user is None or not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MFA setup not initiated",
        )
    if not verify_totp(user.totp_secret, code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid TOTP code")
    user.mfa_enabled = True
    session.add(user)
    session.commit()
    return {"mfa_enabled": True}


def disable_mfa(session: Session, auth: AuthContext, *, code: str) -> dict[str, bool]:
    if auth.user_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API keys cannot use MFA")
    user = session.get(User, auth.user_id)
    if user is None or not user.mfa_enabled or not user.totp_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is not enabled")
    if not verify_totp(user.totp_secret, code):
        remaining = consume_backup_code(code, list(user.totp_backup_codes))
        if remaining is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid code")
        user.totp_backup_codes = remaining

    user.mfa_enabled = False
    user.totp_secret = None
    user.totp_backup_codes = []
    session.add(user)
    session.commit()
    return {"mfa_enabled": False}


def complete_mfa_challenge(
    session: Session,
    *,
    session_token: str,
    code: str,
    settings: Settings,
) -> dict[str, Any]:
    user_session = verify_session_token(session, session_token)
    if user_session is None or "mfa:pending" not in user_session.scopes:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired MFA challenge token",
        )

    user = session.get(User, user_session.user_id)
    if user is None or not user.mfa_enabled or not user.totp_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA not configured")

    if not verify_totp(user.totp_secret, code):
        remaining = consume_backup_code(code, list(user.totp_backup_codes))
        if remaining is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid MFA code")
        user.totp_backup_codes = remaining
        session.add(user)

    user_session.revoked_at = datetime.now(UTC)
    session.add(user_session)

    created = create_user_session(
        session,
        workspace_id=user_session.workspace_id,
        user_id=user.id,
        expires_at=expires_in(days=settings.ragrig_auth_session_days),
        scopes=["*"],
    )
    session.commit()
    role = role_for(session, user.id, created.session.workspace_id)
    return _auth_payload(
        token=created.token,
        user=user,
        user_id=user.id,
        workspace_id=created.session.workspace_id,
        role=role,
    )


def delete_own_account(session: Session, authorization: str | None) -> None:
    token = get_session_token(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    user_session = verify_session_token(session, token)
    if user_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired token",
        )
    erase_user(session, user_session.user_id)
    session.commit()


def erase_workspace_member(
    session: Session,
    auth: AuthContext,
    *,
    target_user_id: uuid.UUID,
) -> None:
    if auth.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="only owners can erase user accounts",
        )
    if auth.user_id is not None and auth.user_id == target_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="use DELETE /auth/users/me to erase your own account",
        )
    user = session.get(User, target_user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    erase_user(session, target_user_id)
    session.commit()


def api_key_payload(key: ApiKey) -> dict[str, Any]:
    return {
        "id": str(key.id),
        "name": key.name,
        "prefix": key.prefix,
        "scopes": key.scopes,
        "created_at": key.created_at.isoformat(),
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "expires_at": key.expires_at.isoformat() if key.expires_at else None,
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
    }


def create_workspace_api_key(
    session: Session,
    auth: AuthContext,
    *,
    name: str,
    scopes: list[str],
    expires_days: int | None,
) -> dict[str, Any]:
    expires_at = None
    if expires_days is not None:
        expires_at = datetime.now(UTC) + timedelta(days=expires_days)
    created = create_api_key(
        session,
        workspace_id=auth.workspace_id,
        name=name,
        created_by_user_id=auth.user_id,
        scopes=scopes,
        expires_at=expires_at,
    )
    session.commit()
    return {**api_key_payload(created.api_key), "token": created.token}


def list_workspace_api_keys(
    session: Session,
    auth: AuthContext,
    *,
    include_revoked: bool,
) -> list[dict[str, Any]]:
    statement = select(ApiKey).where(ApiKey.workspace_id == auth.workspace_id)
    if not include_revoked:
        statement = statement.where(ApiKey.revoked_at.is_(None))
    statement = statement.order_by(ApiKey.created_at.desc())
    return [api_key_payload(key) for key in session.scalars(statement).all()]


def revoke_workspace_api_key(session: Session, auth: AuthContext, *, key_id: uuid.UUID) -> None:
    key = session.scalar(
        select(ApiKey).where(ApiKey.id == key_id).where(ApiKey.workspace_id == auth.workspace_id)
    )
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="api key not found")
    if key.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="api key already revoked")
    key.revoked_at = datetime.now(UTC)
    session.add(key)
    session.commit()


def erase_user(session: Session, user_id: uuid.UUID) -> None:
    for user_session in session.scalars(
        select(UserSession)
        .where(UserSession.user_id == user_id)
        .where(UserSession.revoked_at.is_(None))
    ):
        user_session.revoked_at = datetime.now(UTC)
        session.add(user_session)

    for api_key in session.scalars(
        select(ApiKey)
        .where(ApiKey.created_by_user_id == user_id)
        .where(ApiKey.revoked_at.is_(None))
    ):
        api_key.revoked_at = datetime.now(UTC)
        session.add(api_key)

    session.execute(delete(WorkspaceMembership).where(WorkspaceMembership.user_id == user_id))

    user = session.get(User, user_id)
    if user is not None:
        user.email = None
        user.display_name = None
        user.password_hash = None
        user.external_auth_uid = None
        user.totp_secret = None
        user.totp_backup_codes = []
        user.mfa_enabled = False
        user.status = "deleted"
        session.add(user)

    session.flush()
