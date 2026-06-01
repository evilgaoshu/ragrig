from collections.abc import Iterator

import pytest

import ragrig.db.session as db_session
from ragrig.db.session import get_db_session

pytestmark = pytest.mark.unit


class FakeSession:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_get_db_session_yields_and_closes_session() -> None:
    created: list[FakeSession] = []

    def factory() -> FakeSession:
        session = FakeSession()
        created.append(session)
        return session

    dependency: Iterator[FakeSession] = get_db_session(factory)
    session = next(dependency)

    assert session is created[0]

    try:
        next(dependency)
    except StopIteration:
        pass

    assert session.closed is True


def test_sessionlocal_binds_engine_lazily(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    class FakeSessionFactory:
        def __call__(self) -> FakeSession:
            return FakeSession()

    def fake_get_db_engine() -> object:
        nonlocal calls
        calls += 1
        return object()

    def fake_sessionmaker(**_kwargs: object) -> FakeSessionFactory:
        return FakeSessionFactory()

    monkeypatch.setattr(db_session, "_session_factory", None)
    monkeypatch.setattr(db_session, "get_db_engine", fake_get_db_engine)
    monkeypatch.setattr(db_session, "sessionmaker", fake_sessionmaker)

    assert calls == 0

    first = db_session.SessionLocal()
    second = db_session.SessionLocal()

    assert isinstance(first, FakeSession)
    assert isinstance(second, FakeSession)
    assert calls == 1
