"""P3c tests: usage tracking + budgets + alerting.

Covers:
- ``record_usage_events`` writes one row per operation
- ``aggregate_usage`` rolls up totals and supports group_by
- ``daily_timeseries`` buckets by day
- ``evaluate_budget`` fires alert at threshold and latches per period
- ``evaluate_budget`` reports hard_cap_breached when over limit
- REST: GET /usage, GET /usage/timeseries
- REST: PUT/GET/DELETE /budgets
- REST: POST /admin/usage/evaluate
- /retrieval/answer records usage events as a side effect
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session

from ragrig.config import Settings
from ragrig.db.models import Base, Budget, KnowledgeBase, UsageEvent, Workspace
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.main import create_app
from ragrig.usage import (
    aggregate_usage,
    current_month_window,
    daily_timeseries,
    evaluate_budget,
    record_usage_events,
)


@contextmanager
def _engine(tmp_path: Path) -> Iterator:
    eng = create_engine(f"sqlite+pysqlite:///{tmp_path / 'p3c.db'}", future=True)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


def _make_workspace(session: Session) -> uuid.UUID:
    wid = uuid.uuid4()
    session.add(
        Workspace(
            id=wid,
            slug=str(wid)[:8],
            display_name="t",
            status="active",
            metadata_json={},
        )
    )
    session.flush()
    return wid


# ── Unit ─────────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_current_month_window_returns_first_to_first() -> None:
    win = current_month_window(datetime(2026, 5, 16, 12, tzinfo=UTC))
    assert win.start == datetime(2026, 5, 1, tzinfo=UTC)
    assert win.end == datetime(2026, 6, 1, tzinfo=UTC)


@pytest.mark.unit
def test_current_month_window_year_rollover() -> None:
    win = current_month_window(datetime(2026, 12, 30, tzinfo=UTC))
    assert win.start == datetime(2026, 12, 1, tzinfo=UTC)
    assert win.end == datetime(2027, 1, 1, tzinfo=UTC)


@pytest.mark.unit
def test_record_usage_events_inserts_rows(tmp_path: Path) -> None:
    with _engine(tmp_path) as eng:
        with Session(eng, expire_on_commit=False) as session:
            ws_id = _make_workspace(session)
            n = record_usage_events(
                session,
                workspace_id=ws_id,
                user_id=None,
                operations=[
                    {
                        "operation": "embedding",
                        "provider": "openai",
                        "model": "text-embedding-3-small",
                        "input_tokens_estimated": 100,
                        "output_tokens_estimated": 0,
                        "total_cost_usd_estimated": 0.002,
                        "latency_ms": 120.0,
                    },
                    {
                        "operation": "answer_generation",
                        "provider": "openai",
                        "model": "gpt-4o-mini",
                        "input_tokens_estimated": 200,
                        "output_tokens_estimated": 80,
                        "total_cost_usd_estimated": 0.005,
                        "latency_ms": 850.0,
                    },
                ],
            )
            assert n == 2
            rows = session.scalars(select(UsageEvent)).all()
            assert len(rows) == 2
            assert {r.operation for r in rows} == {"embedding", "answer_generation"}


@pytest.mark.unit
def test_aggregate_usage_totals_and_grouping(tmp_path: Path) -> None:
    with _engine(tmp_path) as eng:
        with Session(eng, expire_on_commit=False) as session:
            ws_id = _make_workspace(session)
            record_usage_events(
                session,
                workspace_id=ws_id,
                user_id=None,
                operations=[
                    {
                        "operation": "embedding",
                        "provider": "openai",
                        "model": "m1",
                        "input_tokens_estimated": 10,
                        "output_tokens_estimated": 0,
                        "total_cost_usd_estimated": 0.10,
                        "latency_ms": 50,
                    },
                    {
                        "operation": "answer_generation",
                        "provider": "openai",
                        "model": "m2",
                        "input_tokens_estimated": 20,
                        "output_tokens_estimated": 5,
                        "total_cost_usd_estimated": 0.30,
                        "latency_ms": 100,
                    },
                ],
            )
            totals = aggregate_usage(session, workspace_id=ws_id)
            assert totals["event_count"] == 2
            assert totals["input_tokens"] == 30
            assert totals["output_tokens"] == 5
            assert abs(totals["cost_usd"] - 0.40) < 1e-6

            grouped = aggregate_usage(session, workspace_id=ws_id, group_by="operation")
            keys = {g["key"] for g in grouped["groups"]}
            assert keys == {"embedding", "answer_generation"}

            record_usage_events(
                session,
                workspace_id=ws_id,
                user_id=None,
                operations=[
                    {
                        "operation": "answer_generation",
                        "provider": "openai",
                        "model": "m3",
                        "input_tokens_estimated": 30,
                        "output_tokens_estimated": 10,
                        "total_cost_usd_estimated": 0.20,
                        "latency_ms": 200,
                    },
                ],
                request_metadata={"role": "admin_reviewer"},
            )
            by_role = aggregate_usage(session, workspace_id=ws_id, group_by="role")
            role_group = next(g for g in by_role["groups"] if g["key"] == "admin_reviewer")
            assert role_group["cost_usd"] == 0.2
            assert role_group["avg_latency_ms"] == 200.0


@pytest.mark.unit
def test_daily_timeseries_returns_buckets(tmp_path: Path) -> None:
    with _engine(tmp_path) as eng:
        with Session(eng, expire_on_commit=False) as session:
            ws_id = _make_workspace(session)
            record_usage_events(
                session,
                workspace_id=ws_id,
                user_id=None,
                operations=[
                    {
                        "operation": "x",
                        "provider": "p",
                        "model": "m",
                        "input_tokens_estimated": 1,
                        "output_tokens_estimated": 0,
                        "total_cost_usd_estimated": 0.05,
                        "latency_ms": 10,
                    }
                ],
            )
            ts = daily_timeseries(session, workspace_id=ws_id, days=7)
            assert ts, "expected at least one bucket"
            assert ts[0]["count"] >= 1


@pytest.mark.unit
def test_evaluate_budget_no_budget_returns_zero(tmp_path: Path) -> None:
    with _engine(tmp_path) as eng:
        with Session(eng, expire_on_commit=False) as session:
            ws_id = _make_workspace(session)
            result = evaluate_budget(
                session, workspace_id=ws_id, settings=Settings(), fire_alert=False
            )
            assert result.budget is None
            assert result.period_spend_usd == 0.0
            assert result.over_threshold is False


@pytest.mark.unit
def test_evaluate_budget_threshold_and_hard_cap(tmp_path: Path) -> None:
    with _engine(tmp_path) as eng:
        with Session(eng, expire_on_commit=False) as session:
            ws_id = _make_workspace(session)
            session.add(
                Budget(
                    id=uuid.uuid4(),
                    workspace_id=ws_id,
                    period="monthly",
                    limit_usd=1.00,
                    alert_threshold_pct=80,
                    hard_cap=True,
                )
            )
            session.commit()
            record_usage_events(
                session,
                workspace_id=ws_id,
                user_id=None,
                operations=[
                    {
                        "operation": "answer_generation",
                        "provider": "p",
                        "model": "m",
                        "input_tokens_estimated": 1,
                        "output_tokens_estimated": 1,
                        "total_cost_usd_estimated": 1.20,
                        "latency_ms": 1,
                    }
                ],
            )
            result = evaluate_budget(
                session, workspace_id=ws_id, settings=Settings(), fire_alert=False
            )
            assert result.over_threshold is True
            assert result.over_limit is True
            assert result.hard_cap_breached is True


@pytest.mark.unit
def test_evaluate_budget_alert_latches(tmp_path: Path) -> None:
    """A second evaluation in the same month should not fire again."""
    with _engine(tmp_path) as eng:
        with Session(eng, expire_on_commit=False) as session:
            ws_id = _make_workspace(session)
            session.add(
                Budget(
                    id=uuid.uuid4(),
                    workspace_id=ws_id,
                    period="monthly",
                    limit_usd=1.00,
                    alert_threshold_pct=50,
                    hard_cap=False,
                )
            )
            session.commit()
            record_usage_events(
                session,
                workspace_id=ws_id,
                user_id=None,
                operations=[
                    {
                        "operation": "x",
                        "provider": "p",
                        "model": "m",
                        "input_tokens_estimated": 1,
                        "output_tokens_estimated": 0,
                        "total_cost_usd_estimated": 0.80,
                        "latency_ms": 1,
                    }
                ],
            )
            first = evaluate_budget(
                session, workspace_id=ws_id, settings=Settings(), fire_alert=True
            )
            second = evaluate_budget(
                session, workspace_id=ws_id, settings=Settings(), fire_alert=True
            )
            assert first.alert_fired is True
            assert second.alert_fired is False


@pytest.mark.unit
def test_evaluate_budget_resets_after_month_rollover(tmp_path: Path) -> None:
    with _engine(tmp_path) as eng:
        with Session(eng, expire_on_commit=False) as session:
            ws_id = _make_workspace(session)
            budget_id = uuid.uuid4()
            session.add(
                Budget(
                    id=budget_id,
                    workspace_id=ws_id,
                    period="monthly",
                    limit_usd=1.00,
                    alert_threshold_pct=50,
                    hard_cap=False,
                )
            )
            session.commit()
            # Backdate last_alert_at into a previous month
            session.execute(
                update(Budget)
                .where(Budget.id == budget_id)
                .values(last_alert_at=datetime.now(UTC) - timedelta(days=45))
            )
            session.commit()
            # No usage yet → under threshold; should not fire
            result = evaluate_budget(
                session, workspace_id=ws_id, settings=Settings(), fire_alert=True
            )
            assert result.alert_fired is False


# ── REST API ────────────────────────────────────────────────────────────────


def _seed_kb(engine, kb_name: str = "kb1") -> None:
    docs_root = Path(engine.url.database).parent / "docs"
    docs_root.mkdir(exist_ok=True)
    (docs_root / "intro.md").write_text(
        "# Intro\n\nRAGRig tracks cost and latency for every model call.\n",
        encoding="utf-8",
    )
    with Session(engine, expire_on_commit=False) as session:
        ingest_local_directory(session=session, knowledge_base_name=kb_name, root_path=docs_root)
        index_knowledge_base(
            session=session, knowledge_base_name=kb_name, chunk_size=48, chunk_overlap=4
        )


def _make_client(tmp_path: Path) -> TestClient:
    with _engine(tmp_path) as eng:
        _seed_kb(eng)

        def sf() -> Session:
            return Session(eng, expire_on_commit=False)

        settings = Settings(ragrig_auth_enabled=False)
        app = create_app(check_database=lambda: None, session_factory=sf, settings=settings)
        return TestClient(app)


@pytest.mark.integration
def test_usage_endpoint_returns_empty_for_new_workspace(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.get("/usage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["event_count"] == 0
    assert data["cost_usd"] == 0


@pytest.mark.integration
def test_put_and_get_budget(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    resp = client.put(
        "/budgets",
        json={"limit_usd": 5.0, "alert_threshold_pct": 75, "hard_cap": False},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()["budget"]
    assert body["limit_usd"] == 5.0
    assert body["alert_threshold_pct"] == 75

    got = client.get("/budgets")
    assert got.status_code == 200
    assert got.json()["budget"]["limit_usd"] == 5.0


@pytest.mark.integration
def test_put_budget_replaces_existing(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.put("/budgets", json={"limit_usd": 1.0})
    client.put("/budgets", json={"limit_usd": 10.0, "alert_threshold_pct": 90})
    resp = client.get("/budgets")
    assert resp.json()["budget"]["limit_usd"] == 10.0
    assert resp.json()["budget"]["alert_threshold_pct"] == 90


@pytest.mark.integration
def test_delete_budget(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.put("/budgets", json={"limit_usd": 2.0})
    assert client.delete("/budgets").status_code == 204
    assert client.get("/budgets").json()["budget"] is None


@pytest.mark.integration
def test_delete_budget_404_when_missing(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    assert client.delete("/budgets").status_code == 404


@pytest.mark.integration
def test_answer_request_records_usage_events(tmp_path: Path) -> None:
    """A successful /retrieval/answer should write at least one UsageEvent."""
    with _engine(tmp_path) as eng:
        _seed_kb(eng)

        def sf() -> Session:
            return Session(eng, expire_on_commit=False)

        settings = Settings(ragrig_auth_enabled=False)
        app = create_app(check_database=lambda: None, session_factory=sf, settings=settings)
        client = TestClient(app)
        resp = client.post(
            "/retrieval/answer",
            json={
                "knowledge_base": "kb1",
                "query": "What is tracked?",
                "role": "admin_reviewer",
                "role_model_config": {
                    "admin_reviewer": {
                        "answer_provider": "deterministic-local",
                        "answer_model": "precise-answer-model",
                    }
                },
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["model"] == "precise-answer-model"
        assert resp.json()["role_model_selection"]["answer_model"] == "precise-answer-model"

        with sf() as session:
            rows = session.scalars(select(UsageEvent)).all()
            assert len(rows) >= 1
            usage = client.get("/usage").json()
            assert usage["event_count"] >= 1
            by_role = client.get("/usage?group_by=role").json()
            assert any(group["key"] == "admin_reviewer" for group in by_role["groups"])


@pytest.mark.integration
def test_role_model_config_persists_on_knowledge_base(tmp_path: Path) -> None:
    with _engine(tmp_path) as eng:
        _seed_kb(eng)

        def sf() -> Session:
            return Session(eng, expire_on_commit=False)

        with sf() as session:
            kb = session.scalars(select(KnowledgeBase).where(KnowledgeBase.name == "kb1")).one()
            kb_id = str(kb.id)

        settings = Settings(ragrig_auth_enabled=False)
        app = create_app(check_database=lambda: None, session_factory=sf, settings=settings)
        client = TestClient(app)
        config = {
            "admin_reviewer": {
                "answer_provider": "deterministic-local",
                "answer_model": "persisted-answer-model",
            },
            "viewer_analyst": {
                "answer_provider": "deterministic-local",
                "answer_model": "economy-answer-model",
            },
        }

        saved = client.put(f"/knowledge-bases/{kb_id}/role-model-config", json={"config": config})
        assert saved.status_code == 200, saved.text
        assert saved.json()["roles"] == ["admin_reviewer", "viewer_analyst"]
        assert saved.json()["config"]["admin_reviewer"]["answer_model"] == "persisted-answer-model"

        loaded = client.get(f"/knowledge-bases/{kb_id}/role-model-config")
        assert loaded.status_code == 200
        assert loaded.json()["config"]["viewer_analyst"]["answer_model"] == "economy-answer-model"

        resp = client.post(
            "/retrieval/answer",
            json={
                "knowledge_base": "kb1",
                "query": "What is tracked?",
                "role": "admin_reviewer",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["model"] == "persisted-answer-model"
        assert resp.json()["role_model_selection"]["source"] == "knowledge_base"


@pytest.mark.integration
def test_usage_timeseries_endpoint(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.post("/retrieval/answer", json={"knowledge_base": "kb1", "query": "tracked?"})
    resp = client.get("/usage/timeseries?days=7")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items, "expected at least one daily bucket"


@pytest.mark.integration
def test_admin_evaluate_endpoint(tmp_path: Path) -> None:
    client = _make_client(tmp_path)
    client.put("/budgets", json={"limit_usd": 1000.0, "alert_threshold_pct": 80})
    resp = client.post("/admin/usage/evaluate")
    assert resp.status_code == 200
    body = resp.json()
    assert "period_spend_usd" in body
    assert body["limit_usd"] == 1000.0
