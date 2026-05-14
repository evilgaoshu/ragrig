from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from ragrig.db.models import Base, Document, DocumentVersion, PipelineRun, PipelineRunItem
from ragrig.ingestion.web_import import (
    MAX_WEBSITE_IMPORT_BYTES,
    WebsiteImportError,
    collect_website_imports,
)
from ragrig.main import create_app
from ragrig.repositories import get_or_create_knowledge_base


def _mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _create_file_session_factory(database_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        future=True,
        poolclass=NullPool,
    )
    Base.metadata.create_all(engine)

    def _factory() -> Session:
        return Session(engine, expire_on_commit=False)

    return _factory


def test_collect_website_imports_accepts_single_html_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.test/guide"
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<html><head><title>Guide</title></head><body>Hello</body></html>",
        )

    result = collect_website_imports(
        urls=["https://example.test/guide"],
        client=_mock_client(handler),
    )

    assert len(result.accepted_pages) == 1
    assert result.accepted_pages[0].source_url == "https://example.test/guide"
    assert result.accepted_pages[0].title == "Guide"
    assert result.accepted_pages[0].html.startswith("<html>")
    assert result.failed_pages == 0
    assert result.failures == []


def test_collect_website_imports_records_non_html_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"ok": True},
        )

    result = collect_website_imports(
        urls=["https://example.test/data"],
        client=_mock_client(handler),
    )

    assert result.accepted_pages == []
    assert result.failed_pages == 1
    assert result.failures[0].source_url == "https://example.test/data"
    assert result.failures[0].reason == "unsupported_content_type"
    assert "application/json" in result.failures[0].message


def test_collect_website_imports_rejects_cap_exceeded() -> None:
    urls = [f"https://example.test/page-{index}" for index in range(26)]

    with pytest.raises(WebsiteImportError, match="maximum 25 URLs"):
        collect_website_imports(
            urls=urls,
            client=_mock_client(lambda request: httpx.Response(200)),
        )


def test_collect_website_imports_rejects_private_literal_ip() -> None:
    with pytest.raises(WebsiteImportError, match="private or local network"):
        collect_website_imports(
            urls=["http://127.0.0.1:8000/private"],
            client=_mock_client(lambda request: httpx.Response(200)),
        )


def test_collect_website_imports_rejects_malformed_url() -> None:
    with pytest.raises(WebsiteImportError, match="invalid URL"):
        collect_website_imports(
            urls=["http://[::1"],
            client=_mock_client(lambda request: httpx.Response(200)),
        )

    with pytest.raises(WebsiteImportError, match="invalid URL"):
        collect_website_imports(
            urls=["http://example.test:bad"],
            client=_mock_client(lambda request: httpx.Response(200)),
        )


def test_collect_website_imports_records_oversized_page_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "content-type": "text/html",
                "content-length": str(MAX_WEBSITE_IMPORT_BYTES + 1),
            },
            text="<html><body>too large</body></html>",
        )

    result = collect_website_imports(
        urls=["https://example.test/huge"],
        client=_mock_client(handler),
    )

    assert result.accepted_pages == []
    assert result.failed_pages == 1
    assert result.failures[0].reason == "response_too_large"
    assert "too large" in result.failures[0].message


def test_collect_website_imports_expands_sitemap_loc_entries() -> None:
    sitemap = """<?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.test/a</loc></url>
      <url><loc>https://example.test/b</loc></url>
    </urlset>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://example.test/sitemap.xml":
            return httpx.Response(
                200,
                headers={"content-type": "application/xml"},
                text=sitemap,
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=(
                f"<html><head><title>{request.url.path}</title></head>"
                "<body>ok</body></html>"
            ),
        )

    result = collect_website_imports(
        urls=["https://example.test/root"],
        sitemap_url="https://example.test/sitemap.xml",
        client=_mock_client(handler),
    )

    assert [page.source_url for page in result.accepted_pages] == [
        "https://example.test/root",
        "https://example.test/a",
        "https://example.test/b",
    ]
    assert result.failed_pages == 0


@pytest.mark.anyio
async def test_website_import_endpoint_returns_accepted_and_failed_counts(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = _create_file_session_factory(tmp_path / "website-import.db")
    with session_factory() as session:
        get_or_create_knowledge_base(session, "fixture-local")
        session.commit()

    from ragrig.ingestion import web_import

    def fake_collect_website_imports(*, urls, sitemap_url=None):
        del sitemap_url
        return web_import.WebsiteImportResult(
            accepted_pages=[
                web_import.ImportedPage(
                    source_url=urls[0],
                    html="<html><body>ok</body></html>",
                    title=None,
                )
            ],
            failures=[
                web_import.ImportFailure(
                    source_url="https://example.test/bad",
                    reason="http_status",
                    message="HTTP status 404",
                )
            ],
        )

    monkeypatch.setattr(
        "ragrig.local_pilot.service.collect_website_imports",
        fake_collect_website_imports,
    )
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/knowledge-bases/fixture-local/website-import",
            json={"urls": ["https://example.test/ok"]},
        )

    assert response.status_code == 202
    body = response.json()
    assert body["pipeline_run_id"]
    assert body["accepted_pages"] == 1
    assert body["failed_pages"] == 1
    assert body["failures"] == [
        {
            "source_url": "https://example.test/bad",
            "reason": "http_status",
            "message": "HTTP status 404",
        }
    ]
    with session_factory() as session:
        run = session.scalar(select(PipelineRun))
        assert run is not None
        assert str(run.id) == body["pipeline_run_id"]
        assert run.run_type == "website_import"
        assert run.total_items == 2
        assert run.success_count == 1
        assert run.failure_count == 1
        assert session.scalar(select(DocumentVersion)) is not None
        documents = list(session.scalars(select(Document).order_by(Document.uri)))
        assert [document.uri for document in documents] == [
            "https://example.test/bad",
            "https://example.test/ok",
        ]
        items = list(session.scalars(select(PipelineRunItem).order_by(PipelineRunItem.status)))
        assert {item.status for item in items} == {"failed", "success"}


@pytest.mark.anyio
async def test_website_import_endpoint_returns_404_for_missing_kb(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = _create_file_session_factory(tmp_path / "missing-website-import.db")

    def fail_collect_website_imports(*, urls, sitemap_url=None):
        raise AssertionError("collector should not run for a missing knowledge base")

    monkeypatch.setattr(
        "ragrig.local_pilot.service.collect_website_imports",
        fail_collect_website_imports,
    )
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/knowledge-bases/missing/website-import",
            json={"urls": ["https://example.test/ok"]},
        )

    assert response.status_code == 404
    assert response.json() == {"error": "knowledge base 'missing' not found"}


def test_local_pilot_status_lists_required_capabilities(tmp_path) -> None:
    session_factory = _create_file_session_factory(tmp_path / "local-pilot-status.db")
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    client = TestClient(app)

    response = client.get("/local-pilot/status")

    assert response.status_code == 200
    body = response.json()
    assert body["upload"]["max_file_size_mb"] == 50
    assert ".pdf" in body["upload"]["extensions"]
    assert ".docx" in body["upload"]["extensions"]
    assert body["website_import"]["max_pages"] == 25
    assert "model.google_gemini" in body["models"]["required"]
