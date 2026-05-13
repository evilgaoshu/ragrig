from __future__ import annotations


class GoogleWorkspaceSourceError(RuntimeError):
    pass


class GoogleWorkspaceConfigError(GoogleWorkspaceSourceError):
    pass


class GoogleWorkspaceCredentialError(GoogleWorkspaceSourceError):
    pass


class GoogleWorkspaceRetryableError(GoogleWorkspaceSourceError):
    pass


class GoogleWorkspacePermanentError(GoogleWorkspaceSourceError):
    pass


def _sanitize_message(message: str, secrets: list[str]) -> str:
    sanitized = message
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    return sanitized
