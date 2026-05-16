from __future__ import annotations

import pytest

from ragrig.config import Settings
from ragrig.health import build_reranker_health, create_database_check

pytestmark = pytest.mark.unit


class FakeCursor:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.fetchone_called = False

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, statement: str) -> None:
        self.executed.append(statement)

    def fetchone(self) -> tuple[int]:
        self.fetchone_called = True
        return (1,)


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self._cursor


def test_create_database_check_runs_select_one(monkeypatch) -> None:
    cursor = FakeCursor()
    calls: list[str] = []

    def fake_connect(database_url: str) -> FakeConnection:
        calls.append(database_url)
        return FakeConnection(cursor)

    monkeypatch.setattr("ragrig.health.psycopg.connect", fake_connect)

    create_database_check(Settings(database_url="postgresql://example/test"))()

    assert calls == ["postgresql://example/test"]
    assert cursor.executed == ["SELECT 1"]
    assert cursor.fetchone_called is True


def test_reranker_health_blocks_fake_fallback_in_production_by_default() -> None:
    health = build_reranker_health(Settings(app_env="production"))

    assert health == {
        "status": "blocked",
        "provider": "reranker.bge",
        "fake_reranker_allowed": False,
        "policy": "production_requires_real_reranker",
        "detail": (
            "Fake reranker fallback is disabled in production; configure a real reranker "
            "or set RAGRIG_ALLOW_FAKE_RERANKER=true."
        ),
        "app_env": "production",
    }
