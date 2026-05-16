from __future__ import annotations


class DatabaseSourceError(RuntimeError):
    """Base class for database source connector failures."""


class DatabaseConfigError(DatabaseSourceError):
    """Raised when database source config or query shape is invalid."""


class DatabaseCredentialError(DatabaseSourceError):
    """Raised when DSN env references cannot be resolved."""


class DatabaseQueryError(DatabaseSourceError):
    """Raised when a configured database query cannot be executed."""


def sanitize_error_message(message: str, *, secrets: list[str]) -> str:
    sanitized = message
    for secret in sorted((value for value in secrets if value), key=len, reverse=True):
        sanitized = sanitized.replace(secret, "[redacted]")
    return sanitized
