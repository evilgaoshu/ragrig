from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest

from ragrig.db.models import Chunk, ConflictReview
from ragrig.indexing.conflict_detection import (
    find_conflicting_chunk,
    record_conflict,
    resolve_conflict,
)

pytestmark = pytest.mark.unit


class _FetchOneResult:
    def __init__(self, row: tuple[str, float] | None) -> None:
        self._row = row

    def fetchone(self) -> tuple[str, float] | None:
        return self._row


class _ScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> "_ScalarResult":
        return self

    def all(self) -> list[Any]:
        return self._rows


class _Dialect:
    def __init__(self, name: str) -> None:
        self.name = name


class _Bind:
    def __init__(self, dialect_name: str) -> None:
        self.dialect = _Dialect(dialect_name)


class _FakeSession:
    def __init__(
        self,
        *,
        dialect_name: str = "postgresql",
        row: tuple[str, float] | None = None,
        bind_error: Exception | None = None,
        execute_error: Exception | None = None,
        objects: dict[tuple[type[Any], uuid.UUID], Any] | None = None,
        embeddings: dict[uuid.UUID, list[Any]] | None = None,
    ) -> None:
        self._dialect_name = dialect_name
        self._row = row
        self._bind_error = bind_error
        self._execute_error = execute_error
        self._objects = objects or {}
        self._embeddings = embeddings or {}
        self.added: list[Any] = []
        self.executed_params: dict[str, Any] | None = None
        self.flush_count = 0

    def get_bind(self) -> _Bind:
        if self._bind_error is not None:
            raise self._bind_error
        return _Bind(self._dialect_name)

    def execute(self, _stmt: Any, params: dict[str, Any] | None = None) -> Any:
        if self._execute_error is not None:
            raise self._execute_error
        self.executed_params = params
        if params is not None:
            return _FetchOneResult(self._row)
        chunk_id = getattr(_stmt.whereclause.right, "value", None)
        return _ScalarResult(self._embeddings.get(chunk_id, []))

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def get(self, model: type[Any], obj_id: uuid.UUID) -> Any:
        return self._objects.get((model, obj_id))

    def flush(self) -> None:
        self.flush_count += 1


def test_find_conflicting_chunk_skips_non_postgres_and_bind_errors() -> None:
    kb_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    assert (
        find_conflicting_chunk(
            _FakeSession(dialect_name="sqlite"),
            new_vector=[0.1, 0.2],
            knowledge_base_id=kb_id,
            new_chunk_id=chunk_id,
        )
        is None
    )
    assert (
        find_conflicting_chunk(
            _FakeSession(bind_error=RuntimeError("no bind")),
            new_vector=[0.1, 0.2],
            knowledge_base_id=kb_id,
            new_chunk_id=chunk_id,
        )
        is None
    )


def test_find_conflicting_chunk_returns_pgvector_match_and_query_params() -> None:
    kb_id = uuid.uuid4()
    new_chunk_id = uuid.uuid4()
    existing_chunk_id = uuid.uuid4()
    session = _FakeSession(row=(str(existing_chunk_id), 0.9375))

    result = find_conflicting_chunk(
        session,
        new_vector=[0.1, 0.2, 0.3],
        knowledge_base_id=kb_id,
        new_chunk_id=new_chunk_id,
        threshold=0.9,
    )

    assert result == (existing_chunk_id, 0.9375)
    assert session.executed_params == {
        "vec": "[0.1,0.2,0.3]",
        "kb_id": str(kb_id),
        "exclude_id": str(new_chunk_id),
        "max_dist": pytest.approx(0.1),
    }


def test_find_conflicting_chunk_returns_none_for_no_match_or_query_failure() -> None:
    kb_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    assert (
        find_conflicting_chunk(
            _FakeSession(row=None),
            new_vector=[0.1],
            knowledge_base_id=kb_id,
            new_chunk_id=chunk_id,
        )
        is None
    )
    assert (
        find_conflicting_chunk(
            _FakeSession(execute_error=RuntimeError("pgvector unavailable")),
            new_vector=[0.1],
            knowledge_base_id=kb_id,
            new_chunk_id=chunk_id,
        )
        is None
    )


