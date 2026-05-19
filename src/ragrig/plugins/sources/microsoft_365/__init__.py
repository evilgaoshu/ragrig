"""Microsoft 365 SharePoint / OneDrive source connector.

Enumerates drive items via the Microsoft Graph API using app-only client
credentials (OAuth2 client_credentials grant). No external SDK is required;
authentication and all Graph calls use ``httpx``.

Configuration shape::

    {
        "tenant_id": "00000000-0000-0000-0000-000000000000",
        "client_id": "00000000-0000-0000-0000-000000000000",
        "client_secret": "env:MICROSOFT_365_CLIENT_SECRET",
        "site_url": "https://myorg.sharepoint.com/sites/Engineering",
        "scope": "sharepoint",
        "page_size": 100,
    }

Required Azure AD app permissions (application, not delegated):
- Sites.Read.All (SharePoint)
- Files.Read.All (OneDrive)
"""

from ragrig.plugins.sources.microsoft_365.config import Microsoft365SourceConfig
from ragrig.plugins.sources.microsoft_365.errors import (
    Microsoft365AuthError,
    Microsoft365ConfigError,
    Microsoft365SourceError,
)
from ragrig.plugins.sources.microsoft_365.scanner import (
    M365Item,
    M365ScanResult,
    scan_microsoft_365,
)

__all__ = [
    "M365Item",
    "M365ScanResult",
    "Microsoft365AuthError",
    "Microsoft365ConfigError",
    "Microsoft365SourceConfig",
    "Microsoft365SourceError",
    "scan_microsoft_365",
]
