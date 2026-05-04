from __future__ import annotations

from collections.abc import Mapping

from pydantic import Field, field_validator

from ragrig.plugins.manifest import PluginConfigModel
from ragrig.plugins.sources.s3.errors import S3ConfigError


class S3SourceConfig(PluginConfigModel):
    bucket: str
    prefix: str = ""
    endpoint_url: str | None = None
    region: str | None = None
    use_path_style: bool = False
    verify_tls: bool = True
    access_key: str
    secret_key: str
    session_token: str | None = None
    include_patterns: list[str] = []
    exclude_patterns: list[str] = []
    max_object_size_mb: int = Field(default=50, gt=0)
    page_size: int = Field(default=1000, gt=0, le=1000)
    max_retries: int = Field(default=3, ge=0)
    connect_timeout_seconds: int = Field(default=10, gt=0)
    read_timeout_seconds: int = Field(default=30, gt=0)

    @field_validator("bucket")
    @classmethod
    def validate_bucket(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("bucket must not be empty")
        if "/" in normalized:
            raise ValueError("bucket must not contain path separators")
        return normalized

    @field_validator("prefix")
    @classmethod
    def normalize_prefix(cls, value: str) -> str:
        normalized = value.strip().lstrip("/")
        if normalized == ".":
            raise ValueError("prefix must not be '.'")
        return normalized.rstrip("/")

    @field_validator("endpoint_url")
    @classmethod
    def validate_endpoint_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("endpoint_url must start with http:// or https://")
        return normalized

    @field_validator("region")
    @classmethod
    def normalize_region(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("include_patterns", "exclude_patterns")
    @classmethod
    def validate_patterns(cls, value: list[str]) -> list[str]:
        for pattern in value:
            if not pattern.strip():
                raise ValueError("patterns must not be empty")
        return value

    @field_validator("access_key", "secret_key", "session_token")
    @classmethod
    def validate_secret_ref(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith("env:"):
            raise ValueError("secret values must use env:SECRET_NAME references")
        return value


class ResolvedS3Credentials(PluginConfigModel):
    access_key: str
    secret_key: str
    session_token: str | None = None


def resolve_s3_credentials(
    config: S3SourceConfig, *, env: Mapping[str, str]
) -> ResolvedS3Credentials:
    return ResolvedS3Credentials(
        access_key=_resolve_secret_ref(config.access_key, env=env),
        secret_key=_resolve_secret_ref(config.secret_key, env=env),
        session_token=(
            _resolve_secret_ref(config.session_token, env=env)
            if config.session_token is not None
            else None
        ),
    )


def redact_s3_config(config: dict[str, object]) -> dict[str, object]:
    redacted = dict(config)
    for key in ("access_key", "secret_key", "session_token"):
        if (
            key in redacted
            and isinstance(redacted[key], str)
            and not str(redacted[key]).startswith("env:")
        ):
            redacted[key] = "[redacted]"
    return redacted


def _resolve_secret_ref(value: str, *, env: Mapping[str, str]) -> str:
    secret_name = value.removeprefix("env:")
    if secret_name not in env:
        raise S3ConfigError(f"Missing required secret reference: {secret_name}")
    resolved = env[secret_name]
    if not resolved:
        raise S3ConfigError(f"Secret reference {secret_name} is empty")
    return resolved
