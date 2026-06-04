from functools import lru_cache
from typing import TypeVar

from ragrig.settings import (
    SETTINGS_CONFIG,
    AppSettings,
    AuthSettings,
    CorsSettings,
    DatabaseSettings,
    EmailSettings,
    LdapSettings,
    MfaSettings,
    ObservabilitySettings,
    OidcSettings,
    PathPolicySettings,
    RateLimitSettings,
    RetentionSettings,
    RuntimePolicySettings,
    TaskQueueSettings,
    VectorSettings,
    WebhookSettings,
)
from ragrig.settings.database import DEFAULT_DATABASE_URL

_PROTECTED_APP_ENVS = {"prod", "production", "staging", "stage", "preview", "canary"}
_SettingsSectionT = TypeVar("_SettingsSectionT")


class Settings(
    AppSettings,
    DatabaseSettings,
    VectorSettings,
    AuthSettings,
    LdapSettings,
    OidcSettings,
    MfaSettings,
    RuntimePolicySettings,
    ObservabilitySettings,
    CorsSettings,
    PathPolicySettings,
    EmailSettings,
    WebhookSettings,
    TaskQueueSettings,
    RateLimitSettings,
    RetentionSettings,
):
    """Aggregate runtime settings.

    Field names stay flat for compatibility with existing callers and
    environment variables, while each functional domain lives in its own
    Settings class under ``ragrig.settings``.
    """

    model_config = SETTINGS_CONFIG

    @property
    def app(self) -> AppSettings:
        return self._section(AppSettings)

    @property
    def database(self) -> DatabaseSettings:
        return self._section(DatabaseSettings)

    @property
    def vector(self) -> VectorSettings:
        return self._section(VectorSettings)

    @property
    def auth(self) -> AuthSettings:
        return self._section(AuthSettings)

    @property
    def ldap(self) -> LdapSettings:
        return self._section(LdapSettings)

    @property
    def oidc(self) -> OidcSettings:
        return self._section(OidcSettings)

    @property
    def mfa(self) -> MfaSettings:
        return self._section(MfaSettings)

    @property
    def observability(self) -> ObservabilitySettings:
        return self._section(ObservabilitySettings)

    @property
    def task_queue(self) -> TaskQueueSettings:
        return self._section(TaskQueueSettings)

    @property
    def rate_limit(self) -> RateLimitSettings:
        return self._section(RateLimitSettings)

    @property
    def retention(self) -> RetentionSettings:
        return self._section(RetentionSettings)

    def _section(self, section_type: type[_SettingsSectionT]) -> _SettingsSectionT:
        values = {name: getattr(self, name) for name in section_type.model_fields}
        return section_type.model_validate(values)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def assert_database_url_safe(settings: Settings) -> None:
    if settings.app_env.strip().lower() not in _PROTECTED_APP_ENVS:
        return
    if _normalized_database_url(settings.database_url) == _normalized_database_url(
        DEFAULT_DATABASE_URL
    ):
        raise RuntimeError(
            "DATABASE_URL must be set to environment-specific credentials in protected "
            f"app environments; the default development database URL is not allowed "
            f"when APP_ENV={settings.app_env!r}."
        )


def _normalized_database_url(value: str) -> str:
    if value.startswith("postgresql+psycopg://"):
        return value.replace("postgresql+psycopg://", "postgresql://", 1)
    return value


__all__ = [
    "AppSettings",
    "AuthSettings",
    "CorsSettings",
    "DatabaseSettings",
    "DEFAULT_DATABASE_URL",
    "EmailSettings",
    "LdapSettings",
    "MfaSettings",
    "ObservabilitySettings",
    "OidcSettings",
    "PathPolicySettings",
    "RateLimitSettings",
    "RetentionSettings",
    "RuntimePolicySettings",
    "Settings",
    "TaskQueueSettings",
    "VectorSettings",
    "WebhookSettings",
    "assert_database_url_safe",
    "get_settings",
]
