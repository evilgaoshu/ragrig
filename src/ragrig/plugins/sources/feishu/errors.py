"""Feishu connector error types."""

from __future__ import annotations


class FeishuSourceError(Exception):
    """Base error for the Feishu / Lark connector."""


class FeishuConfigError(FeishuSourceError):
    """Static configuration is invalid."""


class FeishuAuthError(FeishuSourceError):
    """Credential resolution failed or tenant_access_token exchange failed."""
