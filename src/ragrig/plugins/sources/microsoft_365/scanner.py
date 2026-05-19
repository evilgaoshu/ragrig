"""Microsoft 365 SharePoint / OneDrive scanner.

Enumerates drive items via Microsoft Graph API using app-only client
credentials (OAuth2 client_credentials flow). No external SDK is needed —
authentication and all Graph calls use ``httpx`` which is already a project
dependency.

The HTTP transport is pluggable so tests can inject stubs instead of making
real network calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Mapping

from ragrig.plugins.sources.microsoft_365.config import Microsoft365SourceConfig
from ragrig.plugins.sources.microsoft_365.errors import (
    Microsoft365AuthError,
    Microsoft365ConfigError,
)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# Transport: (method, url, headers, params, json_body) → (status, json)
HttpTransport = Callable[
    [str, str, Mapping[str, str], Mapping[str, object] | None, Mapping[str, object] | None],
    tuple[int, dict[str, Any]],
]


@dataclass(frozen=True)
class M365Item:
    item_id: str
    drive_id: str
    site_id: str | None
    name: str
    web_url: str
    is_folder: bool
    size_bytes: int
    last_modified_at: datetime
    mime_type: str | None
    parent_id: str | None


@dataclass(frozen=True)
class M365ScanResult:
    discovered: list[M365Item] = field(default_factory=list)
    next_cursor: str | None = None
    total_count: int = 0


def _resolve_env(value: str, env: Mapping[str, str]) -> str:
    if value.startswith("env:"):
        name = value.removeprefix("env:")
        resolved = env.get(name)
        if resolved is None:
            raise Microsoft365AuthError(f"missing required env var: {name}")
        return resolved
    return value


def _default_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    params: Mapping[str, object] | None,
    json_body: Mapping[str, object] | None,
) -> tuple[int, dict[str, Any]]:  # pragma: no cover - real HTTP path
    import httpx

    resp = httpx.request(
        method.upper(),
        url,
        headers=dict(headers),
        params=dict(params) if params else None,
        json=json_body,
        timeout=20,
    )
    return resp.status_code, resp.json() if resp.content else {}


def _acquire_token(
    tenant_id: str,
    client_id: str,
    client_secret: str,
    transport: HttpTransport,
) -> str:
    """Obtain an access token via OAuth2 client credentials."""
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    # POST form-encoded body for token request
    form_data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "https://graph.microsoft.com/.default",
    }
    status, body = transport("POST", token_url, {}, None, form_data)  # type: ignore[arg-type]
    if status != 200:
        error = body.get("error_description") or body.get("error") or f"HTTP {status}"
        raise Microsoft365AuthError(f"token acquisition failed: {error}")
    token = body.get("access_token")
    if not token:
        raise Microsoft365AuthError("token response missing access_token")
    return str(token)


def _acquire_token_real(  # pragma: no cover
    tenant_id: str, client_id: str, client_secret: str
) -> str:
    """Real token acquisition using httpx form-encoded POST."""
    import httpx

    resp = httpx.post(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
        },
        timeout=15,
    )
    body = resp.json() if resp.content else {}
    if resp.status_code != 200:
        error = body.get("error_description") or body.get("error") or f"HTTP {resp.status_code}"
        raise Microsoft365AuthError(f"token acquisition failed: {error}")
    token = body.get("access_token")
    if not token:
        raise Microsoft365AuthError("token response missing access_token")
    return str(token)


def _parse_item(item: dict[str, Any], drive_id: str, site_id: str | None) -> M365Item:
    last_mod_raw = item.get("lastModifiedDateTime") or ""
    try:
        last_modified_at = datetime.fromisoformat(last_mod_raw.replace("Z", "+00:00"))
    except Exception:
        from datetime import UTC

        last_modified_at = datetime.now(UTC)

    file_info = item.get("file") or {}
    parent_ref = item.get("parentReference") or {}
    parent_id = str(parent_ref["id"]) if parent_ref.get("id") else None

    return M365Item(
        item_id=str(item.get("id") or ""),
        drive_id=drive_id,
        site_id=site_id,
        name=str(item.get("name") or ""),
        web_url=str(item.get("webUrl") or ""),
        is_folder="folder" in item,
        size_bytes=int(item.get("size") or 0),
        last_modified_at=last_modified_at,
        mime_type=str(file_info.get("mimeType")) if file_info.get("mimeType") else None,
        parent_id=parent_id,
    )


def _list_drive_items(
    drive_id: str,
    site_id: str | None,
    *,
    token: str,
    page_size: int,
    cursor: str | None,
    transport: HttpTransport,
) -> tuple[list[M365Item], str | None]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    params: dict[str, object] = {"$top": page_size}
    cursor_is_url = cursor is not None and cursor.startswith("http")
    if cursor and not cursor_is_url:
        url = f"{_GRAPH_BASE}/drives/{drive_id}/root/children"
        params["$skiptoken"] = cursor
    elif cursor_is_url:
        url = cursor
    else:
        url = f"{_GRAPH_BASE}/drives/{drive_id}/root/children"

    req_params = None if cursor_is_url else params
    status, body = transport("GET", url, headers, req_params, None)
    if status in (401, 403):
        raise Microsoft365AuthError(f"graph auth failed listing drive items: HTTP {status}")
    if status >= 400:
        raise Microsoft365ConfigError(f"graph returned HTTP {status} listing drive {drive_id}")

    items = [
        _parse_item(obj, drive_id, site_id)
        for obj in (body.get("value") or [])
        if isinstance(obj, dict)
    ]
    next_link = body.get("@odata.nextLink")
    return items, str(next_link) if next_link else None


def _list_sharepoint_drives(
    site_id: str,
    *,
    token: str,
    transport: HttpTransport,
) -> list[str]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    status, body = transport("GET", f"{_GRAPH_BASE}/sites/{site_id}/drives", headers, None, None)
    if status in (401, 403):
        raise Microsoft365AuthError(f"graph auth failed listing drives: HTTP {status}")
    if status >= 400:
        raise Microsoft365ConfigError(
            f"graph returned HTTP {status} listing drives for site {site_id}"
        )
    return [str(d["id"]) for d in (body.get("value") or []) if isinstance(d, dict) and d.get("id")]


def _resolve_site_id(
    site_url: str,
    *,
    token: str,
    transport: HttpTransport,
) -> str:
    """Resolve a SharePoint site URL to a Graph site ID."""
    from urllib.parse import urlparse

    parsed = urlparse(site_url)
    hostname = parsed.netloc
    path = parsed.path.rstrip("/") or "/"
    # Graph site lookup: /sites/{hostname}:{path}
    lookup_url = f"{_GRAPH_BASE}/sites/{hostname}:{path}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    status, body = transport("GET", lookup_url, headers, None, None)
    if status in (401, 403):
        raise Microsoft365AuthError(f"graph auth failed resolving site: HTTP {status}")
    if status == 404:
        raise Microsoft365ConfigError(f"SharePoint site not found: {site_url}")
    if status >= 400:
        raise Microsoft365ConfigError(f"graph returned HTTP {status} resolving site {site_url}")
    site_id = body.get("id")
    if not site_id:
        raise Microsoft365ConfigError(f"graph response missing site id for {site_url}")
    return str(site_id)


def _list_onedrive_ids(
    *,
    token: str,
    transport: HttpTransport,
) -> list[str]:
    """List accessible OneDrive drives (users' personal drives)."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    status, body = transport("GET", f"{_GRAPH_BASE}/drives", headers, None, None)
    if status in (401, 403):
        raise Microsoft365AuthError(f"graph auth failed listing OneDrive drives: HTTP {status}")
    if status >= 400:
        raise Microsoft365ConfigError(f"graph returned HTTP {status} listing OneDrive drives")
    return [str(d["id"]) for d in (body.get("value") or []) if isinstance(d, dict) and d.get("id")]


def scan_microsoft_365(
    config: Microsoft365SourceConfig | dict[str, object],
    *,
    env: Mapping[str, str],
    cursor: str | None = None,
    transport: HttpTransport | None = None,
    _token_factory: Callable[[str, str, str], str] | None = None,
) -> M365ScanResult:
    """Scan SharePoint / OneDrive items via Microsoft Graph API.

    *transport* and *_token_factory* are injectable for tests.
    """
    if isinstance(config, dict):
        config = Microsoft365SourceConfig.from_dict(config)

    client_secret = _resolve_env(config.client_secret, env)
    fetch = transport or _default_transport

    if _token_factory is not None:
        token = _token_factory(config.tenant_id, config.client_id, client_secret)
    else:
        token = _acquire_token_real(  # pragma: no cover
            config.tenant_id, config.client_id, client_secret
        )

    # Determine which drive IDs to enumerate
    drive_ids: list[tuple[str, str | None]] = []  # (drive_id, site_id)

    if config.scope in ("sharepoint", "both"):
        if config.site_url:
            site_id = _resolve_site_id(config.site_url, token=token, transport=fetch)
            for drive_id in _list_sharepoint_drives(site_id, token=token, transport=fetch):
                drive_ids.append((drive_id, site_id))
        else:
            # Search all accessible SharePoint sites
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            status, body = fetch("GET", f"{_GRAPH_BASE}/sites?search=*", headers, None, None)
            if status in (401, 403):
                raise Microsoft365AuthError(f"graph auth failed listing sites: HTTP {status}")
            if status >= 400:
                raise Microsoft365ConfigError(f"graph returned HTTP {status} listing sites")
            for site in body.get("value") or []:
                if not isinstance(site, dict) or not site.get("id"):
                    continue
                sid = str(site["id"])
                for drive_id in _list_sharepoint_drives(sid, token=token, transport=fetch):
                    drive_ids.append((drive_id, sid))

    if config.scope in ("onedrive", "both"):
        for drive_id in _list_onedrive_ids(token=token, transport=fetch):
            drive_ids.append((drive_id, None))

    if not drive_ids:
        return M365ScanResult(discovered=[], next_cursor=None, total_count=0)

    # When resuming with a cursor, parse it as "drive_index:next_link"
    drive_index = 0
    drive_cursor: str | None = None
    if cursor:
        try:
            idx_str, _, link = cursor.partition(":")
            drive_index = int(idx_str)
            drive_cursor = link or None
        except Exception:
            drive_index = 0

    all_items: list[M365Item] = []
    next_cursor: str | None = None

    if drive_index < len(drive_ids):
        drive_id, site_id = drive_ids[drive_index]
        items, next_link = _list_drive_items(
            drive_id,
            site_id,
            token=token,
            page_size=config.page_size,
            cursor=drive_cursor,
            transport=fetch,
        )
        all_items.extend(items)
        if next_link:
            next_cursor = f"{drive_index}:{next_link}"
        elif drive_index + 1 < len(drive_ids):
            next_cursor = f"{drive_index + 1}:"

    return M365ScanResult(
        discovered=all_items,
        next_cursor=next_cursor,
        total_count=len(all_items),
    )
