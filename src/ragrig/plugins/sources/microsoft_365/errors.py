"""Microsoft 365 connector error types."""

from __future__ import annotations


class Microsoft365SourceError(Exception):
    """Base error for all Microsoft 365 connector errors."""


class Microsoft365AuthError(Microsoft365SourceError):
    """Raised when authentication with Microsoft Graph API fails."""


class Microsoft365ConfigError(Microsoft365SourceError):
    """Raised when the connector configuration is invalid or incomplete."""
