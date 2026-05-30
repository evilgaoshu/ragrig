"""Integration tests for sink export API endpoints.

Both endpoints monkeypatch the underlying connectors so no real HTTP
calls or database chunk data are required.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from ragrig.db.models import Base
from ragrig.main import create_app
from ragrig.repositories import get_or_create_knowledge_base


def _create_session_factory(database_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        future=True,
        poolclass=NullPool,
    )
    Base.metadata.create_all(engine)

    def _factory() -> Session:
        return Session(engine, expire_on_commit=False)

    return _factory


# ── Agent Access sink export ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_agent_access_export_endpoint_returns_chunk_counts(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = _create_session_factory(tmp_path / "agent-access.db")
    with session_factory() as session:
        get_or_create_knowledge_base(session, "test-kb")
        session.commit()

    from ragrig.plugins.sinks.agent_access.connector import AgentAccessExportReport

    def fake_export(session, *, knowledge_base_name, endpoint_url, api_key, **_kwargs):
        return AgentAccessExportReport(
            endpoint_url=endpoint_url,
            knowledge_base=knowledge_base_name,
            dry_run=False,
            chunk_count=42,
            batch_count=1,
            delivered_batches=1,
            failed_batches=0,
        )

    monkeypatch.setattr("ragrig.routers.sink_exports.export_to_agent_endpoint", fake_export)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/knowledge-bases/test-kb/sink-export/agent-access",
            json={
                "endpoint_url": "https://agent.example.com/ingest",
                "api_key": "test-api-key",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total_chunks"] == 42
    assert body["batches_sent"] == 1
    assert body["failed_batches"] == 0
    assert body["dry_run"] is False


@pytest.mark.anyio
async def test_agent_access_export_dry_run(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = _create_session_factory(tmp_path / "agent-access-dry.db")
    with session_factory() as session:
        get_or_create_knowledge_base(session, "test-kb")
        session.commit()

    from ragrig.plugins.sinks.agent_access.connector import AgentAccessExportReport

    def fake_export(session, *, knowledge_base_name, endpoint_url, api_key, dry_run, **_kwargs):
        return AgentAccessExportReport(
            endpoint_url=endpoint_url,
            knowledge_base=knowledge_base_name,
            dry_run=dry_run,
            chunk_count=10,
            batch_count=1,
            delivered_batches=0,
            failed_batches=0,
        )

    monkeypatch.setattr("ragrig.routers.sink_exports.export_to_agent_endpoint", fake_export)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/knowledge-bases/test-kb/sink-export/agent-access",
            json={
                "endpoint_url": "https://agent.example.com/ingest",
                "api_key": "test-api-key",
                "dry_run": True,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["batches_sent"] == 0


@pytest.mark.anyio
async def test_agent_access_export_returns_404_for_missing_kb(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = _create_session_factory(tmp_path / "agent-access-404.db")

    def fail_export(session, *, knowledge_base_name, **_kwargs):
        raise ValueError(f"Knowledge base '{knowledge_base_name}' not found")

    monkeypatch.setattr("ragrig.routers.sink_exports.export_to_agent_endpoint", fail_export)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/knowledge-bases/missing/sink-export/agent-access",
            json={
                "endpoint_url": "https://agent.example.com/ingest",
                "api_key": "test-api-key",
            },
        )

    assert response.status_code == 404
    assert "missing" in response.json()["error"]


# ── Webhook sink export ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_webhook_export_endpoint_returns_chunk_counts(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = _create_session_factory(tmp_path / "webhook.db")
    with session_factory() as session:
        get_or_create_knowledge_base(session, "test-kb")
        session.commit()

    from ragrig.plugins.sinks.webhook.connector import WebhookExportReport

    def fake_export(session, *, knowledge_base_name, endpoint_url, format, **_kwargs):
        return WebhookExportReport(
            endpoint_url=endpoint_url,
            knowledge_base=knowledge_base_name,
            format=format,
            dry_run=False,
            chunk_count=30,
            batch_count=2,
            delivered_batches=2,
            failed_batches=0,
        )

    monkeypatch.setattr("ragrig.routers.sink_exports.export_to_webhook", fake_export)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/knowledge-bases/test-kb/sink-export/webhook",
            json={
                "endpoint_url": "https://webhook.example.com/chunks",
                "format": "ndjson",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["total_chunks"] == 30
    assert body["batches_sent"] == 2
    assert body["failed_batches"] == 0
    assert body["dry_run"] is False


@pytest.mark.anyio
async def test_webhook_export_invalid_format_returns_400(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = _create_session_factory(tmp_path / "webhook-400.db")
    with session_factory() as session:
        get_or_create_knowledge_base(session, "test-kb")
        session.commit()

    def fail_export(session, *, knowledge_base_name, format, **_kwargs):
        raise ValueError(f"format must be 'ndjson' or 'json'; got {format!r}")

    monkeypatch.setattr("ragrig.routers.sink_exports.export_to_webhook", fail_export)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/knowledge-bases/test-kb/sink-export/webhook",
            json={
                "endpoint_url": "https://webhook.example.com/chunks",
                "format": "csv",
            },
        )

    assert response.status_code == 400
    assert "format must be" in response.json()["error"]


@pytest.mark.anyio
async def test_webhook_export_returns_404_for_missing_kb(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = _create_session_factory(tmp_path / "webhook-404.db")

    def fail_export(session, *, knowledge_base_name, **_kwargs):
        raise ValueError(f"Knowledge base '{knowledge_base_name}' not found")

    monkeypatch.setattr("ragrig.routers.sink_exports.export_to_webhook", fail_export)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/knowledge-bases/missing/sink-export/webhook",
            json={"endpoint_url": "https://webhook.example.com/chunks"},
        )

    assert response.status_code == 404
    assert "missing" in response.json()["error"]


@pytest.mark.anyio
async def test_webhook_export_dry_run(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = _create_session_factory(tmp_path / "webhook-dry.db")
    with session_factory() as session:
        get_or_create_knowledge_base(session, "test-kb")
        session.commit()

    from ragrig.plugins.sinks.webhook.connector import WebhookExportReport

    def fake_export(session, *, knowledge_base_name, endpoint_url, format, dry_run, **_kwargs):
        return WebhookExportReport(
            endpoint_url=endpoint_url,
            knowledge_base=knowledge_base_name,
            format=format,
            dry_run=dry_run,
            chunk_count=5,
            batch_count=1,
            delivered_batches=0,
            failed_batches=0,
        )

    monkeypatch.setattr("ragrig.routers.sink_exports.export_to_webhook", fake_export)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/knowledge-bases/test-kb/sink-export/webhook",
            json={
                "endpoint_url": "https://webhook.example.com/chunks",
                "dry_run": True,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["batches_sent"] == 0
