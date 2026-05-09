from collections.abc import Iterator

import pytest

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
