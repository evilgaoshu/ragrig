from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from ragrig.config import Settings, get_settings
from ragrig.db.session import get_session
from ragrig.deps import AuthContext, require_admin_auth, require_auth
from ragrig.routers.runtime import get_auth_login_limiter
from ragrig.services import auth as auth_service

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


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(
    body: RegisterRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthResponse:
    return AuthResponse(
        **auth_service.register_account(
            session,
            email=body.email,
            password=body.password,
            display_name=body.display_name,
            invitation_token=body.invitation_token,
            settings=settings,
        )
    )


@router.post("/login", response_model=AuthResponse)
def login(
    body: LoginRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    auth_login_limiter: Annotated[object, Depends(get_auth_login_limiter)],
) -> AuthResponse:
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    return AuthResponse(
        **auth_service.login_password(
            session,
            email=body.email,
            password=body.password,
            settings=settings,
            ip=ip,
            user_agent=ua,
            login_limiter=auth_login_limiter,
        )
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    session: Annotated[Session, Depends(get_session)] = None,  # type: ignore[assignment]
) -> None:
    auth_service.logout_session(session, authorization)


@router.get("/me", response_model=MeResponse)
def me(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    session: Annotated[Session, Depends(get_session)] = None,  # type: ignore[assignment]
    settings: Annotated[Settings, Depends(get_settings)] = None,  # type: ignore[assignment]
) -> MeResponse:
    return MeResponse(
        **auth_service.current_user(session, authorization=authorization, settings=settings)
    )


# ── User management ──────────────────────────────────────────────────────────


@router.get("/workspace/members", response_model=list[MemberResponse])
def list_members(
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_auth)],
) -> list[MemberResponse]:
    """List all active members in the caller's workspace."""
    return [MemberResponse(**item) for item in auth_service.list_members(session, auth)]


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
    return MemberResponse(
        **auth_service.update_member_role(
            session,
            auth,
            target_user_id=target_user_id,
            role=body.role,
        )
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
    auth_service.remove_member(session, auth, target_user_id=target_user_id)


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
    settings: Annotated[Settings, Depends(get_settings)],
) -> InvitationResponse:
    """Create an invitation link. Requires admin or owner."""
    return InvitationResponse(
        **auth_service.create_workspace_invitation(
            session,
            auth,
            email=body.email,
            role=body.role,
            days=body.days,
            settings=settings,
        )
    )


@router.get("/workspace/invitations", response_model=list[InvitationResponse])
def list_workspace_invitations(
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> list[InvitationResponse]:
    """List pending invitations for this workspace. Requires admin or owner."""
    return [
        InvitationResponse(**item)
        for item in auth_service.list_workspace_invitations(session, auth)
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
    auth_service.revoke_workspace_invitation(session, auth, invitation_id=invitation_id)


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
    return AuthResponse(
        **auth_service.login_ldap_user(
            session,
            login=body.login,
            password=body.password,
            settings=settings,
        )
    )


# ── OIDC login ────────────────────────────────────────────────────────────────


class OidcAuthorizeResponse(BaseModel):
    authorization_url: str
    state: str


@router.get("/oidc/authorize", response_model=OidcAuthorizeResponse)
def oidc_authorize(
    settings: Annotated[Settings, Depends(get_settings)],
) -> OidcAuthorizeResponse:
    """Return the IdP authorization URL. Redirect the browser there to start OIDC flow."""
    return OidcAuthorizeResponse(**auth_service.oidc_authorization(settings))


@router.get("/oidc/callback", response_model=AuthResponse)
def oidc_callback(
    code: Annotated[str, Query()],
    state: Annotated[str, Query()],
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthResponse:
    """Handle the IdP callback: exchange code, upsert user, return session token."""
    return AuthResponse(
        **auth_service.oidc_callback(
            session,
            code=code,
            state=state,
            settings=settings,
        )
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
    return MfaSetupResponse(**auth_service.setup_mfa(session, auth, settings))


@router.post("/mfa/confirm", response_model=MfaStatusResponse)
def mfa_confirm(
    body: MfaVerifyRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    session: Annotated[Session, Depends(get_session)],
) -> MfaStatusResponse:
    """Activate MFA by verifying the first TOTP code from the authenticator app."""
    return MfaStatusResponse(**auth_service.confirm_mfa(session, auth, code=body.code))


@router.post("/mfa/disable", response_model=MfaStatusResponse)
def mfa_disable(
    body: MfaVerifyRequest,
    auth: Annotated[AuthContext, Depends(require_auth)],
    session: Annotated[Session, Depends(get_session)],
) -> MfaStatusResponse:
    """Disable MFA after verifying the current TOTP code or a backup code."""
    return MfaStatusResponse(**auth_service.disable_mfa(session, auth, code=body.code))


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
    return AuthResponse(
        **auth_service.complete_mfa_challenge(
            session,
            session_token=body.session_token,
            code=body.code,
            settings=settings,
        )
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
    auth_service.delete_own_account(session, authorization)


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
    auth_service.erase_workspace_member(session, auth, target_user_id=target_user_id)


# ── API key management ────────────────────────────────────────────────────────


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    prefix: str
    scopes: list[str]
    created_at: str
    last_used_at: str | None
    expires_at: str | None
    revoked_at: str | None


class CreatedApiKeyResponse(ApiKeyResponse):
    token: str


class CreateApiKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    scopes: list[str] = Field(default_factory=list)
    expires_days: int | None = Field(default=None, ge=1, le=3650)


@router.post("/api-keys", response_model=CreatedApiKeyResponse, status_code=status.HTTP_201_CREATED)
def create_workspace_api_key(
    body: CreateApiKeyRequest,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> CreatedApiKeyResponse:
    """Create a new API key for the workspace. Requires admin or owner."""
    return CreatedApiKeyResponse(
        **auth_service.create_workspace_api_key(
            session,
            auth,
            name=body.name,
            scopes=body.scopes,
            expires_days=body.expires_days,
        )
    )


@router.get("/api-keys", response_model=list[ApiKeyResponse])
def list_workspace_api_keys(
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_admin_auth)],
    include_revoked: bool = False,
) -> list[ApiKeyResponse]:
    """List API keys for the workspace. Requires admin or owner."""
    return [
        ApiKeyResponse(**item)
        for item in auth_service.list_workspace_api_keys(
            session,
            auth,
            include_revoked=include_revoked,
        )
    ]


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_workspace_api_key(
    key_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> None:
    """Revoke an API key. Requires admin or owner."""
    auth_service.revoke_workspace_api_key(session, auth, key_id=key_id)
