from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ragrig.auth import (
    DEFAULT_WORKSPACE_ID,
    SESSION_TOKEN_PREFIX,
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
from ragrig.config import Settings, get_settings
from ragrig.db.models import (
    ApiKey,
    User,
    UserSession,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from ragrig.db.session import get_session
from ragrig.deps import AuthContext, require_admin_auth, require_auth
from ragrig.email import EmailDeliveryError, send_invitation_email

logger = logging.getLogger(__name__)

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
    mfa_required: bool = False


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
    user = session.get(User, created.session.user_id)

    # If MFA is enrolled, revoke the full-scope session and issue a pending one
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
            user_agent=ua,
        )
        session.commit()
        return AuthResponse(
            token=pending.token,
            user_id=str(user.id),
            email=user.email or "",
            display_name=user.display_name,
            workspace_id=str(pending.session.workspace_id),
            role=None,
            mfa_required=True,
        )

    session.commit()
    role = _role_for(session, created.session.user_id, created.session.workspace_id)
    return AuthResponse(
        token=created.token,
        user_id=str(created.session.user_id),
        email=user.email or "" if user else "",
        display_name=user.display_name if user else None,
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

    if created.invitation.email and created.token:
        _settings = get_settings()
        ws = session.get(Workspace, auth.workspace_id)
        inviter = session.get(User, auth.user_id) if auth.user_id else None
        try:
            send_invitation_email(
                _settings,
                to_email=created.invitation.email,
                workspace_name=ws.display_name if ws else str(auth.workspace_id),
                inviter_name=inviter.display_name if inviter else None,
                role=created.invitation.role,
                token=created.token,
                expires_days=body.days,
            )
        except EmailDeliveryError as exc:
            logger.warning("invitation email delivery failed: %s", exc)

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


# ── LDAP login ────────────────────────────────────────────────────────────────


class LdapLoginRequest(BaseModel):
    login: str = Field(description="Email or LDAP username")
    password: str


@router.post("/login/ldap", response_model=AuthResponse)
def login_ldap(
    body: LdapLoginRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthResponse:
    """Authenticate via LDAP and return a session token.

    Creates a local user record on first login; subsequent logins update
    the display_name from the directory.
    """
    if not settings.ragrig_ldap_enabled:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="LDAP not enabled")
    try:
        info = authenticate_ldap(body.login, body.password, settings)
    except LdapAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    normalized_email = info.email.strip().lower()
    provider_key = "ldap"

    user = session.scalar(select(User).where(User.email == normalized_email).limit(1))
    if user is None:
        user = User(
            email=normalized_email,
            display_name=info.display_name,
            password_hash=None,
            status="active",
            external_auth_provider=provider_key,
            external_auth_uid=info.uid,
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
            role = "owner" if is_first else settings.ragrig_ldap_default_role
            session.add(
                WorkspaceMembership(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    role=role,
                    status="active",
                )
            )
            session.flush()
    else:
        user.display_name = info.display_name
        session.add(user)
        session.flush()

    membership = session.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.user_id == user.id)
        .where(WorkspaceMembership.status == "active")
        .limit(1)
    )
    workspace_id = membership.workspace_id if membership else DEFAULT_WORKSPACE_ID
    role = membership.role if membership else None

    created = create_user_session(
        session,
        workspace_id=workspace_id,
        user_id=user.id,
        expires_at=expires_in(days=settings.ragrig_auth_session_days),
        scopes=["*"],
    )
    session.commit()
    return AuthResponse(
        token=created.token,
        user_id=str(user.id),
        email=user.email or "",
        display_name=user.display_name,
        workspace_id=str(workspace_id),
        role=role,
    )


# ── OIDC login ────────────────────────────────────────────────────────────────

# In-memory state store for OIDC CSRF protection.
# Production deployments should use a Redis-backed store or signed cookies.
_oidc_states: dict[str, str] = {}


class OidcAuthorizeResponse(BaseModel):
    authorization_url: str
    state: str


@router.get("/oidc/authorize", response_model=OidcAuthorizeResponse)
def oidc_authorize(
    settings: Annotated[Settings, Depends(get_settings)],
) -> OidcAuthorizeResponse:
    """Return the IdP authorization URL. Redirect the browser there to start OIDC flow."""
    if not settings.ragrig_oidc_enabled:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="OIDC not enabled")
    state = generate_state()
    try:
        url = build_authorization_url(settings, state)
    except OidcAuthError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    _oidc_states[state] = state
    return OidcAuthorizeResponse(authorization_url=url, state=state)


