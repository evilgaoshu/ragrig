from __future__ import annotations


class ObjectStorageError(RuntimeError):
    pass


class ObjectStorageConfigError(ObjectStorageError):
    pass


class ObjectStorageCredentialError(ObjectStorageError):
    pass


class ObjectStorageRetryableError(ObjectStorageError):
    pass


class ObjectStoragePermanentError(ObjectStorageError):
    pass


def sanitize_error_message(message: str, *, secrets: list[str]) -> str:
    sanitized = message
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    return sanitized
