"""Notion API scanner.

Walks the integration's accessible pages/databases via ``POST /v1/search``,
falling through to ``GET /v1/blocks/{id}/children`` for paragraph extraction.

The HTTP transport is pluggable so tests can pass a stub. The default
transport uses ``httpx`` and is only reached when a real Notion endpoint is
configured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Mapping

from ragrig.plugins.sources.notion.config import NotionSourceConfig
from ragrig.plugins.sources.notion.errors import NotionAuthError, NotionConfigError

# Transport receives (method, url, headers, json_body) and returns
# (status_code, parsed_json).
HttpTransport = Callable[
    [str, str, Mapping[str, str], Mapping[str, object] | None], tuple[int, dict[str, Any]]
]


@dataclass(frozen=True)
class NotionItem:
    item_id: str
    object_kind: str  # "page" | "database"
    title: str
    url: str
    last_edited_at: datetime
    parent_id: str | None
    text: str = ""


@dataclass(frozen=True)
class NotionScanResult:
    discovered: list[NotionItem] = field(default_factory=list)
    next_cursor: str | None = None
    total_count: int = 0


def _resolve_env(value: str, env: Mapping[str, str]) -> str:
    if value.startswith("env:"):
        name = value.removeprefix("env:")
        resolved = env.get(name)
        if resolved is None:
            raise NotionAuthError(f"missing required env: {name}")
        return resolved
    return value


def _default_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    json_body: Mapping[str, object] | None,
) -> tuple[int, dict[str, Any]]:  # pragma: no cover - real HTTP path
    import httpx

    if method.upper() == "POST":
        resp = httpx.post(url, headers=dict(headers), json=json_body, timeout=15)
    else:
        resp = httpx.get(url, headers=dict(headers), timeout=15)
    return resp.status_code, resp.json() if resp.content else {}


def _extract_title(obj: dict[str, Any]) -> str:
    """Pull a human title out of a Notion page/database object.

    Pages expose a ``properties`` map keyed by name; the title property holds a
    list of rich-text spans. Databases store the title at the top level under
    ``title``.
    """
    if obj.get("object") == "database":
        spans = obj.get("title") or []
        return "".join(span.get("plain_text", "") for span in spans if isinstance(span, dict))
    props = obj.get("properties") or {}
    for value in props.values():
        if isinstance(value, dict) and value.get("type") == "title":
            spans = value.get("title") or []
            return "".join(span.get("plain_text", "") for span in spans if isinstance(span, dict))
    return ""


def _extract_blocks_text(blocks: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if not kind:
            continue
        payload = block.get(kind)
        if not isinstance(payload, dict):
            continue
        spans = payload.get("rich_text") or payload.get("text") or []
        text = "".join(span.get("plain_text", "") for span in spans if isinstance(span, dict))
        if text:
            parts.append(text)
    return "\n".join(parts)


def scan_notion_pages(
    config: NotionSourceConfig | dict[str, object],
    *,
    env: Mapping[str, str],
    cursor: str | None = None,
    transport: HttpTransport | None = None,
) -> NotionScanResult:
    """Enumerate pages/databases visible to the configured integration."""
    if isinstance(config, dict):
        config = NotionSourceConfig.from_dict(config)
    token = _resolve_env(config.api_token, env)
    if not token:
        raise NotionAuthError("api_token resolved empty")

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Notion-Version": config.notion_version,
        "Content-Type": "application/json",
    }
    body: dict[str, object] = {"page_size": int(config.page_size)}
    if cursor:
        body["start_cursor"] = cursor
    if config.filter_kind:
        body["filter"] = {"value": config.filter_kind, "property": "object"}

    fetch = transport or _default_transport
    status, payload = fetch("POST", "https://api.notion.com/v1/search", headers, body)
    if status in (401, 403):
        raise NotionAuthError(f"notion auth failed: HTTP {status}")
    if status >= 400:
        raise NotionConfigError(f"notion returned HTTP {status}")

    items: list[NotionItem] = []
    for obj in payload.get("results") or []:
        if not isinstance(obj, dict):
            continue
        kind = obj.get("object") or "page"
        last_edited_raw = obj.get("last_edited_time") or ""
        try:
            last_edited = datetime.fromisoformat(last_edited_raw.replace("Z", "+00:00"))
        except Exception:
            from datetime import UTC

            last_edited = datetime.now(UTC)
        parent_id = None
        parent = obj.get("parent") or {}
        for key in ("page_id", "database_id", "workspace"):
            if isinstance(parent.get(key), str):
                parent_id = str(parent[key])
                break
        items.append(
            NotionItem(
                item_id=str(obj.get("id") or ""),
                object_kind=str(kind),
                title=_extract_title(obj) or "(untitled)",
                url=str(obj.get("url") or ""),
                last_edited_at=last_edited,
                parent_id=parent_id,
                text="",
            )
        )

    next_cursor = payload.get("next_cursor")
    return NotionScanResult(
        discovered=items,
        next_cursor=str(next_cursor) if next_cursor else None,
        total_count=len(items),
    )


def fetch_block_text(
    page_id: str,
    *,
    token: str,
    notion_version: str = "2022-06-28",
    transport: HttpTransport | None = None,
) -> str:
    """Fetch the concatenated paragraph text of a Notion page.

    Useful when ``scan_notion_pages`` is called by an ingester that wants the
    body — Notion's search response omits block content.
    """
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Notion-Version": notion_version,
    }
    fetch = transport or _default_transport
    status, payload = fetch(
        "GET", f"https://api.notion.com/v1/blocks/{page_id}/children", headers, None
    )
    if status in (401, 403):
        raise NotionAuthError(f"notion auth failed fetching blocks: HTTP {status}")
    if status >= 400:
        raise NotionConfigError(f"notion returned HTTP {status} fetching blocks")
    return _extract_blocks_text(payload.get("results") or [])
