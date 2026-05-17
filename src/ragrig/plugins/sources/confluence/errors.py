"""Error types for the Confluence source plugin."""

from __future__ import annotations


class ConfluenceSourceError(Exception):
    """Base error for the Confluence connector."""


class ConfluenceConfigError(ConfluenceSourceError):
    """Static configuration is invalid (missing keys, bad URL, etc.)."""


class ConfluenceAuthError(ConfluenceSourceError):
    """Credential resolution or HTTP 401/403 from Confluence."""