@router.get("/oidc/callback", response_model=AuthResponse)
def oidc_callback(
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthResponse:
    """Handle the IdP callback: exchange code, upsert user, return session token."""
    if not settings.ragrig_oidc_enabled:
        raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="OIDC not enabled")
    if state not in _oidc_states:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid or expired state"
        )
    _oidc_states.pop(state, None)

    try:
        info = exchange_code(settings, code)
    except OidcAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    normalized_email = info.email.strip().lower()
    user = session.scalar(select(User).where(User.email == normalized_email).limit(1))
    if user is None:
        user = User(
            email=normalized_email,
            display_name=info.display_name,
            password_hash=None,
            status="active",
            external_auth_provider=info.provider,
            external_auth_uid=info.uid,
        )
        session.add(user)
        session.flush()
        workspace = ensure_default_workspace(session)
        is_first = (
            session.scalar(
                select(WorkspaceMembership)
                .where(WorkspaceMembership.workspace_id == workspace.id)
                .limit(1)
            )
            is None
        )
        role = "owner" if is_first else settings.ragrig_oidc_default_role
        session.add(
            WorkspaceMembership(
                workspace_id=workspace.id,
                user_id=user.id,
                role=role,
                status="active",
            )
        )
        session.flush()
    else:
        user.display_name = info.display_name
        user.external_auth_provider = info.provider
        user.external_auth_uid = info.uid
        session.add(user)
        session.flush()

    membership = session.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.user_id == user.id)
        .where(WorkspaceMembership.status == "active")
        .limit(1)
    )
    workspace_id = membership.workspace_id if membership else DEFAULT_WORKSPACE_ID
    role = membership.role if membership else None

    created = create_user_session(
        session,
        workspace_id=workspace_id,
        user_id=user.id,
        expires_at=expires_in(days=settings.ragrig_auth_session_days),
        scopes=["*"],
    )
    session.commit()
    return AuthResponse(
        token=created.token,
        user_id=str(user.id),
        email=user.email or "",
        display_name=user.display_name,
        workspace_id=str(workspace_id),
        role=role,
    )


# ── MFA / TOTP ───────────────────────────────────────────────────────────────


class MfaSetupResponse(BaseModel):
    provisioning_uri: str
    qr_png_b64: str
    backup_codes: list[str]


class MfaVerifyRequest(BaseModel):
    code: str = Field(
        min_length=6, max_length=16, description="6-digit TOTP or 10-char backup code"
    )


class MfaStatusResponse(BaseModel):
    mfa_enabled: bool


