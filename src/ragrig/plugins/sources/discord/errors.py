"""Error types for the Discord source plugin."""

from __future__ import annotations


class DiscordSourceError(Exception):
    """Base error for the Discord connector."""


class DiscordAuthError(DiscordSourceError):
    """Credential resolution or HTTP 401/403 from Discord API."""


class DiscordConfigError(DiscordSourceError):
    """Static configuration or API response is invalid."""


class DiscordRateLimitError(DiscordSourceError):
    """Discord returned a rate-limit response."""
