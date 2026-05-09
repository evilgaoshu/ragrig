import pytest

from scripts.db_check import REQUIRED_TABLES, evaluate_database_state

pytestmark = pytest.mark.unit


class FakeCursor:
    def __init__(self, results: list[tuple[object, ...]]) -> None:
        self.results = results
        self.executed: list[str] = []

    def execute(self, query: str, params: object | None = None) -> None:
        self.executed.append(query)

    def fetchone(self) -> tuple[object, ...] | None:
        return self.results.pop(0)

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.results.pop(0)


def test_evaluate_database_state_reports_extension_and_required_tables() -> None:
    cursor = FakeCursor(
        results=[
            ("vector",),
            [(table_name,) for table_name in REQUIRED_TABLES],
            ("20260503_0001",),
        ]
    )

    state = evaluate_database_state(cursor, expected_revision="20260503_0001")

    assert state["extension"] == "vector"
    assert state["missing_tables"] == []
    assert state["current_revision"] == "20260503_0001"
    assert state["revision_matches_head"] is True
    assert len(cursor.executed) == 3
