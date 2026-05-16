from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ragrig"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    db_host_port: int = 5432
    db_runtime_host: str = "localhost"
    database_url: str = Field(
        default="postgresql://ragrig:ragrig_dev@localhost:5432/ragrig",
        description="PostgreSQL connection string for RAGRig.",
    )
    vector_backend: str = Field(default="pgvector", description="Vector backend name.")
    qdrant_url: str = Field(
        default="http://localhost:6333",
        description="Qdrant base URL for the optional vector backend.",
    )
    qdrant_api_key: str | None = Field(default=None, description="Optional Qdrant API key.")
    ragrig_auth_enabled: bool = Field(
        default=True,
        description=(
            "Enable authentication enforcement. When False, all requests are treated as "
            "anonymous and routed to the default workspace. Disable only for local dev."
        ),
    )
    ragrig_auth_session_days: int = Field(
        default=30,
        description="Session token lifetime in days.",
    )
    ragrig_open_registration: bool = Field(
        default=True,
        description=(
            "Allow anyone to register without an invitation. When False, registration "
            "requires a valid invitation token issued by an admin. Ignored when "
            "ragrig_auth_enabled is False."
        ),
    )

    # ── LDAP ─────────────────────────────────────────────────────────────────
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

    # ── OIDC ──────────────────────────────────────────────────────────────────
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

    # ── MFA ───────────────────────────────────────────────────────────────────
    ragrig_mfa_issuer: str = Field(
        default="RAGRig",
        description="Issuer name shown in authenticator apps.",
    )
    ragrig_mfa_backup_code_count: int = Field(
        default=8, description="Number of one-time backup codes generated on MFA setup."
    )

    # ── PII redaction ─────────────────────────────────────────────────────────
    ragrig_pii_redaction_enabled: bool = Field(
        default=False,
        description="Redact detected PII patterns from chunk text before storing.",
    )

    ragrig_allow_fake_reranker: bool = Field(
        default=False,
        description=(
            "Allow the deterministic fake reranker fallback in production. "
            "Use only for demos or explicitly accepted degraded environments."
        ),
    )

    # ── Prometheus metrics ────────────────────────────────────────────────────
    ragrig_metrics_enabled: bool = Field(
        default=True,
        description="Expose Prometheus /metrics endpoint.",
    )

    # ── Email (SMTP) ──────────────────────────────────────────────────────────
    ragrig_smtp_enabled: bool = Field(default=False, description="Enable SMTP email delivery.")
    ragrig_smtp_host: str = Field(default="localhost", description="SMTP server host.")
    ragrig_smtp_port: int = Field(default=587, description="SMTP server port.")
    ragrig_smtp_use_tls: bool = Field(default=True, description="Use STARTTLS.")
    ragrig_smtp_username: str = Field(default="", description="SMTP username.")
    ragrig_smtp_password: str = Field(default="", description="SMTP password.")
    ragrig_smtp_from: str = Field(
        default="noreply@ragrig.local",
        description="From address for outbound emails.",
    )
    ragrig_app_base_url: str = Field(
        default="http://localhost:8000",
        description="Public base URL, used to build invitation links.",
    )

    # ── Alert webhooks ────────────────────────────────────────────────────────
    ragrig_webhook_url: str = Field(
        default="",
        description=(
            "Outbound webhook URL. Receives JSON POST on pipeline failure/completion. "
            "Supports Slack Incoming Webhook, generic HTTP endpoints."
        ),
    )
    ragrig_webhook_secret: str = Field(
        default="",
        description="Optional HMAC-SHA256 signing secret for outbound webhooks.",
    )
    ragrig_webhook_on_failure: bool = Field(
        default=True, description="Fire webhook on pipeline/task failure."
    )
    ragrig_webhook_on_completion: bool = Field(
        default=False, description="Fire webhook on pipeline/task completion."
    )

    # ── OpenTelemetry ─────────────────────────────────────────────────────────
    ragrig_otel_enabled: bool = Field(
        default=False,
        description="Enable OpenTelemetry tracing and structured log export.",
    )
    ragrig_otel_endpoint: str = Field(
        default="http://localhost:4318",
        description="OTLP HTTP collector endpoint (e.g. http://otel-collector:4318).",
    )
    ragrig_otel_service_name: str = Field(
        default="ragrig",
        description="Service name reported to the OTel collector.",
    )
    ragrig_log_format: str = Field(
        default="text",
        description="Log format: 'text' (human-readable) or 'json' (structured, for log aggregators).",  # noqa: E501
    )

    # ── Async task queue (ARQ / Redis) ────────────────────────────────────────
    ragrig_task_backend: str = Field(
        default="threadpool",
        description="Task execution backend: 'threadpool' (default) or 'arq' (Redis-backed).",
    )
    ragrig_redis_url: str = Field(
        default="redis://localhost:6379",
        description="Redis URL for the ARQ task queue backend.",
    )
    ragrig_task_queue_max_jobs: int = Field(
        default=10,
        description="Max concurrent jobs in the ARQ worker.",
    )

    @property
    def runtime_database_url(self) -> str:
        if "://" not in self.database_url or not self.database_url.startswith("postgresql"):
            return self.database_url
        parts = urlsplit(self.database_url)
        username = parts.username or ""
        password = parts.password or ""
        auth = username
        if password:
            auth = f"{auth}:{password}"
        if auth:
            auth = f"{auth}@"
        return urlunsplit(
            (
                parts.scheme,
                f"{auth}{self.db_runtime_host}:{self.db_host_port}",
                parts.path,
                parts.query,
                parts.fragment,
            )
        )

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url.startswith("postgresql+psycopg://"):
            return self.database_url
        if self.database_url.startswith("postgresql://"):
            return self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        return self.database_url

    @property
    def sqlalchemy_runtime_database_url(self) -> str:
        if self.runtime_database_url.startswith("postgresql+psycopg://"):
            return self.runtime_database_url
        if self.runtime_database_url.startswith("postgresql://"):
            return self.runtime_database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        return self.runtime_database_url

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
