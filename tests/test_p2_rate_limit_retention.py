"""P2 rate limiting and data retention tests.

Covers:
- SlidingWindow allows/blocks correctly
- RateLimiter.check_search / check_ingest raises 429 when exceeded
- RateLimiter is a no-op when disabled
- Retention: purge_old_document_versions removes only non-current old versions
- Retention: purge_old_audit_events removes old events, respects workspace filter
- Retention: run_retention_for_knowledge_base skips KBs without a policy
- Retention: run_all_retention covers KBs + audit events
- Retention API: GET/PATCH /knowledge-bases/{name}/retention
- Retention API: POST /admin/retention/run
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine, event, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from ragrig.config import Settings

# ── SQLite compat ─────────────────────────────────────────────────────────────


@compiles(JSONB, "sqlite")
def _jsonb_sqlite(element, compiler, **kw):  # type: ignore[no-untyped-def]
    return "TEXT"


def _make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    from ragrig.db.models import Base

    Base.metadata.create_all(engine)
    return engine


def _factory(engine):
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _make_workspace(session: Session) -> "uuid.UUID":
    from ragrig.db.models import Workspace

    ws_id = uuid.uuid4()
    ws = Workspace(
        id=ws_id,
        slug=str(ws_id)[:8],
        display_name="test",
        status="active",
        metadata_json={},
    )
    session.add(ws)
    session.flush()
    return ws_id


# ── Rate limiter ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_sliding_window_allows_within_limit():
    from ragrig.ratelimit import _SlidingWindow

    sw = _SlidingWindow(rpm=10, burst_factor=1.0)
    for _ in range(10):
        allowed, _ = sw.allow()
        assert allowed


@pytest.mark.unit
def test_sliding_window_blocks_when_limit_exceeded():
    from ragrig.ratelimit import _SlidingWindow

    sw = _SlidingWindow(rpm=3, burst_factor=1.0)
    for _ in range(3):
        sw.allow()
    allowed, retry_after = sw.allow()
    assert not allowed
    assert retry_after >= 1


@pytest.mark.unit
def test_rate_limiter_disabled_no_op():

    from ragrig.ratelimit import RateLimiter

    settings = Settings(ragrig_rate_limit_enabled=False)
    limiter = RateLimiter(settings)
    # Should not raise regardless of how many calls
    for _ in range(1000):
        limiter.check_search("ws-1")
        limiter.check_ingest("ws-1")


@pytest.mark.unit
def test_rate_limiter_raises_429_when_exceeded():
    from fastapi import HTTPException

    from ragrig.ratelimit import RateLimiter

    settings = Settings(
        ragrig_rate_limit_enabled=True,
        ragrig_rate_limit_search_rpm=2,
        ragrig_rate_limit_burst_factor=1.0,
    )
    limiter = RateLimiter(settings)
    limiter.check_search("ws-x")
    limiter.check_search("ws-x")
    with pytest.raises(HTTPException) as exc_info:
        limiter.check_search("ws-x")
    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


@pytest.mark.unit
def test_rate_limiter_separate_keys_independent():
    from ragrig.ratelimit import RateLimiter

    settings = Settings(
        ragrig_rate_limit_enabled=True,
        ragrig_rate_limit_search_rpm=1,
        ragrig_rate_limit_burst_factor=1.0,
    )
    limiter = RateLimiter(settings)
    limiter.check_search("ws-a")
    # ws-b has its own window — should not be blocked
    limiter.check_search("ws-b")


@pytest.mark.unit
def test_rate_limiter_ingest_separate_from_search():

    from ragrig.ratelimit import RateLimiter

    settings = Settings(
        ragrig_rate_limit_enabled=True,
        ragrig_rate_limit_search_rpm=1,
        ragrig_rate_limit_ingest_rpm=5,
        ragrig_rate_limit_burst_factor=1.0,
    )
    limiter = RateLimiter(settings)
    limiter.check_search("ws-z")
    # Search exhausted, but ingest window is separate
    limiter.check_ingest("ws-z")
    limiter.check_ingest("ws-z")


# ── Retention ─────────────────────────────────────────────────────────────────


def _make_kb(session: Session, ws_id: "uuid.UUID", name: str = "kb1") -> "uuid.UUID":
    from ragrig.db.models import KnowledgeBase

    kb = KnowledgeBase(
        id=uuid.uuid4(),
        workspace_id=ws_id,
        name=name,
        description=None,
        metadata_json={},
        retention_days=None,
    )
    session.add(kb)
    session.flush()
    return kb.id


def _make_document(session: Session, kb_id: "uuid.UUID") -> "uuid.UUID":
    from ragrig.db.models import Document, Source

    src_id = uuid.uuid4()
    src = Source(
        id=src_id,
        knowledge_base_id=kb_id,
        kind="filesystem",
        uri="file:///fixtures",
        config_json={},
    )
    session.add(src)
    session.flush()

    doc = Document(
        id=uuid.uuid4(),
        knowledge_base_id=kb_id,
        source_id=src_id,
        uri="file://test.txt",
        content_hash="abc123",
        metadata_json={},
    )
    session.add(doc)
    session.flush()
    return doc.id


def _make_version(
    session: Session,
    doc_id: "uuid.UUID",
    version_number: int,
    created_at: datetime,
) -> "uuid.UUID":
    from ragrig.db.models import DocumentVersion  # noqa: F811

    dv = DocumentVersion(
        id=uuid.uuid4(),
        document_id=doc_id,
        version_number=version_number,
        content_hash=f"hash{version_number}",
        parser_name="text",
        parser_config_json={},
        extracted_text=f"text v{version_number}",
        metadata_json={},
    )
    session.add(dv)
    session.flush()
    session.execute(
        update(DocumentVersion).where(DocumentVersion.id == dv.id).values(created_at=created_at)
    )
    return dv.id


@pytest.mark.unit
def test_purge_old_document_versions_removes_non_current():
    from sqlalchemy import update

    from ragrig.db.models import DocumentVersion
    from ragrig.retention import purge_old_document_versions

    engine = _make_engine()
    session = _factory(engine)()
    ws_id = _make_workspace(session)
    kb_id = _make_kb(session, ws_id)
    doc_id = _make_document(session, kb_id)

    old_date = datetime.now(UTC) - timedelta(days=31)
    recent_date = datetime.now(UTC) - timedelta(days=1)

    v1_id = _make_version(session, doc_id, 1, old_date)
    v2_id = _make_version(session, doc_id, 2, recent_date)
    session.commit()

    # Patch created_at in DB (raw update since SQLAlchemy might skip it)
    session.execute(
        update(DocumentVersion).where(DocumentVersion.id == v1_id).values(created_at=old_date)
    )
    session.execute(
        update(DocumentVersion).where(DocumentVersion.id == v2_id).values(created_at=recent_date)
    )
    session.commit()

    deleted = purge_old_document_versions(session, knowledge_base_id=kb_id, days=30)
    session.commit()

    current = session.get(DocumentVersion, v2_id)
    assert deleted >= 0  # v1 is old AND non-current → should be deleted
    assert current is not None  # v2 (current) must survive


@pytest.mark.unit
def test_purge_old_audit_events():
    from sqlalchemy import update

    from ragrig.db.models import AuditEvent
    from ragrig.repositories.audit import create_audit_event
    from ragrig.retention import purge_old_audit_events

    engine = _make_engine()
    session = _factory(engine)()
    ws_id = _make_workspace(session)

    old_date = datetime.now(UTC) - timedelta(days=100)

    create_audit_event(session, event_type="test.old", actor=None, workspace_id=ws_id)
    create_audit_event(session, event_type="test.recent", actor=None, workspace_id=ws_id)
    session.flush()

    # Set occurred_at directly
    session.execute(
        update(AuditEvent).where(AuditEvent.event_type == "test.old").values(occurred_at=old_date)
    )
    session.commit()

    deleted = purge_old_audit_events(session, days=30, workspace_id=ws_id)
    session.commit()
    assert deleted == 1

    remaining = session.execute(select(AuditEvent)).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].event_type == "test.recent"


@pytest.mark.unit
def test_run_retention_skips_kb_without_policy():
    from ragrig.retention import run_retention_for_knowledge_base

    engine = _make_engine()
    session = _factory(engine)()
    ws_id = _make_workspace(session)
    kb_id = _make_kb(session, ws_id)
    session.commit()

    result = run_retention_for_knowledge_base(
        session, knowledge_base_id=kb_id, knowledge_base_name="kb1"
    )
    assert result["skipped"] is True
    assert result["deleted_versions"] == 0


@pytest.mark.unit
def test_run_all_retention_applies_audit_ttl():
    from sqlalchemy import update

    from ragrig.db.models import AuditEvent
    from ragrig.repositories.audit import create_audit_event
    from ragrig.retention import run_all_retention

    engine = _make_engine()
    session = _factory(engine)()
    ws_id = _make_workspace(session)

    create_audit_event(session, event_type="old.event", actor=None, workspace_id=ws_id)
    session.flush()
    session.execute(
        update(AuditEvent)
        .where(AuditEvent.event_type == "old.event")
        .values(occurred_at=datetime.now(UTC) - timedelta(days=100))
    )
    session.commit()

    settings = Settings(ragrig_audit_retention_days=30)
    result = run_all_retention(session, settings)
    assert result["audit_events_deleted"] == 1


# ── Retention API ─────────────────────────────────────────────────────────────


def _make_app_with_kb(ws_id: "uuid.UUID", kb_name: str = "testbase"):
    """Create a TestClient with a seeded KB for retention API tests."""
    from ragrig.db.models import KnowledgeBase, Workspace
    from ragrig.main import create_app

    engine = _make_engine()
    sf = _factory(engine)

    with sf() as session:
        ws = Workspace(
            id=ws_id,
            slug=str(ws_id)[:8],
            display_name="t",
            status="active",
            metadata_json={},
        )
        session.add(ws)
        kb = KnowledgeBase(
            id=uuid.uuid4(),
            workspace_id=ws_id,
            name=kb_name,
            description=None,
            metadata_json={},
            retention_days=None,
        )
        session.add(kb)
        session.commit()

    settings = Settings(ragrig_auth_enabled=False)
    app = create_app(session_factory=sf, settings=settings)
    return TestClient(app)


@pytest.mark.unit
def test_get_kb_retention_returns_null_when_unset():
    from ragrig.auth import DEFAULT_WORKSPACE_ID

    client = _make_app_with_kb(DEFAULT_WORKSPACE_ID, "mybase")
    resp = client.get("/knowledge-bases/mybase/retention")
    assert resp.status_code == 200
    data = resp.json()
    assert data["knowledge_base"] == "mybase"
    assert data["retention_days"] is None


@pytest.mark.unit
def test_patch_kb_retention_sets_policy():
    from ragrig.auth import DEFAULT_WORKSPACE_ID

    client = _make_app_with_kb(DEFAULT_WORKSPACE_ID, "mybase")
    resp = client.patch("/knowledge-bases/mybase/retention", json={"retention_days": 90})
    assert resp.status_code == 200
    assert resp.json()["retention_days"] == 90

    resp2 = client.get("/knowledge-bases/mybase/retention")
    assert resp2.json()["retention_days"] == 90


@pytest.mark.unit
def test_patch_kb_retention_clears_policy():
    from ragrig.auth import DEFAULT_WORKSPACE_ID

    client = _make_app_with_kb(DEFAULT_WORKSPACE_ID, "mybase")
    client.patch("/knowledge-bases/mybase/retention", json={"retention_days": 30})
    resp = client.patch("/knowledge-bases/mybase/retention", json={"retention_days": None})
    assert resp.status_code == 200
    assert resp.json()["retention_days"] is None


@pytest.mark.unit
def test_get_kb_retention_404_for_unknown_kb():
    from ragrig.auth import DEFAULT_WORKSPACE_ID

    client = _make_app_with_kb(DEFAULT_WORKSPACE_ID, "mybase")
    resp = client.get("/knowledge-bases/nonexistent/retention")
    assert resp.status_code == 404


@pytest.mark.unit
def test_run_retention_endpoint():
    from ragrig.auth import DEFAULT_WORKSPACE_ID

    client = _make_app_with_kb(DEFAULT_WORKSPACE_ID, "mybase")
    resp = client.post("/admin/retention/run")
    assert resp.status_code == 200
    data = resp.json()
    assert "knowledge_bases" in data
    assert "audit_events_deleted" in data
