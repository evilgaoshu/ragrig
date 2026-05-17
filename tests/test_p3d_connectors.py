"""P3d tests: Confluence + Notion + Feishu source connectors + source webhooks.

Each scanner accepts a pluggable ``transport`` callable so these tests stub the
HTTP layer entirely — no real network calls. The webhook router test boots a
FastAPI app with a SQLite store and exercises the HMAC verification path.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.config import Settings
from ragrig.db.models import Base, KnowledgeBase, Source, Workspace
from ragrig.main import create_app
from ragrig.plugins.sources.confluence import (
    ConfluenceAuthError,
    ConfluenceConfigError,
    scan_confluence_pages,
)
from ragrig.plugins.sources.feishu import (
    FeishuAuthError,
    FeishuConfigError,
    scan_feishu_documents,
)
from ragrig.plugins.sources.feishu.scanner import fetch_docx_raw_content
from ragrig.plugins.sources.notion import (
    NotionAuthError,
    NotionConfigError,
    scan_notion_pages,
)
from ragrig.plugins.sources.notion.scanner import fetch_block_text


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return compiler.process(JSON(), **kw)


@compiles(Vector, "sqlite")
def _vector_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return compiler.process(JSON(), **kw)


# ─── Confluence ──────────────────────────────────────────────────────────────


def test_confluence_scan_happy_path() -> None:
    calls: list[tuple[str, dict[str, str], dict[str, object]]] = []

    def transport(url, headers, params):
        calls.append((url, dict(headers), dict(params)))
        return 200, {
            "results": [
                {
                    "id": "page-1",
                    "title": "Engineering Onboarding",
                    "version": {"number": 3, "when": "2026-05-10T12:00:00Z"},
                    "space": {"key": "ENG"},
                    "body": {"storage": {"value": "<p>welcome</p>"}},
                    "_links": {"webui": "/spaces/ENG/pages/page-1"},
                }
            ],
            "size": 1,
            "start": 0,
            "_links": {"next": "/rest/api/content?start=1"},
        }

    result = scan_confluence_pages(
        {
            "base_url": "https://example.atlassian.net/wiki",
            "space_key": "ENG",
            "email": "env:EMAIL",
            "api_token": "env:TOKEN",
        },
        env={"EMAIL": "ops@example.com", "TOKEN": "secret-token"},
        transport=transport,
    )

    assert len(result.discovered) == 1
    item = result.discovered[0]
    assert item.item_id == "page-1"
    assert item.title == "Engineering Onboarding"
    assert item.space_key == "ENG"
    assert item.version == 3
    assert "welcome" in item.body_storage
    assert "/spaces/ENG/pages/page-1" in item.web_url
    assert result.next_cursor == "1"

    url, headers, params = calls[0]
    assert url == "https://example.atlassian.net/wiki/rest/api/content"
    assert headers["Authorization"].startswith("Basic ")
    assert params["spaceKey"] == "ENG"


def test_confluence_scan_pagination_cursor() -> None:
    seen_starts: list[object] = []

    def transport(url, headers, params):
        seen_starts.append(params.get("start"))
        return 200, {"results": [], "size": 0, "start": int(params.get("start") or 0)}

    scan_confluence_pages(
        {
            "base_url": "https://example.atlassian.net/wiki",
            "email": "env:E",
            "api_token": "env:T",
        },
        env={"E": "a", "T": "b"},
        cursor="50",
        transport=transport,
    )
    assert seen_starts == [50]


def test_confluence_scan_missing_credentials_raises() -> None:
    with pytest.raises(ConfluenceAuthError):
        scan_confluence_pages(
            {"base_url": "https://x.example.com", "email": "env:E", "api_token": "env:T"},
            env={},
            transport=lambda *a, **k: (200, {}),
        )


def test_confluence_scan_401_raises_auth_error() -> None:
    def transport(url, headers, params):
        return 401, {}

    with pytest.raises(ConfluenceAuthError):
        scan_confluence_pages(
            {
                "base_url": "https://x.example.com",
                "email": "env:E",
                "api_token": "env:T",
            },
            env={"E": "a", "T": "b"},
            transport=transport,
        )


def test_confluence_scan_500_raises_config_error() -> None:
    def transport(url, headers, params):
        return 500, {}

    with pytest.raises(ConfluenceConfigError):
        scan_confluence_pages(
            {
                "base_url": "https://x.example.com",
                "email": "env:E",
                "api_token": "env:T",
            },
            env={"E": "a", "T": "b"},
            transport=transport,
        )


# ─── Notion ──────────────────────────────────────────────────────────────────


def test_notion_scan_happy_path_pages_and_databases() -> None:
    def transport(method, url, headers, body):
        assert method == "POST"
        assert url == "https://api.notion.com/v1/search"
        assert headers["Authorization"] == "Bearer secret-token"
        return 200, {
            "results": [
                {
                    "object": "page",
                    "id": "page-1",
                    "url": "https://www.notion.so/page-1",
                    "last_edited_time": "2026-05-10T12:00:00.000Z",
                    "parent": {"workspace": "ws-root"},
                    "properties": {
                        "Name": {
                            "type": "title",
                            "title": [{"plain_text": "Roadmap"}],
                        }
                    },
                },
                {
                    "object": "database",
                    "id": "db-1",
                    "url": "https://www.notion.so/db-1",
                    "last_edited_time": "2026-05-09T12:00:00.000Z",
                    "title": [{"plain_text": "Customers"}],
                    "parent": {"page_id": "page-1"},
                },
            ],
            "next_cursor": "abc",
        }

    result = scan_notion_pages(
        {"api_token": "secret-token", "filter": "page"},
        env={},
        transport=transport,
    )
    titles = sorted(item.title for item in result.discovered)
    assert titles == ["Customers", "Roadmap"]
    assert result.next_cursor == "abc"
    assert {item.object_kind for item in result.discovered} == {"page", "database"}


def test_notion_scan_passes_cursor() -> None:
    captured: dict[str, object] = {}

    def transport(method, url, headers, body):
        captured.update(dict(body or {}))
        return 200, {"results": [], "next_cursor": None}

    scan_notion_pages(
        {"api_token": "tok"},
        env={},
        cursor="next-page-token",
        transport=transport,
    )
    assert captured["start_cursor"] == "next-page-token"


def test_notion_scan_401_raises_auth_error() -> None:
    with pytest.raises(NotionAuthError):
        scan_notion_pages(
            {"api_token": "tok"},
            env={},
            transport=lambda *a, **k: (401, {}),
        )


def test_notion_scan_invalid_filter_rejected() -> None:
    with pytest.raises(NotionConfigError):
        scan_notion_pages({"api_token": "tok", "filter": "bogus"}, env={})


def test_notion_fetch_block_text_joins_paragraphs() -> None:
    def transport(method, url, headers, body):
        assert method == "GET"
        assert "/blocks/page-1/children" in url
        return 200, {
            "results": [
                {
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"plain_text": "Hello "}, {"plain_text": "world."}]
                    },
                },
                {
                    "type": "heading_2",
                    "heading_2": {"rich_text": [{"plain_text": "Section"}]},
                },
            ]
        }

    text = fetch_block_text("page-1", token="tok", transport=transport)
    assert "Hello world." in text
    assert "Section" in text


# ─── Feishu / Lark ───────────────────────────────────────────────────────────


def _feishu_token_transport(node_payload: dict[str, Any], *, fail_token: bool = False):
    def transport(method, url, headers, body):
        if "tenant_access_token" in url:
            if fail_token:
                return 200, {"code": 99991663, "msg": "invalid app credentials"}
            return 200, {"code": 0, "tenant_access_token": "u-token"}
        if "/wiki/v2/spaces/" in url:
            return 200, node_payload
        if "/docx/v1/documents/" in url:
            return 200, {"code": 0, "data": {"content": "doc body text"}}
        raise AssertionError(f"unexpected url: {url}")

    return transport


def test_feishu_scan_happy_path() -> None:
    payload = {
        "code": 0,
        "data": {
            "items": [
                {
                    "node_token": "n-1",
                    "obj_token": "d-1",
                    "obj_type": "docx",
                    "title": "Onboarding",
                    "obj_edit_time": 1715000000,
                    "parent_node_token": "root",
                },
                {
                    "node_token": "n-2",
                    "obj_token": "d-2",
                    "obj_type": "docx",
                    "title": "API Docs",
                    "obj_edit_time": 1715100000,
                },
            ],
            "has_more": True,
            "page_token": "cursor-2",
        },
    }
    result = scan_feishu_documents(
        {
            "space_id": "spc-1",
            "app_id": "env:APP",
            "app_secret": "env:SECRET",
        },
        env={"APP": "cli_xxx", "SECRET": "shh"},
        transport=_feishu_token_transport(payload),
    )
    assert len(result.discovered) == 2
    assert result.next_cursor == "cursor-2"
    titles = [item.title for item in result.discovered]
    assert titles == ["Onboarding", "API Docs"]


def test_feishu_scan_token_failure_raises_auth_error() -> None:
    with pytest.raises(FeishuAuthError):
        scan_feishu_documents(
            {
                "space_id": "spc-1",
                "app_id": "env:APP",
                "app_secret": "env:SECRET",
            },
            env={"APP": "cli_xxx", "SECRET": "bad"},
            transport=_feishu_token_transport({}, fail_token=True),
        )


def test_feishu_scan_requires_space_id() -> None:
    with pytest.raises(FeishuConfigError):
        scan_feishu_documents(
            {"space_id": "", "app_id": "env:A", "app_secret": "env:B"},
            env={"A": "a", "B": "b"},
            transport=_feishu_token_transport({}),
        )


def test_feishu_fetch_docx_raw_content_returns_body() -> None:
    body = fetch_docx_raw_content(
        "d-1",
        base_url="https://open.feishu.cn",
        app_id="env:APP",
        app_secret="env:SECRET",
        env={"APP": "cli_x", "SECRET": "s"},
        transport=_feishu_token_transport({}),
    )
    assert body == "doc body text"


# ─── Source webhook router (HMAC + auth fallback) ────────────────────────────


@contextmanager
def _engine(tmp_path: Path) -> Iterator[Any]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'p3d.db'}", future=True)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _seed_source(
    engine, *, source_name: str = "wiki-onboarding", webhook_secret: str | None = None
) -> tuple[uuid.UUID, uuid.UUID]:
    with Session(engine, expire_on_commit=False) as session:
        ws = Workspace(id=uuid.uuid4(), slug="acme", display_name="Acme")
        session.add(ws)
        session.flush()
        kb = KnowledgeBase(id=uuid.uuid4(), workspace_id=ws.id, name="kb1")
        session.add(kb)
        session.flush()
        config: dict[str, Any] = {}
        if webhook_secret is not None:
            config["webhook_secret"] = webhook_secret
        source = Source(
            id=uuid.uuid4(),
            knowledge_base_id=kb.id,
            kind="confluence",
            uri=source_name,
            config_json=config,
        )
        session.add(source)
        session.commit()
        return ws.id, source.id


def _client(engine) -> TestClient:
    def sf() -> Session:
        return Session(engine, expire_on_commit=False)

    settings = Settings(ragrig_auth_enabled=False)
    app = create_app(check_database=lambda: None, session_factory=sf, settings=settings)
    return TestClient(app)


def test_source_webhook_404_when_unknown(tmp_path: Path) -> None:
    with _engine(tmp_path) as engine:
        _seed_source(engine)
        client = _client(engine)
        resp = client.post("/sources/does-not-exist/webhook", json={"event": "ping"})
        assert resp.status_code == 404


def test_source_webhook_accepts_valid_signature(tmp_path: Path) -> None:
    secret = "super-secret"
    with _engine(tmp_path) as engine:
        _seed_source(engine, source_name="wiki-1", webhook_secret=secret)
        client = _client(engine)
        body = json.dumps({"event": "page.updated", "page_id": "p-1"}).encode()
        sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        resp = client.post(
            "/sources/wiki-1/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-RAGRig-Signature-256": sig,
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["status"] == "accepted"


def test_source_webhook_rejects_invalid_signature(tmp_path: Path) -> None:
    with _engine(tmp_path) as engine:
        _seed_source(engine, source_name="wiki-2", webhook_secret="real-secret")
        client = _client(engine)
        body = b'{"event": "x"}'
        resp = client.post(
            "/sources/wiki-2/webhook",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-RAGRig-Signature-256": "sha256=deadbeef",
            },
        )
        assert resp.status_code == 401


def test_source_webhook_no_secret_falls_through_to_auth(tmp_path: Path) -> None:
    # When auth is disabled (test setting) and no secret is configured, the
    # endpoint must still reject anonymous calls — it's an anti-footgun guard.
    with _engine(tmp_path) as engine:
        _seed_source(engine, source_name="wiki-3", webhook_secret=None)
        client = _client(engine)
        resp = client.post("/sources/wiki-3/webhook", json={"event": "x"})
        assert resp.status_code == 401


# ─── Enterprise plugin spec exposure ─────────────────────────────────────────


def test_enterprise_specs_include_new_connectors() -> None:
    from ragrig.plugins.enterprise import ENTERPRISE_CONNECTORS

    assert "source.confluence" in ENTERPRISE_CONNECTORS
    assert "source.notion" in ENTERPRISE_CONNECTORS
    assert "source.feishu" in ENTERPRISE_CONNECTORS
