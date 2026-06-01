from __future__ import annotations

import pytest
from prometheus_client import generate_latest

from ragrig.config import Settings
from ragrig.db import engine as db_engine

pytestmark = pytest.mark.unit


def test_create_db_engine_uses_explicit_settings() -> None:
    engine = db_engine.create_db_engine(
        Settings(database_url="sqlite+pysqlite:///:memory:"),
    )

    assert engine.url.render_as_string(hide_password=False) == "sqlite+pysqlite:///:memory:"
    assert engine.pool._pre_ping is True
    engine.dispose()


def test_create_db_engine_instruments_pool_metrics(tmp_path) -> None:
    engine = db_engine.create_db_engine(
        Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'pool-metrics.db'}"),
    )

    with engine.connect() as connection:
        connection.exec_driver_sql("SELECT 1")

    payload = generate_latest().decode("utf-8")
    assert "ragrig_db_pool_checkouts_total" in payload
    assert "ragrig_db_pool_checkins_total" in payload
    assert "ragrig_db_pool_checked_out" in payload
    assert "ragrig_db_pool_size" in payload
    engine.dispose()


def test_create_db_engine_applies_postgresql_pool_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    fake_engine = object()

    def fake_create_engine(url: str, **kwargs: object) -> object:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return fake_engine

    monkeypatch.setattr(db_engine, "create_engine", fake_create_engine)
    monkeypatch.setattr(db_engine, "setup_db_pool_metrics", lambda _engine: None)

    engine = db_engine.create_db_engine(
        Settings(
            database_url="postgresql://user:pass@localhost:5432/ragrig",
            ragrig_db_pool_size=7,
            ragrig_db_max_overflow=11,
            ragrig_db_pool_recycle=123,
        ),
    )

    assert engine is fake_engine
    assert captured["url"] == "postgresql+psycopg://user:pass@localhost:5432/ragrig"
    assert captured["kwargs"] == {
        "pool_pre_ping": True,
        "pool_size": 7,
        "max_overflow": 11,
        "pool_recycle": 123,
    }


def test_create_db_engine_rejects_default_database_url_in_protected_env() -> None:
    with pytest.raises(RuntimeError, match="default development database URL"):
        db_engine.create_db_engine(Settings(app_env="production"))


def test_create_db_engine_omits_pool_sizing_for_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    fake_engine = object()

    def fake_create_engine(url: str, **kwargs: object) -> object:
        captured["url"] = url
        captured["kwargs"] = kwargs
        return fake_engine

    monkeypatch.setattr(db_engine, "create_engine", fake_create_engine)
    monkeypatch.setattr(db_engine, "setup_db_pool_metrics", lambda _engine: None)

    db_engine.create_db_engine(Settings(database_url="sqlite+pysqlite:///:memory:"))

    assert captured["kwargs"] == {"pool_pre_ping": True}


def test_get_db_engine_uses_cached_factory(monkeypatch) -> None:
    created = []

    def fake_create_db_engine():
        marker = object()
        created.append(marker)
        return marker

    db_engine.get_db_engine.cache_clear()
    monkeypatch.setattr(db_engine, "create_db_engine", fake_create_db_engine)

    first = db_engine.get_db_engine()
    second = db_engine.get_db_engine()

    assert first is second
    assert created == [first]
    db_engine.get_db_engine.cache_clear()
