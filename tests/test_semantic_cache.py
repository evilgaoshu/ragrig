"""Tests for semantic_cache module."""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from ragrig.semantic_cache import (
    CacheHit,
    SemanticCacheConfig,
    _cosine_similarity,
    increment_hit_count,
    invalidate_cache,
    lookup_cache,
    store_cache,
)

# ---------------------------------------------------------------------------
# SemanticCacheConfig validation
# ---------------------------------------------------------------------------


def test_config_defaults() -> None:
    cfg = SemanticCacheConfig()
    assert cfg.similarity_threshold == 0.95
    assert cfg.ttl_seconds == 3600
    assert cfg.max_entries_per_kb == 500


def test_config_invalid_threshold_zero() -> None:
    with pytest.raises(ValueError, match="similarity_threshold"):
        SemanticCacheConfig(similarity_threshold=0.0)


def test_config_invalid_threshold_negative() -> None:
    with pytest.raises(ValueError, match="similarity_threshold"):
        SemanticCacheConfig(similarity_threshold=-0.1)


def test_config_threshold_one_is_valid() -> None:
    cfg = SemanticCacheConfig(similarity_threshold=1.0)
    assert cfg.similarity_threshold == 1.0


def test_config_invalid_ttl_zero() -> None:
    with pytest.raises(ValueError, match="ttl_seconds"):
        SemanticCacheConfig(ttl_seconds=0)


def test_config_invalid_ttl_negative() -> None:
    with pytest.raises(ValueError, match="ttl_seconds"):
        SemanticCacheConfig(ttl_seconds=-1)


def test_config_ttl_none_is_valid() -> None:
    cfg = SemanticCacheConfig(ttl_seconds=None)
    assert cfg.ttl_seconds is None


# ---------------------------------------------------------------------------
# _cosine_similarity
# ---------------------------------------------------------------------------


def test_cosine_similarity_identical() -> None:
    v = [1.0, 2.0, 3.0]
    assert _cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal() -> None:
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert _cosine_similarity(a, b) == pytest.approx(0.0)


def test_cosine_similarity_opposite() -> None:
    a = [1.0, 0.0]
    b = [-1.0, 0.0]
    assert _cosine_similarity(a, b) == pytest.approx(-1.0)


def test_cosine_similarity_zero_vector() -> None:
    # zero vector → norm clamped to 1.0 to avoid division by zero
    a = [0.0, 0.0]
    b = [1.0, 0.0]
    result = _cosine_similarity(a, b)
    assert math.isfinite(result)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entry(
    *,
    knowledge_base_name: str = "kb1",
    provider: str = "openai",
    model: str = "text-embedding-3-small",
    dimensions: int = 3,
    embedding: list[float] | None = None,
    expires_at: datetime | None = None,
    hit_count: int = 0,
    workspace_id: uuid.UUID | None = None,
) -> MagicMock:
    entry = MagicMock()
    entry.id = uuid.uuid4()
    entry.knowledge_base_name = knowledge_base_name
    entry.provider = provider
    entry.model = model
    entry.dimensions = dimensions
    entry.embedding = embedding if embedding is not None else [1.0, 0.0, 0.0]
    entry.expires_at = expires_at
    entry.hit_count = hit_count
    entry.workspace_id = workspace_id
    entry.query_text = "test query"
    entry.answer_text = "cached answer"
    entry.citations_json = []
    return entry


def _make_session(entries: list) -> MagicMock:
    session = MagicMock()
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = entries
    session.execute.return_value = execute_result
    return session


# ---------------------------------------------------------------------------
# lookup_cache
# ---------------------------------------------------------------------------


def test_lookup_cache_hit() -> None:
    entry = _make_entry(embedding=[1.0, 0.0, 0.0])
    session = _make_session([entry])
    cfg = SemanticCacheConfig(similarity_threshold=0.9)

    result = lookup_cache(
        session,
        query_vector=[1.0, 0.0, 0.0],
        knowledge_base_name="kb1",
        provider="openai",
        model="text-embedding-3-small",
        dimensions=3,
        config=cfg,
    )

    assert result is not None
    assert isinstance(result, CacheHit)
    assert result.similarity == pytest.approx(1.0, abs=1e-5)
    assert result.answer_text == "cached answer"


