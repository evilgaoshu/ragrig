"""Confluence Cloud connector.

Pulls space content via the Confluence REST API (``/wiki/rest/api/content``).
Authentication uses an Atlassian API token + admin email (basic auth). Page
bodies are returned in storage (XHTML) format; downstream parsers convert to
text.

Configuration shape (the only required field is ``base_url``)::

    {
        "base_url": "https://example.atlassian.net/wiki",
        "space_key": "DOCS",
        "email": "env:CONFLUENCE_EMAIL",
        "api_token": "env:CONFLUENCE_API_TOKEN",
        "page_size": 50,
    }
"""

from ragrig.plugins.sources.confluence.config import ConfluenceSourceConfig
from ragrig.plugins.sources.confluence.errors import (
    ConfluenceAuthError,
    ConfluenceConfigError,
    ConfluenceSourceError,
)
from ragrig.plugins.sources.confluence.scanner import (
    ConfluenceItem,
    ConfluenceScanResult,
    scan_confluence_pages,
)

__all__ = [
    "ConfluenceAuthError",
    "ConfluenceConfigError",
    "ConfluenceItem",
    "ConfluenceScanResult",
    "ConfluenceSourceConfig",
    "ConfluenceSourceError",
    "scan_confluence_pages",
]
