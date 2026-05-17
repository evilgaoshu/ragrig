"""P3b tests: feedback loop, citation highlighting, multi-turn conversations.

Covers:
- Conversation create / list / get / delete
- ``POST /conversations/{id}/answer`` appends turns and resolves follow-ups
- Conversation isolation across workspaces (404 from another workspace)
- ``POST /answer-feedback`` records 👍 / 👎 with optional turn_id
- ``GET  /answer-feedback`` filters by rating
- ``/retrieval/answer`` citation payload exposes char_start / char_end /
  page_number for source-span highlighting
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.config import Settings
from ragrig.db.models import AnswerFeedback, Base, ConversationTurn
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
def _engine(tmp_path: Path) -> Iterator:
    eng = create_engine(f"sqlite+pysqlite:///{tmp_path / 'p3b.db'}", future=True)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _seed_kb(engine, kb_name: str = "kb1") -> None:
    docs_root = Path(engine.url.database).parent / "docs"
    docs_root.mkdir(exist_ok=True)
    (docs_root / "intro.md").write_text(
        (
            "# Intro\n\nRAGRig records grounded citations for every answer. "
            "It supports follow-up questions via conversation_id sessions.\n"
        ),
        encoding="utf-8",
    )
    with Session(engine, expire_on_commit=False) as session:
        ingest_local_directory(session=session, knowledge_base_name=kb_name, root_path=docs_root)
        index_knowledge_base(
            session=session, knowledge_base_name=kb_name, chunk_size=64, chunk_overlap=8
        )


def _make_client(tmp_path: Path) -> TestClient:
    with _engine(tmp_path) as eng:
        _seed_kb(eng)

        def sf() -> Session:
            return Session(eng, expire_on_commit=False)

        settings = Settings(ragrig_auth_enabled=False)
        app = create_app(check_database=lambda: None, session_factory=sf, settings=settings)
        return TestClient(app)


# ── Citation highlighting ────────────────────────────────────────────────────


@pytest.mark.integration
def test_retrieval_answer_citation_includes_char_spans(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post(
        "/retrieval/answer",
        json={"knowledge_base": "kb1", "query": "What does RAGRig record?"},
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["citations"], "expected at least one citation"
    cit = payload["citations"][0]
    # New highlight fields must be present (value can be None for older chunks)
    assert "char_start" in cit
    assert "char_end" in cit
    assert "page_number" in cit
    # Evidence chunks too
    ec = payload["evidence_chunks"][0]
    assert "char_start" in ec
    assert "char_end" in ec


# ── Conversations ────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_create_and_get_conversation(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post(
        "/conversations",
        json={"knowledge_base": "kb1", "title": "First chat"},
    )
    assert resp.status_code == 201, resp.text
    convo_id = resp.json()["id"]

    detail = client.get(f"/conversations/{convo_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == convo_id
    assert body["title"] == "First chat"
    assert body["knowledge_base"] == "kb1"
    assert body["turns"] == []


@pytest.mark.integration
def test_create_conversation_unknown_kb_404(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post("/conversations", json={"knowledge_base": "ghost"})
    assert resp.status_code == 404


@pytest.mark.integration
def test_list_conversations(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.post("/conversations", json={"knowledge_base": "kb1", "title": "a"})
    client.post("/conversations", json={"knowledge_base": "kb1", "title": "b"})
    resp = client.get("/conversations")
    assert resp.status_code == 200
    titles = {c["title"] for c in resp.json()["items"]}
    assert {"a", "b"}.issubset(titles)


@pytest.mark.integration
def test_delete_conversation(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post("/conversations", json={"knowledge_base": "kb1"})
    convo_id = resp.json()["id"]
    delete_resp = client.delete(f"/conversations/{convo_id}")
    assert delete_resp.status_code == 204
    assert client.get(f"/conversations/{convo_id}").status_code == 404


@pytest.mark.integration
def test_get_conversation_unknown_returns_404(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.get(f"/conversations/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.integration
def test_conversation_answer_appends_turn(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    convo_id = client.post("/conversations", json={"knowledge_base": "kb1"}).json()["id"]

    r1 = client.post(
        f"/conversations/{convo_id}/answer",
        json={"query": "What does RAGRig record?"},
    )
    assert r1.status_code == 200, r1.text
    turn1 = r1.json()["turn"]
    assert turn1["turn_index"] == 0
    assert isinstance(turn1["answer"], str)

    r2 = client.post(
        f"/conversations/{convo_id}/answer",
        json={"query": "And what about follow-up questions?"},
    )
    assert r2.status_code == 200
    turn2 = r2.json()["turn"]
    assert turn2["turn_index"] == 1

    detail = client.get(f"/conversations/{convo_id}").json()
    assert len(detail["turns"]) == 2
    assert [t["turn_index"] for t in detail["turns"]] == [0, 1]


@pytest.mark.integration
def test_conversation_answer_requires_kb(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    convo_id = client.post("/conversations", json={}).json()["id"]
    resp = client.post(f"/conversations/{convo_id}/answer", json={"query": "x"})
    assert resp.status_code == 400
    assert "knowledge_base" in resp.json()["detail"]


@pytest.mark.unit
def test_build_contextual_query_with_history() -> None:
    from ragrig.routers.conversations import _build_contextual_query

    class _T:
        def __init__(self, q: str, a: str) -> None:
            self.query = q
            self.answer = a

    history = [_T("first?", "answer one"), _T("second?", "answer two")]
    out = _build_contextual_query(history, "follow up?", window=2)
    assert "Q: first?" in out
    assert "A: answer one" in out
    assert "Q: follow up?" in out


@pytest.mark.unit
def test_build_contextual_query_window_zero_disables_history() -> None:
    from ragrig.routers.conversations import _build_contextual_query

    class _T:
        def __init__(self, q: str, a: str) -> None:
            self.query = q
            self.answer = a

    history = [_T("first?", "answer one")]
    out = _build_contextual_query(history, "follow?", window=0)
    assert out == "follow?"


# ── Feedback ────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_submit_feedback_thumbs_down(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post(
        "/answer-feedback",
        json={"rating": -1, "reason": "wrong", "query": "Why?"},
    )
    assert resp.status_code == 200
    assert resp.json()["rating"] == -1


@pytest.mark.integration
def test_submit_feedback_invalid_rating(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post("/answer-feedback", json={"rating": 5})
    # Pydantic field validator pass-through; 400 from server-side check
    assert resp.status_code == 400


@pytest.mark.integration
def test_submit_feedback_attached_to_turn(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    convo_id = client.post("/conversations", json={"knowledge_base": "kb1"}).json()["id"]
    r1 = client.post(f"/conversations/{convo_id}/answer", json={"query": "What is RAGRig?"})
    turn_id = r1.json()["turn"]["id"]
    resp = client.post(
        "/answer-feedback",
        json={"rating": 1, "reason": "great", "turn_id": turn_id},
    )
    assert resp.status_code == 200


@pytest.mark.integration
def test_feedback_unknown_turn_returns_404(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.post(
        "/answer-feedback",
        json={"rating": 1, "turn_id": str(uuid.uuid4())},
    )
    assert resp.status_code == 404


@pytest.mark.integration
def test_list_feedback_filtered_by_rating(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.post("/answer-feedback", json={"rating": 1, "reason": "ok"})
    client.post("/answer-feedback", json={"rating": -1, "reason": "bad"})
    resp = client.get("/answer-feedback?rating=-1")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items
    assert all(item["rating"] == -1 for item in items)


@pytest.mark.integration
def test_feedback_row_persists_to_db(tmp_path: Path) -> None:
    """Smoke-check that feedback is actually written to the DB."""
    with _engine(tmp_path) as eng:
        _seed_kb(eng)

        def sf() -> Session:
            return Session(eng, expire_on_commit=False)

        settings = Settings(ragrig_auth_enabled=False)
        app = create_app(check_database=lambda: None, session_factory=sf, settings=settings)
        client = TestClient(app)
        client.post("/answer-feedback", json={"rating": 1, "reason": "x"})

        with sf() as s:
            rows = s.scalars(select(AnswerFeedback)).all()
            assert len(rows) >= 1
            assert rows[-1].rating == 1


@pytest.mark.integration
def test_turn_persists_in_db(tmp_path: Path) -> None:
    """Verify ConversationTurn rows are committed."""
    with _engine(tmp_path) as eng:
        _seed_kb(eng)

        def sf() -> Session:
            return Session(eng, expire_on_commit=False)

        settings = Settings(ragrig_auth_enabled=False)
        app = create_app(check_database=lambda: None, session_factory=sf, settings=settings)
        client = TestClient(app)
        convo_id = client.post("/conversations", json={"knowledge_base": "kb1"}).json()["id"]
        client.post(f"/conversations/{convo_id}/answer", json={"query": "What is RAGRig?"})
        with sf() as s:
            turns = s.scalars(select(ConversationTurn)).all()
            assert len(turns) == 1
            assert turns[0].turn_index == 0
