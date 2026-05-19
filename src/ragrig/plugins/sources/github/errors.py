"""Error types for the GitHub source plugin."""

from __future__ import annotations


class GithubSourceError(Exception):
    """Base error for the GitHub connector."""


class GithubAuthError(GithubSourceError):
    """Credential resolution or HTTP 401/403 from GitHub."""


class GithubConfigError(GithubSourceError):
    """Static configuration is invalid (missing keys, bad repo, etc.)."""
