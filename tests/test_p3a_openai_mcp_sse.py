"""P3a tests: OpenAI-compatible endpoint, MCP server, and SSE streaming.

Covers:
- ``POST /v1/chat/completions`` non-streaming
- ``POST /v1/chat/completions`` streaming (SSE)
- ``GET /v1/models``
- ``POST /mcp`` initialize / tools.list / tools.call / resources.list
- ``POST /retrieval/answer`` with ``stream=true``
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.config import Settings
from ragrig.db.models import Base
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.main import create_app


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return compiler.process(JSON(), **kw)


@compiles(Vector, "sqlite")
def _vector_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return compiler.process(JSON(), **kw)


@contextmanager
def _session_factory(tmp_path: Path) -> Iterator[Session]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'p3a.db'}", future=True)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _seed_kb(engine, kb_name: str = "kb1") -> None:
    docs_root = Path(engine.url.database).parent / "docs"
    docs_root.mkdir(exist_ok=True)
    (docs_root / "intro.md").write_text(
        "# Intro\n\nRAGRig is a RAG workbench that supports hybrid retrieval and citations.\n",
        encoding="utf-8",
    )
    with Session(engine, expire_on_commit=False) as session:
        ingest_local_directory(session=session, knowledge_base_name=kb_name, root_path=docs_root)
        index_knowledge_base(
            session=session, knowledge_base_name=kb_name, chunk_size=64, chunk_overlap=8
        )


def _make_client(tmp_path: Path, kb_name: str = "kb1") -> TestClient:
    with _session_factory(tmp_path) as engine:
        _seed_kb(engine, kb_name)

        def sf() -> Session:
            return Session(engine, expire_on_commit=False)

        settings = Settings(ragrig_auth_enabled=False)
        app = create_app(check_database=lambda: None, session_factory=sf, settings=settings)
        return TestClient(app)


# ── OpenAI compat ────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_openai_chat_completion_nonstream(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "ragrig/kb1",
            "messages": [{"role": "user", "content": "What is RAGRig?"}],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["object"] == "chat.completion"
    assert data["model"] == "ragrig/kb1"
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert isinstance(data["choices"][0]["message"]["content"], str)
    assert data["choices"][0]["finish_reason"] == "stop"
    assert "usage" in data
    assert data["usage"]["total_tokens"] >= 1
    # RAGRig extension block
    assert "ragrig" in data
    assert "grounding_status" in data["ragrig"]


@pytest.mark.integration
def test_openai_chat_completion_stream_emits_sse(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "ragrig/kb1",
            "messages": [{"role": "user", "content": "Hybrid retrieval?"}],
            "stream": True,
        },
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = b"".join(resp.iter_bytes()).decode("utf-8")
    assert "data: " in body
    assert "[DONE]" in body
    # at least one chunk should carry delta content
    assert '"delta":' in body


@pytest.mark.integration
def test_openai_chat_completion_invalid_request(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "ragrig/kb1", "messages": [{"role": "system", "content": "hi"}]},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "missing_user_message"


@pytest.mark.integration
def test_openai_chat_completion_unknown_kb(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post(
        "/v1/chat/completions",
        json={
            "model": "ragrig/does-not-exist",
            "messages": [{"role": "user", "content": "x"}],
        },
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "knowledge_base_not_found"


@pytest.mark.integration
def test_openai_models_lists_knowledge_bases(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    ids = {entry["id"] for entry in data["data"]}
    assert "ragrig/kb1" in ids


@pytest.mark.unit
def test_parse_model_variants() -> None:
    from ragrig.routers.openai_compat import _parse_model

    assert _parse_model("kb1") == ("kb1", "deterministic-local", None)
    assert _parse_model("ragrig/kb1") == ("kb1", "deterministic-local", None)
    assert _parse_model("ragrig/kb1@openai") == ("kb1", "openai", None)
    assert _parse_model("ragrig/kb1@openai:gpt-4o") == ("kb1", "openai", "gpt-4o")


# ── MCP ──────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_mcp_initialize_returns_capabilities(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 1
    assert data["result"]["serverInfo"]["name"] == "ragrig"
    assert "tools" in data["result"]["capabilities"]


@pytest.mark.integration
def test_mcp_tools_list_includes_search_and_answer(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert resp.status_code == 200
    names = {t["name"] for t in resp.json()["result"]["tools"]}
    assert "search_knowledge_base" in names
    assert "answer_question" in names


@pytest.mark.integration
def test_mcp_search_tool_returns_results(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "search_knowledge_base",
                "arguments": {"knowledge_base": "kb1", "query": "hybrid retrieval"},
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["isError"] is False
    assert body["result"]["content"][0]["type"] == "text"
    assert body["result"]["_meta"]["knowledge_base"] == "kb1"


@pytest.mark.integration
def test_mcp_answer_tool_returns_text(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "answer_question",
                "arguments": {
                    "knowledge_base": "kb1",
                    "query": "What does RAGRig support?",
                },
            },
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["isError"] is False
    assert len(body["result"]["content"][0]["text"]) > 0


@pytest.mark.integration
def test_mcp_resources_list_returns_kbs(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 5, "method": "resources/list"})
    assert resp.status_code == 200
    uris = {r["uri"] for r in resp.json()["result"]["resources"]}
    assert "ragrig://kb/kb1" in uris


@pytest.mark.integration
def test_mcp_unknown_method_returns_error(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": 99, "method": "nope/nope"})
    assert resp.status_code == 200
    err = resp.json()["error"]
    assert err["code"] == -32601


@pytest.mark.integration
def test_mcp_batch_dispatch(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post(
        "/mcp",
        json=[
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ],
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert {item["id"] for item in body} == {1, 2}


# ── /retrieval/answer SSE ────────────────────────────────────────────────────


@pytest.mark.integration
def test_retrieval_answer_stream_emits_sse(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    with client.stream(
        "POST",
        "/retrieval/answer",
        json={
            "knowledge_base": "kb1",
            "query": "What does RAGRig support?",
            "stream": True,
        },
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = b"".join(resp.iter_bytes()).decode("utf-8")
    assert "event: delta" in body
    assert "event: done" in body
    assert "[DONE]" in body
    # Final event payload should be valid JSON containing citations
    final_data_lines = [
        line[6:]
        for line in body.split("\n")
        if line.startswith("data: ") and line != "data: [DONE]"
    ]
    parsed_payload = json.loads(final_data_lines[-1])
    assert "citations" in parsed_payload


# ── Sanity: verify imports resolve cleanly ───────────────────────────────────


@pytest.mark.unit
def test_imports() -> None:
    from ragrig.routers import mcp as mcp_mod
    from ragrig.routers import openai_compat as oa_mod

    assert mcp_mod.router is not None
    assert oa_mod.router is not None
    # Unused locals to make ruff happy
    _ = uuid