@router.post("/mfa/setup", response_model=MfaSetupResponse)
def mfa_setup(
    auth: Annotated[AuthContext, Depends(require_auth)],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> MfaSetupResponse:
    """Initialise TOTP for the current user.

    Returns the provisioning URI, a QR code PNG (base64), and single-use
    backup codes. Call POST /auth/mfa/confirm with a valid code to activate.
    """
    if auth.user_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API keys cannot use MFA")
    user = session.get(User, auth.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    secret = generate_totp_secret()
    plain_codes, hashed_codes = generate_backup_codes(settings.ragrig_mfa_backup_code_count)
    uri = totp_provisioning_uri(secret, user.email or str(user.id), settings)
    qr_b64 = totp_qr_png_b64(uri)

    # Store secret (not yet activated — mfa_enabled remains False until confirmed)
    user.totp_secret = secret
    user.totp_backup_codes = hashed_codes
    session.add(user)
    session.commit()

    return MfaSetupResponse(provisioning_uri=uri, qr_png_b64=qr_b64, backup_codes=plain_codes)


@router.post("/mfa/confirm", response_model=MfaStatusResponse)
def mfa_confirm(
    body: MfaVerifyRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    session: Annotated[Session, Depends(get_session)],
) -> MfaStatusResponse:
    """Activate MFA by verifying the first TOTP code from the authenticator app."""
    if auth.user_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API keys cannot use MFA")
    user = session.get(User, auth.user_id)
    if user is None or not user.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="MFA setup not initiated"
        )
    if not verify_totp(user.totp_secret, body.code):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid TOTP code")
    user.mfa_enabled = True
    session.add(user)
    session.commit()
    return MfaStatusResponse(mfa_enabled=True)


@router.post("/mfa/disable", response_model=MfaStatusResponse)
def mfa_disable(
    body: MfaVerifyRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    session: Annotated[Session, Depends(get_session)],
) -> MfaStatusResponse:
    """Disable MFA after verifying the current TOTP code or a backup code."""
    if auth.user_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API keys cannot use MFA")
    user = session.get(User, auth.user_id)
    if user is None or not user.mfa_enabled or not user.totp_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is not enabled")
    if not verify_totp(user.totp_secret, body.code):
        remaining = consume_backup_code(body.code, list(user.totp_backup_codes))
        if remaining is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid code")
        user.totp_backup_codes = remaining

    user.mfa_enabled = False
    user.totp_secret = None
    user.totp_backup_codes = []
    session.add(user)
    session.commit()
    return MfaStatusResponse(mfa_enabled=False)


class MfaChallengeRequest(BaseModel):
    session_token: str = Field(description="Temporary session token returned by /auth/login")
    code: str = Field(
        min_length=6, max_length=16, description="6-digit TOTP or 10-char backup code"
    )


@router.post("/mfa/challenge", response_model=AuthResponse)
def mfa_challenge(
    body: MfaChallengeRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthResponse:
    """Complete login for MFA-enrolled users.

    Pass the temporary token returned by POST /auth/login together with a
    valid TOTP or backup code. Returns a full-scope session token on success.

    The temporary token is issued with scopes=["mfa:pending"] and is not
    valid for any other endpoint.
    """
    user_session = verify_session_token(session, body.session_token)
    if user_session is None or "mfa:pending" not in user_session.scopes:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or expired MFA challenge token",
        )

    user = session.get(User, user_session.user_id)
    if user is None or not user.mfa_enabled or not user.totp_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA not configured")

    valid = verify_totp(user.totp_secret, body.code)
    if not valid:
        remaining = consume_backup_code(body.code, list(user.totp_backup_codes))
        if remaining is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid MFA code")
        user.totp_backup_codes = remaining
        session.add(user)

    # Revoke the temporary token and issue a full-scope token
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

    role = _role_for(session, user.id, created.session.workspace_id)
    return AuthResponse(
        token=created.token,
        user_id=str(user.id),
        email=user.email or "",
        display_name=user.display_name,
        workspace_id=str(created.session.workspace_id),
        role=role,
    )


# ── Right to erasure (hard delete) ───────────────────────────────────────────


@router.delete("/users/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_own_account(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    session: Annotated[Session, Depends(get_session)] = None,  # type: ignore[assignment]
) -> None:
    """Permanently delete the authenticated user's account and all personal data.

    - Revokes all active sessions and API keys.
    - Removes workspace memberships.
    - Anonymises and soft-deletes the user record (email cleared, status=deleted).
    """
    token = _get_token(authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
        )
    user_session = verify_session_token(session, token)
    if user_session is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired token"
        )
    _erase_user(session, user_session.user_id)
    session.commit()


@router.delete(
    "/workspace/members/{target_user_id}/erase",
    status_code=status.HTTP_204_NO_CONTENT,
)
def erase_workspace_member(
    target_user_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> None:
    """Hard-delete a user: anonymise all PII and revoke access. Requires owner."""
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
    _erase_user(session, target_user_id)
    session.commit()


def _erase_user(session: Session, user_id: uuid.UUID) -> None:
    """Anonymise and hard-delete all personal data for *user_id*."""
    # Revoke all sessions
    for s in session.scalars(
        select(UserSession)
        .where(UserSession.user_id == user_id)
        .where(UserSession.revoked_at.is_(None))
    ):
        s.revoked_at = datetime.now(UTC)
        session.add(s)

    # Revoke all API keys
    for k in session.scalars(
        select(ApiKey)
        .where(ApiKey.created_by_user_id == user_id)
        .where(ApiKey.revoked_at.is_(None))
    ):
        k.revoked_at = datetime.now(UTC)
        session.add(k)

    # Remove workspace memberships
    session.execute(delete(WorkspaceMembership).where(WorkspaceMembership.user_id == user_id))

    # Anonymise and soft-delete the user record
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
