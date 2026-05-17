"""Confluence Cloud page scanner.

``scan_confluence_pages`` lists pages in a space (or all spaces) via the
REST API and returns ``ConfluenceItem`` records. The HTTP transport is
pluggable so tests can inject a stub instead of mounting a real httpx client.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Mapping

from ragrig.plugins.sources.confluence.config import ConfluenceSourceConfig
from ragrig.plugins.sources.confluence.errors import (
    ConfluenceAuthError,
    ConfluenceConfigError,
)

# An HTTP transport is a callable taking (url, headers, params) and returning
# (status_code, json_body). The default real implementation uses httpx.
HttpTransport = Callable[[str, Mapping[str, str], Mapping[str, object]], tuple[int, dict[str, Any]]]


@dataclass(frozen=True)
class ConfluenceItem:
    item_id: str
    title: str
    space_key: str | None
    version: int
    updated_at: datetime
    web_url: str
    body_storage: str
    parent_id: str | None = None


@dataclass(frozen=True)
class ConfluenceScanResult:
    discovered: list[ConfluenceItem] = field(default_factory=list)
    next_cursor: str | None = None
    total_count: int = 0


def _resolve_env(value: str, env: Mapping[str, str]) -> str:
    if value.startswith("env:"):
        name = value.removeprefix("env:")
        resolved = env.get(name)
        if resolved is None:
            raise ConfluenceAuthError(f"missing required env: {name}")
        return resolved
    return value


def _auth_header(email: str, token: str) -> str:
    raw = f"{email}:{token}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def _default_httpx_transport(
    url: str, headers: Mapping[str, str], params: Mapping[str, object]
) -> tuple[int, dict[str, Any]]:  # pragma: no cover - real HTTP path
    import httpx

    resp = httpx.get(url, headers=dict(headers), params=dict(params), timeout=15)
    return resp.status_code, resp.json() if resp.content else {}


def scan_confluence_pages(
    config: ConfluenceSourceConfig | dict[str, object],
    *,
    env: Mapping[str, str],
    cursor: str | None = None,
    transport: HttpTransport | None = None,
) -> ConfluenceScanResult:
    """List pages in the configured space.

    *transport* is for testing — pass a stub returning canned JSON.
    """
    if isinstance(config, dict):
        config = ConfluenceSourceConfig.from_dict(config)
    if not config.base_url:
        raise ConfluenceConfigError("base_url is required")
    email = _resolve_env(config.email, env) if config.email else ""
    token = _resolve_env(config.api_token, env) if config.api_token else ""
    if not email or not token:
        raise ConfluenceAuthError("email and api_token are required (use env:NAME)")

    headers = {
        "Accept": "application/json",
        "Authorization": _auth_header(email, token),
    }
    params: dict[str, object] = {
        "limit": int(config.page_size),
        "expand": "body.storage,version,space",
    }
    if config.space_key:
        params["spaceKey"] = config.space_key
    if cursor is not None:
        params["start"] = int(cursor)

    url = f"{config.base_url}/rest/api/content"
    fetch = transport or _default_httpx_transport
    status, body = fetch(url, headers, params)
    if status == 401 or status == 403:
        raise ConfluenceAuthError(f"authentication failed: HTTP {status}")
    if status >= 400:
        raise ConfluenceConfigError(f"confluence returned HTTP {status}")

    results = body.get("results") or []
    items: list[ConfluenceItem] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        version = row.get("version") or {}
        space = row.get("space") or {}
        body_field = (row.get("body") or {}).get("storage") or {}
        links = row.get("_links") or {}
        updated_raw = version.get("when") or row.get("updatedAt") or ""
        try:
            updated_at = datetime.fromisoformat(updated_raw.replace("Z", "+00:00"))
        except Exception:
            from datetime import UTC

            updated_at = datetime.now(UTC)
        items.append(
            ConfluenceItem(
                item_id=str(row.get("id") or ""),
                title=str(row.get("title") or ""),
                space_key=str(space.get("key")) if space.get("key") else None,
                version=int(version.get("number") or 1),
                updated_at=updated_at,
                web_url=f"{config.base_url}{links.get('webui', '')}"
                if links.get("webui")
                else config.base_url,
                body_storage=str(body_field.get("value") or ""),
                parent_id=None,
            )
        )

    # Confluence v1 pagination: next start = current start + size returned
    next_cursor: str | None = None
    size = int(body.get("size") or len(results))
    start = int(body.get("start") or (int(cursor) if cursor else 0))
    if "_links" in body and isinstance(body["_links"], dict) and body["_links"].get("next"):
        next_cursor = str(start + size)
    total = int(body.get("totalSize") or body.get("limit") or size)
    return ConfluenceScanResult(discovered=items, next_cursor=next_cursor, total_count=total)
