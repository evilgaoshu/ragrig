from __future__ import annotations

import gc
import sqlite3
import warnings
from pathlib import Path

import sqlalchemy
from sqlalchemy import text

import tests.conftest as test_conftest


def test_sqlalchemy_sqlite_engine_is_tracked_for_teardown_cleanup(tmp_path: Path) -> None:
    engine = sqlalchemy.create_engine(f"sqlite+pysqlite:///{tmp_path / 'tracked.db'}", future=True)

    with engine.connect() as connection:
        connection.execute(text("select 1"))

    assert engine in test_conftest._SQLITE_ENGINES


def test_dispose_sqlite_engines_cleans_tracked_sqlalchemy_sqlite_engine(tmp_path: Path) -> None:
    gc.collect()

    with warnings.catch_warnings(record=True) as records:
        warnings.simplefilter("always", ResourceWarning)
        engine = sqlalchemy.create_engine(
            f"sqlite+pysqlite:///{tmp_path / 'cleanup.db'}",
            future=True,
        )
        session = sqlalchemy.orm.Session(engine, expire_on_commit=False)
        session.execute(text("select 1"))

        assert engine in test_conftest._SQLITE_ENGINES

        test_conftest._dispose_sqlite_engines()

        del session
        del engine
        gc.collect()

    assert test_conftest._SQLITE_ENGINES == set()
    resource_warnings = [
        warning for warning in records if isinstance(warning.message, ResourceWarning)
    ]
    assert resource_warnings == []


def test_direct_sqlite3_leak_path_remains_outside_sqlalchemy_cleanup_scope(tmp_path: Path) -> None:
    tracked_before = set(test_conftest._SQLITE_ENGINES)

    connection = sqlite3.connect(tmp_path / "raw-leak.db")
    connection.execute("select 1")

    assert test_conftest._SQLITE_ENGINES == tracked_before

    del connection
    gc.collect()
