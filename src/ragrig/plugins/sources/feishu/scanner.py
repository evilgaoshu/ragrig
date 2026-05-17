"""Feishu / Lark documentation scanner.

Walks a Lark Wiki space via ``GET /open-apis/wiki/v2/spaces/{space}/nodes`` and
exposes the discovered docx pages as ``FeishuItem`` records. Authentication
exchanges ``app_id`` + ``app_secret`` for a ``tenant_access_token``.

The HTTP transport is pluggable so tests can stub responses without a real
network round-trip.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Mapping

from ragrig.plugins.sources.feishu.config import FeishuSourceConfig
from ragrig.plugins.sources.feishu.errors import FeishuAuthError, FeishuConfigError

HttpTransport = Callable[
    [str, str, Mapping[str, str], Mapping[str, object] | None], tuple[int, dict[str, Any]]
]


@dataclass(frozen=True)
class FeishuItem:
    item_id: str
    obj_token: str
    node_type: str  # "docx" | "doc" | "sheet" | "bitable" etc.
    title: str
    updated_at: datetime
    parent_id: str | None = None


@dataclass(frozen=True)
class FeishuScanResult:
    discovered: list[FeishuItem] = field(default_factory=list)
    next_cursor: str | None = None
    total_count: int = 0


def _resolve_env(value: str, env: Mapping[str, str]) -> str:
    if value.startswith("env:"):
        name = value.removeprefix("env:")
        resolved = env.get(name)
        if resolved is None:
            raise FeishuAuthError(f"missing required env: {name}")
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


def _acquire_tenant_token(
    base_url: str,
    app_id: str,
    app_secret: str,
    transport: HttpTransport,
) -> str:
    """Exchange app credentials for a tenant_access_token (cached one-shot)."""
    status, body = transport(
        "POST",
        f"{base_url}/open-apis/auth/v3/tenant_access_token/internal",
        {"Content-Type": "application/json"},
        {"app_id": app_id, "app_secret": app_secret},
    )
    if status >= 400:
        raise FeishuAuthError(f"feishu token exchange HTTP {status}")
    if int(body.get("code") or 0) != 0:
        raise FeishuAuthError(
            f"feishu token exchange failed: {body.get('msg') or body.get('message') or 'unknown'}"
        )
    token = body.get("tenant_access_token")
    if not isinstance(token, str) or not token:
        raise FeishuAuthError("feishu response missing tenant_access_token")
    return token


def scan_feishu_documents(
    config: FeishuSourceConfig | dict[str, object],
    *,
    env: Mapping[str, str],
    cursor: str | None = None,
    transport: HttpTransport | None = None,
) -> FeishuScanResult:
    """List wiki nodes in a Feishu space.

    Returns at most ``page_size`` items per call; pass ``cursor`` from the
    previous result to paginate.
    """
    if isinstance(config, dict):
        config = FeishuSourceConfig.from_dict(config)
    if not config.space_id:
        raise FeishuConfigError("space_id is required")
    app_id = _resolve_env(config.app_id, env)
    app_secret = _resolve_env(config.app_secret, env)

    fetch = transport or _default_transport
    token = _acquire_tenant_token(config.base_url, app_id, app_secret, fetch)

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    url = (
        f"{config.base_url}/open-apis/wiki/v2/spaces/{config.space_id}/nodes"
        f"?page_size={int(config.page_size)}"
    )
    if cursor:
        url = f"{url}&page_token={cursor}"
    status, body = fetch("GET", url, headers, None)
    if status in (401, 403):
        raise FeishuAuthError(f"feishu auth failed listing nodes: HTTP {status}")
    if status >= 400:
        raise FeishuConfigError(f"feishu returned HTTP {status} listing nodes")
    if int(body.get("code") or 0) != 0:
        raise FeishuConfigError(f"feishu nodes API error: {body.get('msg') or body.get('message')}")

    data = body.get("data") or {}
    items: list[FeishuItem] = []
    for row in data.get("items") or []:
        if not isinstance(row, dict):
            continue
        ts_raw = row.get("obj_edit_time") or row.get("obj_create_time") or 0
        try:
            updated_at = datetime.fromtimestamp(int(ts_raw), UTC)
        except Exception:
            updated_at = datetime.now(UTC)
        items.append(
            FeishuItem(
                item_id=str(row.get("node_token") or ""),
                obj_token=str(row.get("obj_token") or ""),
                node_type=str(row.get("obj_type") or "docx"),
                title=str(row.get("title") or "(untitled)"),
                updated_at=updated_at,
                parent_id=str(row.get("parent_node_token") or "") or None,
            )
        )

    next_cursor = data.get("page_token") if data.get("has_more") else None
    return FeishuScanResult(
        discovered=items,
        next_cursor=str(next_cursor) if next_cursor else None,
        total_count=len(items),
    )


def fetch_docx_raw_content(
    obj_token: str,
    *,
    base_url: str,
    app_id: str,
    app_secret: str,
    env: Mapping[str, str],
    transport: HttpTransport | None = None,
) -> str:
    """Fetch the plain-text body of a Feishu docx node.

    Reuses the credential-exchange flow rather than persisting tokens — the
    Lark token TTL is 2h, much longer than a typical ingest pass.
    """
    fetch = transport or _default_transport
    resolved_app_id = _resolve_env(app_id, env)
    resolved_app_secret = _resolve_env(app_secret, env)
    token = _acquire_tenant_token(base_url, resolved_app_id, resolved_app_secret, fetch)
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
    }
    status, body = fetch(
        "GET",
        f"{base_url}/open-apis/docx/v1/documents/{obj_token}/raw_content",
        headers,
        None,
    )
    if status in (401, 403):
        raise FeishuAuthError(f"feishu auth failed fetching docx: HTTP {status}")
    if status >= 400:
        raise FeishuConfigError(f"feishu returned HTTP {status} fetching docx")
    data = body.get("data") or {}
    return str(data.get("content") or "")
