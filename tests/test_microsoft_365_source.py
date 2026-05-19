"""Unit tests for the Microsoft 365 (SharePoint / OneDrive) source scanner."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping

import pytest

from ragrig.plugins.sources.microsoft_365.config import Microsoft365SourceConfig
from ragrig.plugins.sources.microsoft_365.errors import (
    Microsoft365AuthError,
    Microsoft365ConfigError,
)
from ragrig.plugins.sources.microsoft_365.scanner import (
    M365Item,
    scan_microsoft_365,
)

pytestmark = pytest.mark.unit

# ── Fixtures / helpers ────────────────────────────────────────────────────────

_TS = "2024-06-01T12:00:00Z"


def _drive_item(
    item_id: str,
    name: str,
    *,
    is_folder: bool = False,
    mime_type: str | None = "application/pdf",
    parent_id: str | None = "root",
) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "id": item_id,
        "name": name,
        "webUrl": f"https://tenant.sharepoint.com/sites/Eng/Shared/{name}",
        "size": 1024,
        "lastModifiedDateTime": _TS,
        "parentReference": {"id": parent_id} if parent_id else {},
    }
    if is_folder:
        obj["folder"] = {"childCount": 2}
    else:
        obj["file"] = {"mimeType": mime_type}
    return obj


def _stub_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    return "fake-access-token"


def _make_transport(
    responses: dict[str, tuple[int, dict[str, Any]]],
) -> Any:
    """Returns a transport stub that matches by URL substring."""

    def transport(
        method: str,
        url: str,
        headers: Mapping[str, str],
        params: Mapping[str, object] | None,
        json_body: Mapping[str, object] | None,
    ) -> tuple[int, dict[str, Any]]:
        for key, (status, body) in responses.items():
            if key in url:
                return status, body
        return 404, {"error": {"message": f"no stub for {url}"}}

    return transport


# ── Config tests ──────────────────────────────────────────────────────────────


def test_config_from_dict_valid() -> None:
    cfg = Microsoft365SourceConfig.from_dict(
        {
            "tenant_id": "t1",
            "client_id": "c1",
            "client_secret": "s1",
            "scope": "both",
            "page_size": 50,
        }
    )
    assert cfg.tenant_id == "t1"
    assert cfg.scope == "both"
    assert cfg.page_size == 50
    assert cfg.site_url is None


def test_config_missing_tenant_id_raises() -> None:
    with pytest.raises(Microsoft365ConfigError, match="tenant_id"):
        Microsoft365SourceConfig.from_dict({"client_id": "c1", "client_secret": "s1"})


def test_config_invalid_scope_raises() -> None:
    with pytest.raises(Microsoft365ConfigError, match="scope"):
        Microsoft365SourceConfig.from_dict(
            {"tenant_id": "t", "client_id": "c", "client_secret": "s", "scope": "teams"}
        )


def test_config_site_url_trailing_slash_stripped() -> None:
    cfg = Microsoft365SourceConfig.from_dict(
        {
            "tenant_id": "t",
            "client_id": "c",
            "client_secret": "s",
            "site_url": "https://org.sharepoint.com/sites/Eng/",
        }
    )
    assert cfg.site_url == "https://org.sharepoint.com/sites/Eng"


# ── env:VAR resolution ────────────────────────────────────────────────────────


def test_env_var_missing_raises_auth_error() -> None:
    transport = _make_transport(
        {"sites": (200, {"value": [{"id": "site1"}]}), "drives": (200, {"value": []})}
    )
    with pytest.raises(Microsoft365AuthError, match="missing required env var"):
        scan_microsoft_365(
            {"tenant_id": "t", "client_id": "c", "client_secret": "env:MISSING_SECRET"},
            env={},
            transport=transport,
            _token_factory=_stub_token,
        )


# ── SharePoint scan ───────────────────────────────────────────────────────────


def test_scan_sharepoint_returns_items() -> None:
    items_body = {
        "value": [
            _drive_item("f1", "report.pdf"),
            _drive_item("f2", "readme.txt", mime_type="text/plain"),
        ]
    }
    transport = _make_transport(
        {
            "sites?search": (200, {"value": [{"id": "site1"}]}),
            "sites/site1/drives": (200, {"value": [{"id": "drv1"}]}),
            "drives/drv1/root/children": (200, items_body),
        }
    )
    result = scan_microsoft_365(
        {"tenant_id": "t", "client_id": "c", "client_secret": "s", "scope": "sharepoint"},
        env={},
        transport=transport,
        _token_factory=_stub_token,
    )
    assert result.total_count == 2
    assert len(result.discovered) == 2
    names = {i.name for i in result.discovered}
    assert names == {"report.pdf", "readme.txt"}


def test_scan_returns_m365_item_fields() -> None:
    transport = _make_transport(
        {
            "sites?search": (200, {"value": [{"id": "site1"}]}),
            "sites/site1/drives": (200, {"value": [{"id": "drv1"}]}),
            "drives/drv1/root/children": (
                200,
                {"value": [_drive_item("f1", "doc.pdf")]},
            ),
        }
    )
    result = scan_microsoft_365(
        {"tenant_id": "t", "client_id": "c", "client_secret": "s"},
        env={},
        transport=transport,
        _token_factory=_stub_token,
    )
    item: M365Item = result.discovered[0]
    assert item.item_id == "f1"
    assert item.drive_id == "drv1"
    assert item.site_id == "site1"
    assert item.mime_type == "application/pdf"
    assert item.is_folder is False
    assert item.size_bytes == 1024
    assert isinstance(item.last_modified_at, datetime)


def test_scan_folder_item_detected() -> None:
    transport = _make_transport(
        {
            "sites?search": (200, {"value": [{"id": "site1"}]}),
            "sites/site1/drives": (200, {"value": [{"id": "drv1"}]}),
            "drives/drv1/root/children": (
                200,
                {"value": [_drive_item("d1", "Docs", is_folder=True)]},
            ),
        }
    )
    result = scan_microsoft_365(
        {"tenant_id": "t", "client_id": "c", "client_secret": "s"},
        env={},
        transport=transport,
        _token_factory=_stub_token,
    )
    assert result.discovered[0].is_folder is True


# ── Site URL scoping ──────────────────────────────────────────────────────────


def test_scan_with_site_url_resolves_site() -> None:
    transport = _make_transport(
        {
            "tenant.sharepoint.com:/sites/Eng": (200, {"id": "resolved-site"}),
            "sites/resolved-site/drives": (200, {"value": [{"id": "drv2"}]}),
            "drives/drv2/root/children": (200, {"value": [_drive_item("f1", "a.pdf")]}),
        }
    )
    result = scan_microsoft_365(
        {
            "tenant_id": "t",
            "client_id": "c",
            "client_secret": "s",
            "site_url": "https://tenant.sharepoint.com/sites/Eng",
        },
        env={},
        transport=transport,
        _token_factory=_stub_token,
    )
    assert result.discovered[0].site_id == "resolved-site"


def test_scan_site_url_not_found_raises() -> None:
    transport = _make_transport(
        {"tenant.sharepoint.com:/sites/Gone": (404, {"error": {"message": "not found"}})}
    )
    with pytest.raises(Microsoft365ConfigError, match="not found"):
        scan_microsoft_365(
            {
                "tenant_id": "t",
                "client_id": "c",
                "client_secret": "s",
                "site_url": "https://tenant.sharepoint.com/sites/Gone",
            },
            env={},
            transport=transport,
            _token_factory=_stub_token,
        )


# ── OneDrive scope ────────────────────────────────────────────────────────────


def test_scan_onedrive_scope() -> None:
    def transport(
        method: str,
        url: str,
        headers: Mapping[str, str],
        params: Mapping[str, object] | None,
        json_body: Mapping[str, object] | None,
    ) -> tuple[int, dict[str, Any]]:
        if url.endswith("/drives"):
            return 200, {"value": [{"id": "od1"}, {"id": "od2"}]}
        if "od1/root/children" in url:
            return 200, {"value": [_drive_item("f1", "personal.docx")]}
        if "od2/root/children" in url:
            return 200, {"value": []}
        return 404, {}

    result = scan_microsoft_365(
        {"tenant_id": "t", "client_id": "c", "client_secret": "s", "scope": "onedrive"},
        env={},
        transport=transport,
        _token_factory=_stub_token,
    )
    # First page: first drive returns 1 item; second drive is on next cursor page
    assert len(result.discovered) == 1
    assert result.discovered[0].name == "personal.docx"


# ── Empty results ─────────────────────────────────────────────────────────────


def test_scan_no_drives_returns_empty() -> None:
    transport = _make_transport(
        {
            "sites?search": (200, {"value": [{"id": "site1"}]}),
            "sites/site1/drives": (200, {"value": []}),
        }
    )
    result = scan_microsoft_365(
        {"tenant_id": "t", "client_id": "c", "client_secret": "s"},
        env={},
        transport=transport,
        _token_factory=_stub_token,
    )
    assert result.discovered == []
    assert result.next_cursor is None


def test_scan_no_sites_returns_empty() -> None:
    transport = _make_transport({"sites?search": (200, {"value": []})})
    result = scan_microsoft_365(
        {"tenant_id": "t", "client_id": "c", "client_secret": "s"},
        env={},
        transport=transport,
        _token_factory=_stub_token,
    )
    assert result.discovered == []


# ── Auth error propagation ────────────────────────────────────────────────────


def test_auth_error_on_sites_listing() -> None:
    transport = _make_transport({"sites?search": (401, {})})
    with pytest.raises(Microsoft365AuthError, match="HTTP 401"):
        scan_microsoft_365(
            {"tenant_id": "t", "client_id": "c", "client_secret": "s"},
            env={},
            transport=transport,
            _token_factory=_stub_token,
        )


def test_config_error_on_drive_listing() -> None:
    transport = _make_transport(
        {
            "sites?search": (200, {"value": [{"id": "site1"}]}),
            "sites/site1/drives": (500, {"error": {"message": "server error"}}),
        }
    )
    with pytest.raises(Microsoft365ConfigError, match="HTTP 500"):
        scan_microsoft_365(
            {"tenant_id": "t", "client_id": "c", "client_secret": "s"},
            env={},
            transport=transport,
            _token_factory=_stub_token,
        )


# ── Pagination cursor ─────────────────────────────────────────────────────────


def test_pagination_cursor_carries_next_link() -> None:
    next_link = "https://graph.microsoft.com/v1.0/drives/drv1/root/children?$skiptoken=abc123"
    transport = _make_transport(
        {
            "sites?search": (200, {"value": [{"id": "site1"}]}),
            "sites/site1/drives": (200, {"value": [{"id": "drv1"}]}),
            "drives/drv1/root/children": (
                200,
                {
                    "value": [_drive_item("f1", "page1.pdf")],
                    "@odata.nextLink": next_link,
                },
            ),
        }
    )
    result = scan_microsoft_365(
        {"tenant_id": "t", "client_id": "c", "client_secret": "s"},
        env={},
        transport=transport,
        _token_factory=_stub_token,
    )
    assert result.next_cursor is not None
    assert "drv1" in result.next_cursor or next_link in result.next_cursor


# ── last_modified_at fallback ─────────────────────────────────────────────────


def test_invalid_timestamp_falls_back_to_now() -> None:
    item = _drive_item("f1", "bad.pdf")
    item["lastModifiedDateTime"] = "not-a-date"

    transport = _make_transport(
        {
            "sites?search": (200, {"value": [{"id": "site1"}]}),
            "sites/site1/drives": (200, {"value": [{"id": "drv1"}]}),
            "drives/drv1/root/children": (200, {"value": [item]}),
        }
    )
    before = datetime.now(UTC)
    result = scan_microsoft_365(
        {"tenant_id": "t", "client_id": "c", "client_secret": "s"},
        env={},
        transport=transport,
        _token_factory=_stub_token,
    )
    after = datetime.now(UTC)
    ts = result.discovered[0].last_modified_at
    assert before <= ts <= after
