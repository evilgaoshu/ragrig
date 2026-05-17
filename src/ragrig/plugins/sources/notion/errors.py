"""Notion connector error types."""

from __future__ import annotations


class NotionSourceError(Exception):
    """Base error for the Notion source connector."""


class NotionConfigError(NotionSourceError):
    """Static configuration is invalid."""


class NotionAuthError(NotionSourceError):
    """Credential resolution failed or Notion API returned 401/403."""
