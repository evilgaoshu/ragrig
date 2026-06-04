from pydantic import Field

from ragrig.settings.base import RagrigBaseSettings


class AuthSettings(RagrigBaseSettings):
    ragrig_auth_enabled: bool = Field(
        default=True,
        description=(
            "Enable authentication enforcement. When False, all requests are treated as "
            "anonymous and routed to the default workspace. Disable only for local dev."
        ),
    )
    ragrig_auth_secret_pepper: str = Field(
        default="",
        description=(
            "HMAC pepper for API keys, sessions, audit hashes, and invitation tokens. "
            "Set RAGRIG_AUTH_SECRET_PEPPER in .env or the runtime environment."
        ),
    )
    ragrig_auth_session_days: int = Field(
        default=30,
        description="Session token lifetime in days.",
    )
    ragrig_auth_login_rate_limit_enabled: bool = Field(
        default=True,
        description="Enable in-process throttling for repeated password login failures.",
    )
    ragrig_auth_login_max_failures: int = Field(
        default=5,
        description="Failed password login attempts allowed per IP/email window.",
    )
    ragrig_auth_login_window_seconds: int = Field(
        default=300,
        description="Window in seconds for password login failure counting.",
    )
    ragrig_auth_login_lockout_seconds: int = Field(
        default=900,
        description="Temporary lockout duration after too many password login failures.",
    )
    ragrig_open_registration: bool = Field(
        default=True,
        description=(
            "Allow anyone to register without an invitation. When False, registration "
            "requires a valid invitation token issued by an admin. Ignored when "
            "ragrig_auth_enabled is False."
        ),
    )


class LdapSettings(RagrigBaseSettings):
    ragrig_ldap_enabled: bool = Field(default=False, description="Enable LDAP authentication.")
    ragrig_ldap_url: str = Field(
        default="ldap://localhost:389",
        description="LDAP server URL, e.g. ldap://ad.corp.example.com:389",
    )
    ragrig_ldap_use_tls: bool = Field(default=True, description="Upgrade connection with StartTLS.")
    ragrig_ldap_bind_dn: str = Field(
        default="",
        description="Service-account DN used for directory searches.",
    )
    ragrig_ldap_bind_password: str = Field(default="", description="Service-account password.")
    ragrig_ldap_search_base: str = Field(
        default="dc=example,dc=com",
        description="Base DN for user searches.",
    )
    ragrig_ldap_user_filter: str = Field(
        default="(mail={login})",
        description=(
            "LDAP search filter template. {login} is replaced with the submitted email/username."
        ),
    )
    ragrig_ldap_attr_email: str = Field(default="mail", description="Attribute holding email.")
    ragrig_ldap_attr_display_name: str = Field(
        default="displayName", description="Attribute holding display name."
    )
    ragrig_ldap_attr_groups: str = Field(
        default="memberOf", description="Attribute holding group DNs."
    )
    ragrig_ldap_default_role: str = Field(
        default="viewer", description="Default workspace role for LDAP users."
    )


class OidcSettings(RagrigBaseSettings):
    ragrig_oidc_enabled: bool = Field(default=False, description="Enable OIDC authentication.")
    ragrig_oidc_provider_name: str = Field(
        default="oidc",
        description="Short label for this provider, e.g. 'google' or 'azure'.",
    )
    ragrig_oidc_issuer: str = Field(
        default="",
        description="OIDC issuer URL, e.g. https://accounts.google.com",
    )
    ragrig_oidc_client_id: str = Field(default="", description="OAuth2 client ID.")
    ragrig_oidc_client_secret: str = Field(default="", description="OAuth2 client secret.")
    ragrig_oidc_redirect_uri: str = Field(
        default="http://localhost:8000/auth/oidc/callback",
        description="Callback URL registered with the IdP.",
    )
    ragrig_oidc_scopes: str = Field(
        default="openid email profile",
        description="Space-separated OIDC scopes.",
    )
    ragrig_oidc_default_role: str = Field(
        default="viewer", description="Default workspace role for OIDC users."
    )


class MfaSettings(RagrigBaseSettings):
    ragrig_mfa_issuer: str = Field(
        default="RAGRig",
        description="Issuer name shown in authenticator apps.",
    )
    ragrig_mfa_backup_code_count: int = Field(
        default=8, description="Number of one-time backup codes generated on MFA setup."
    )
