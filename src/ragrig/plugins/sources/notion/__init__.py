"""Notion connector.

Uses the public Notion API (``POST /v1/search``) to enumerate pages and
databases the integration has been shared with, then ``GET /v1/blocks/{id}/children``
to extract paragraph-level text. Authentication uses an internal integration
bearer token.

Configuration shape::

    {
        "api_token": "env:NOTION_API_KEY",
        "page_size": 50,
        "filter": "page" | "database" | None
    }
"""

from ragrig.plugins.sources.notion.config import NotionSourceConfig
from ragrig.plugins.sources.notion.errors import (
    NotionAuthError,
    NotionConfigError,
    NotionSourceError,
)
from ragrig.plugins.sources.notion.scanner import (
    NotionItem,
    NotionScanResult,
    scan_notion_pages,
)

__all__ = [
    "NotionAuthError",
    "NotionConfigError",
    "NotionItem",
    "NotionScanResult",
    "NotionSourceConfig",
    "NotionSourceError",
    "scan_notion_pages",
]