def test_lookup_cache_miss_below_threshold() -> None:
    # orthogonal vector → similarity 0.0
    entry = _make_entry(embedding=[1.0, 0.0, 0.0])
    session = _make_session([entry])
    cfg = SemanticCacheConfig(similarity_threshold=0.9)

    result = lookup_cache(
        session,
        query_vector=[0.0, 1.0, 0.0],
        knowledge_base_name="kb1",
        provider="openai",
        model="text-embedding-3-small",
        dimensions=3,
        config=cfg,
    )

    assert result is None


def test_lookup_cache_expired_entry_skipped() -> None:
    past = datetime.now(timezone.utc) - timedelta(seconds=10)
    entry = _make_entry(embedding=[1.0, 0.0, 0.0], expires_at=past)
    session = _make_session([entry])
    cfg = SemanticCacheConfig(similarity_threshold=0.5)

    result = lookup_cache(
        session,
        query_vector=[1.0, 0.0, 0.0],
        knowledge_base_name="kb1",
        provider="openai",
        model="text-embedding-3-small",
        dimensions=3,
        config=cfg,
    )

    assert result is None


def test_lookup_cache_non_expired_entry_returned() -> None:
    future = datetime.now(timezone.utc) + timedelta(seconds=3600)
    entry = _make_entry(embedding=[1.0, 0.0, 0.0], expires_at=future)
    session = _make_session([entry])
    cfg = SemanticCacheConfig(similarity_threshold=0.9)

    result = lookup_cache(
        session,
        query_vector=[1.0, 0.0, 0.0],
        knowledge_base_name="kb1",
        provider="openai",
        model="text-embedding-3-small",
        dimensions=3,
        config=cfg,
    )

    assert result is not None


def test_lookup_cache_no_embedding_skipped() -> None:
    entry = _make_entry()
    entry.embedding = None
    session = _make_session([entry])
    cfg = SemanticCacheConfig(similarity_threshold=0.5)

    result = lookup_cache(
        session,
        query_vector=[1.0, 0.0, 0.0],
        knowledge_base_name="kb1",
        provider="openai",
        model="text-embedding-3-small",
        dimensions=3,
        config=cfg,
    )

    assert result is None


def test_lookup_cache_returns_best_match() -> None:
    e1 = _make_entry(embedding=[1.0, 0.0, 0.0])
    e1.answer_text = "answer 1"
    e2 = _make_entry(embedding=[0.9, 0.436, 0.0])  # closer to [1,0,0] than e1? no, e1 is identical
    e2.answer_text = "answer 2"
    session = _make_session([e1, e2])
    cfg = SemanticCacheConfig(similarity_threshold=0.5)

    result = lookup_cache(
        session,
        query_vector=[1.0, 0.0, 0.0],
        knowledge_base_name="kb1",
        provider="openai",
        model="text-embedding-3-small",
        dimensions=3,
        config=cfg,
    )

    assert result is not None
    assert result.answer_text == "answer 1"  # identical vector wins


def test_lookup_cache_db_error_returns_none() -> None:
    session = MagicMock()
    session.execute.side_effect = RuntimeError("db down")
    cfg = SemanticCacheConfig()

    result = lookup_cache(
        session,
        query_vector=[1.0, 0.0, 0.0],
        knowledge_base_name="kb1",
        provider="openai",
        model="text-embedding-3-small",
        dimensions=3,
        config=cfg,
    )

    assert result is None


def test_lookup_cache_empty_table_returns_none() -> None:
    session = _make_session([])
    cfg = SemanticCacheConfig()

    result = lookup_cache(
        session,
        query_vector=[1.0, 0.0, 0.0],
        knowledge_base_name="kb1",
        provider="openai",
        model="text-embedding-3-small",
        dimensions=3,
        config=cfg,
    )

    assert result is None


# ---------------------------------------------------------------------------
# increment_hit_count
# ---------------------------------------------------------------------------


