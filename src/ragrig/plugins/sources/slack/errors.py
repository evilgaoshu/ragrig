"""Error types for the Slack source plugin."""

from __future__ import annotations


class SlackSourceError(Exception):
    """Base error for the Slack connector."""


class SlackAuthError(SlackSourceError):
    """Credential resolution or HTTP 401/403 from Slack API."""


class SlackConfigError(SlackSourceError):
    """Static configuration is invalid (missing keys, bad channel, etc.)."""
