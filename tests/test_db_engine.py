from __future__ import annotations

from ragrig.config import Settings
from ragrig.db import engine as db_engine


def test_create_db_engine_uses_explicit_settings() -> None:
    engine = db_engine.create_db_engine(
        Settings(database_url="sqlite+pysqlite:///:memory:"),
    )

    assert engine.url.render_as_string(hide_password=False) == "sqlite+pysqlite:///:memory:"
    assert engine.pool._pre_ping is True
    engine.dispose()


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