def test_increment_hit_count_success() -> None:
    entry = MagicMock()
    entry.hit_count = 3
    session = MagicMock()
    session.get.return_value = entry
    entry_id = uuid.uuid4()

    increment_hit_count(session, entry_id)

    assert entry.hit_count == 4
    session.flush.assert_called_once()


def test_increment_hit_count_entry_missing() -> None:
    session = MagicMock()
    session.get.return_value = None

    # Must not raise
    increment_hit_count(session, uuid.uuid4())


def test_increment_hit_count_db_error_swallowed() -> None:
    session = MagicMock()
    session.get.side_effect = RuntimeError("db error")

    # Must not raise
    increment_hit_count(session, uuid.uuid4())


# ---------------------------------------------------------------------------
# store_cache
# ---------------------------------------------------------------------------


def _make_store_session(existing_entries: list | None = None) -> MagicMock:
    entries = existing_entries or []
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = entries
    session.execute.return_value = result
    return session


def test_store_cache_adds_entry() -> None:
    session = _make_store_session()
    cfg = SemanticCacheConfig(max_entries_per_kb=10)

    store_cache(
        session,
        knowledge_base_name="kb1",
        query_text="what is RAG?",
        query_vector=[1.0, 0.0, 0.0],
        provider="openai",
        model="text-embedding-3-small",
        dimensions=3,
        answer_text="RAG is retrieval-augmented generation.",
        citations_json=[],
        config=cfg,
    )

    session.add.assert_called_once()
    session.flush.assert_called()


def test_store_cache_evicts_oldest_when_at_capacity() -> None:
    # Fill to max capacity
    now = datetime.now(timezone.utc)
    entries = []
    for i in range(3):
        e = MagicMock()
        e.created_at = now - timedelta(seconds=100 - i)
        entries.append(e)

    session = _make_store_session(entries)
    cfg = SemanticCacheConfig(max_entries_per_kb=3)

    store_cache(
        session,
        knowledge_base_name="kb1",
        query_text="new query",
        query_vector=[1.0, 0.0, 0.0],
        provider="openai",
        model="text-embedding-3-small",
        dimensions=3,
        answer_text="answer",
        citations_json=[],
        config=cfg,
    )

    # One oldest entry should be deleted
    session.delete.assert_called_once_with(entries[0])


def test_store_cache_no_eviction_below_capacity() -> None:
    session = _make_store_session([MagicMock()])
    cfg = SemanticCacheConfig(max_entries_per_kb=10)

    store_cache(
        session,
        knowledge_base_name="kb1",
        query_text="query",
        query_vector=[1.0, 0.0],
        provider="openai",
        model="text-embedding-3-small",
        dimensions=2,
        answer_text="answer",
        citations_json=[],
        config=cfg,
    )

    session.delete.assert_not_called()


def test_store_cache_db_error_swallowed() -> None:
    session = MagicMock()
    session.execute.side_effect = RuntimeError("db down")
    cfg = SemanticCacheConfig()

    # Must not raise
    store_cache(
        session,
        knowledge_base_name="kb1",
        query_text="query",
        query_vector=[1.0, 0.0],
        provider="openai",
        model="text-embedding-3-small",
        dimensions=2,
        answer_text="answer",
        citations_json=[],
        config=cfg,
    )


# ---------------------------------------------------------------------------
# invalidate_cache
# ---------------------------------------------------------------------------


def test_invalidate_cache_deletes_all_entries() -> None:
    entries = [MagicMock(), MagicMock(), MagicMock()]
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = entries
    session.execute.return_value = result

    count = invalidate_cache(session, knowledge_base_name="kb1")

    assert count == 3
    assert session.delete.call_count == 3


def test_invalidate_cache_returns_zero_when_empty() -> None:
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result

    count = invalidate_cache(session, knowledge_base_name="kb1")

    assert count == 0


def test_invalidate_cache_filters_by_workspace() -> None:
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = []
    session.execute.return_value = result
    wid = uuid.uuid4()

    invalidate_cache(session, knowledge_base_name="kb1", workspace_id=wid)

    # Verify a WHERE clause was built (execute was called)
    session.execute.assert_called_once()
