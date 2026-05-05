from __future__ import annotations


class S3SourceError(RuntimeError):
    pass


class S3ConfigError(S3SourceError):
    pass


class S3CredentialError(S3SourceError):
    pass


class S3RetryableError(S3SourceError):
    pass


class S3PermanentError(S3SourceError):
    pass


def sanitize_error_message(message: str, *, secrets: list[str]) -> str:
    sanitized = message
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    return sanitized