def test_record_conflict_adds_pending_review_with_rounded_similarity() -> None:
    session = _FakeSession()
    kb_id = uuid.uuid4()
    new_chunk_id = uuid.uuid4()
    existing_chunk_id = uuid.uuid4()

    review = record_conflict(
        session,
        knowledge_base_id=kb_id,
        new_chunk_id=new_chunk_id,
        existing_chunk_id=existing_chunk_id,
        similarity=0.923456789,
        extra_metadata={"source": "unit"},
    )

    assert session.added == [review]
    assert review.knowledge_base_id == kb_id
    assert review.new_chunk_id == new_chunk_id
    assert review.existing_chunk_id == existing_chunk_id
    assert review.similarity == 0.923457
    assert review.status == "pending"
    assert review.metadata_json == {"source": "unit"}


def test_resolve_conflict_validates_state_and_soft_deletes_embeddings() -> None:
    conflict_id = uuid.uuid4()
    new_chunk_id = uuid.uuid4()
    existing_chunk_id = uuid.uuid4()
    review = SimpleNamespace(
        status="pending",
        new_chunk_id=new_chunk_id,
        existing_chunk_id=existing_chunk_id,
        resolution=None,
        resolved_by=None,
        resolved_at=None,
    )
    embedding = SimpleNamespace(metadata_json={"provider": "test"})
    session = _FakeSession(
        objects={(ConflictReview, conflict_id): review},
        embeddings={existing_chunk_id: [embedding]},
    )

    resolved = resolve_conflict(
        session,
        conflict_id=conflict_id,
        resolution="keep_new",
        resolved_by="alice",
    )

    assert resolved is review
    assert review.status == "resolved_keep_new"
    assert review.resolution == "keep_new"
    assert review.resolved_by == "alice"
    assert review.resolved_at is not None
    assert embedding.metadata_json == {"provider": "test", "conflict_resolved": True}
    assert session.flush_count == 2

    with pytest.raises(ValueError, match="Invalid resolution"):
        resolve_conflict(session, conflict_id=conflict_id, resolution="invalid")
    with pytest.raises(ValueError, match="not found"):
        resolve_conflict(_FakeSession(), conflict_id=uuid.uuid4(), resolution="keep_both")
    with pytest.raises(ValueError, match="already resolved"):
        resolve_conflict(session, conflict_id=conflict_id, resolution="keep_both")


def test_resolve_conflict_auto_recency_chooses_newer_chunk_or_keep_new_fallback() -> None:
    now = datetime.now(timezone.utc)
    conflict_id = uuid.uuid4()
    fallback_conflict_id = uuid.uuid4()
    new_chunk_id = uuid.uuid4()
    existing_chunk_id = uuid.uuid4()
    fallback_new_chunk_id = uuid.uuid4()
    fallback_existing_chunk_id = uuid.uuid4()
    review = SimpleNamespace(
        status="pending",
        new_chunk_id=new_chunk_id,
        existing_chunk_id=existing_chunk_id,
        resolution=None,
        resolved_by=None,
        resolved_at=None,
    )
    fallback_review = SimpleNamespace(
        status="pending",
        new_chunk_id=fallback_new_chunk_id,
        existing_chunk_id=fallback_existing_chunk_id,
        resolution=None,
        resolved_by=None,
        resolved_at=None,
    )
    old_embedding = SimpleNamespace(metadata_json={})
    fallback_embedding = SimpleNamespace(metadata_json={})
    session = _FakeSession(
        objects={
            (ConflictReview, conflict_id): review,
            (Chunk, new_chunk_id): SimpleNamespace(created_at=now),
            (Chunk, existing_chunk_id): SimpleNamespace(created_at=now - timedelta(seconds=1)),
            (ConflictReview, fallback_conflict_id): fallback_review,
        },
        embeddings={
            existing_chunk_id: [old_embedding],
            fallback_existing_chunk_id: [fallback_embedding],
        },
    )

    resolved = resolve_conflict(
        session,
        conflict_id=conflict_id,
        resolution="auto_recency",
    )
    fallback = resolve_conflict(
        session,
        conflict_id=fallback_conflict_id,
        resolution="auto_recency",
    )

    assert resolved.status == "resolved_auto_recency"
    assert resolved.resolution == "keep_new"
    assert old_embedding.metadata_json == {"conflict_resolved": True}
    assert fallback.status == "resolved_auto_recency"
    assert fallback.resolution == "keep_new"
    assert fallback_embedding.metadata_json == {"conflict_resolved": True}
