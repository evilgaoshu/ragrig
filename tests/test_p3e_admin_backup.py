"""P3e tests: workspace backup/restore + admin status endpoint."""

from __future__ import annotations

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

from ragrig.backup import dump_workspace, restore_workspace
from ragrig.config import Settings
from ragrig.db.models import (
    AnswerFeedback,
    Conversation,
    ConversationTurn,
    KnowledgeBase,
    Source,
    Workspace,
)
from ragrig.main import create_app


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return compiler.process(JSON(), **kw)


@compiles(Vector, "sqlite")
def _vector_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return compiler.process(JSON(), **kw)


@contextmanager
def _engine(tmp_path: Path) -> Iterator[Any]:
    from ragrig.db.models import Base

    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'p3e.db'}", future=True)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _seed_workspace(engine) -> uuid.UUID:
    with Session(engine, expire_on_commit=False) as session:
        ws = Workspace(id=uuid.uuid4(), slug="acme", display_name="Acme Inc")
        session.add(ws)
        session.flush()
        kb = KnowledgeBase(id=uuid.uuid4(), workspace_id=ws.id, name="docs")
        session.add(kb)
        session.flush()
        source = Source(
            id=uuid.uuid4(),
            knowledge_base_id=kb.id,
            kind="confluence",
            uri="docs-space",
            config_json={"base_url": "https://x.atlassian.net/wiki", "space_key": "DOC"},
        )
        session.add(source)
        conv = Conversation(
            id=uuid.uuid4(),
            workspace_id=ws.id,
            knowledge_base_id=kb.id,
            title="Welcome",
        )
        session.add(conv)
        session.flush()
        turn = ConversationTurn(
            id=uuid.uuid4(),
            conversation_id=conv.id,
            turn_index=0,
            query="what is RAGRig?",
            answer="a RAG workbench",
            grounding_status="grounded",
            citations_json=[],
        )
        session.add(turn)
        fb = AnswerFeedback(
            id=uuid.uuid4(),
            workspace_id=ws.id,
            turn_id=turn.id,
            rating=1,
            reason="clear",
        )
        session.add(fb)
        session.commit()
        return ws.id


def test_dump_workspace_captures_all_blocks(tmp_path: Path) -> None:
    with _engine(tmp_path) as engine:
        ws_id = _seed_workspace(engine)
        with Session(engine, expire_on_commit=False) as session:
            payload = dump_workspace(session, workspace_id=ws_id)
    assert payload["schema_version"] == 1
    assert payload["workspace"]["slug"] == "acme"
    assert len(payload["knowledge_bases"]) == 1
    assert len(payload["sources"]) == 1
    assert payload["sources"][0]["uri"] == "docs-space"
    assert len(payload["conversations"]) == 1
    assert len(payload["conversation_turns"]) == 1
    assert len(payload["answer_feedback"]) == 1


def test_dump_unknown_workspace_raises(tmp_path: Path) -> None:
    with _engine(tmp_path) as engine:
        _seed_workspace(engine)
        with Session(engine, expire_on_commit=False) as session:
            with pytest.raises(ValueError):
                dump_workspace(session, workspace_id=uuid.uuid4())


def test_restore_into_empty_db_is_idempotent(tmp_path: Path) -> None:
    # Dump from one DB
    with _engine(tmp_path) as src_engine:
        ws_id = _seed_workspace(src_engine)
        with Session(src_engine, expire_on_commit=False) as session:
            payload = dump_workspace(session, workspace_id=ws_id)

    # Restore into a fresh DB
    dest_path = tmp_path / "dest"
    dest_path.mkdir()
    with _engine(dest_path) as dest_engine:
        with Session(dest_engine, expire_on_commit=False) as session:
            counts1 = restore_workspace(session, payload)
            session.commit()
        # second time → upsert, no duplicates
        with Session(dest_engine, expire_on_commit=False) as session:
            counts2 = restore_workspace(session, payload)
            session.commit()
        # And the restored workspace is queryable
        with Session(dest_engine, expire_on_commit=False) as session:
            ws = session.get(Workspace, ws_id)
            assert ws is not None
            assert ws.slug == "acme"
            sources = list(session.scalars(Source.__table__.select()))
            assert len(sources) == 1
    assert counts1["workspace"] == 1 == counts2["workspace"]
    assert counts1["knowledge_bases"] == 1 == counts2["knowledge_bases"]
    assert counts1["conversation_turns"] == 1 == counts2["conversation_turns"]


def test_restore_rejects_bad_schema_version(tmp_path: Path) -> None:
    with _engine(tmp_path) as engine:
        with Session(engine, expire_on_commit=False) as session:
            with pytest.raises(ValueError):
                restore_workspace(session, {"schema_version": 999, "workspace": {}})


# ─── Admin router ────────────────────────────────────────────────────────────


def _client(engine) -> TestClient:
    def sf() -> Session:
        return Session(engine, expire_on_commit=False)

    settings = Settings(ragrig_auth_enabled=False)
    app = create_app(check_database=lambda: None, session_factory=sf, settings=settings)
    return TestClient(app)


def test_admin_status_reports_counts(tmp_path: Path) -> None:
    with _engine(tmp_path) as engine:
        _seed_workspace(engine)
        client = _client(engine)
        resp = client.get("/admin/status")
        assert resp.status_code == 200, resp.text
        counts = resp.json()["counts"]
        assert counts["workspaces"] == 1
        assert counts["knowledge_bases"] == 1
        assert counts["sources"] == 1
        assert counts["conversations"] == 1
        assert counts["answer_feedback"] == 1


def test_admin_backup_returns_payload_and_restore_roundtrip(tmp_path: Path) -> None:
    with _engine(tmp_path) as engine:
        ws_id = _seed_workspace(engine)
        client = _client(engine)
        backup_resp = client.get(f"/admin/backup/{ws_id}")
        assert backup_resp.status_code == 200, backup_resp.text
        payload = backup_resp.json()
        assert payload["workspace"]["slug"] == "acme"

        restore_resp = client.post("/admin/restore", json={"payload": payload})
        assert restore_resp.status_code == 200, restore_resp.text
        body = restore_resp.json()
        assert body["status"] == "ok"
        assert body["written"]["workspace"] == 1


def test_admin_backup_unknown_workspace_404(tmp_path: Path) -> None:
    with _engine(tmp_path) as engine:
        _seed_workspace(engine)
        client = _client(engine)
        resp = client.get(f"/admin/backup/{uuid.uuid4()}")
        assert resp.status_code == 404


def test_admin_restore_rejects_invalid_payload(tmp_path: Path) -> None:
    with _engine(tmp_path) as engine:
        _seed_workspace(engine)
        client = _client(engine)
        resp = client.post("/admin/restore", json={"payload": {"schema_version": 99}})
        assert resp.status_code == 400
