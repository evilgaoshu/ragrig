from __future__ import annotations


class FileshareSourceError(RuntimeError):
    pass


class FileshareConfigError(FileshareSourceError):
    pass


class FileshareCredentialError(FileshareSourceError):
    pass


class FileshareRetryableError(FileshareSourceError):
    pass


class FilesharePermanentError(FileshareSourceError):
    pass


def sanitize_error_message(message: str, *, secrets: list[str]) -> str:
    sanitized = message
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    return sanitized
