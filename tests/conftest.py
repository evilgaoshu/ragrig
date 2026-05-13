from __future__ import annotations

import gc
from collections.abc import Iterator

import pytest
import sqlalchemy
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, close_all_sessions

from ragrig.db.models import Base

_SQLITE_ENGINES: set[Engine] = set()
_ORIGINAL_CREATE_ENGINE = sqlalchemy.create_engine


def _tracking_create_engine(*args, **kwargs) -> Engine:
    engine = _ORIGINAL_CREATE_ENGINE(*args, **kwargs)
    if engine.url.get_backend_name() == "sqlite":
        _SQLITE_ENGINES.add(engine)
    return engine


sqlalchemy.create_engine = _tracking_create_engine


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def _dispose_sqlite_engines() -> None:
    close_all_sessions()
    for engine in list(_SQLITE_ENGINES):
        engine.dispose()
    _SQLITE_ENGINES.clear()
    gc.collect()


@pytest.fixture(autouse=True)
def _cleanup_sqlite_engines() -> Iterator[None]:
    yield
    _dispose_sqlite_engines()


@pytest.fixture
def sqlite_session() -> Iterator[Session]:
    engine = sqlalchemy.create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()
