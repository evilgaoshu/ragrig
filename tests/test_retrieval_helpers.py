"""Unit tests for retrieval.py helper functions.

Covers edge-case paths in private helpers that are not exercised by the
integration-level test_retrieval.py (which requires full ingest+index setup).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import patch

import pytest

from ragrig.db.models import (
    Chunk,
    Document,
    DocumentSummary,
    DocumentVersion,
    Embedding,
    KnowledgeBase,
    Source,
    Workspace,
)
from ragrig.reranker import RerankCandidate, RerankResult
from ragrig.retrieval import (
    RetrievalResult,
    _apply_hybrid_fusion,
    _apply_rerank,
    _apply_time_decay,
    _fetch_all_texts,
    _hydrate_parent_text,
    _search_document_summaries,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(**kwargs) -> RetrievalResult:
    defaults = dict(
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        chunk_index=0,
        document_uri="test://doc",
        source_uri=None,
        text="hello world",
        text_preview="hello world",
        distance=0.1,
        score=0.9,
        chunk_metadata={},
        rank_stage_trace={"stages": [], "final_source": "vector"},
    )
    defaults.update(kwargs)
    return RetrievalResult(**defaults)


def _seed_kb(session) -> tuple[Workspace, KnowledgeBase, Source]:
    ws = Workspace(
        id=uuid.uuid4(),
        slug=f"ws-{uuid.uuid4().hex[:8]}",
        display_name="Test Workspace",
        status="active",
        metadata_json={},
    )
    session.add(ws)
    session.flush()

    kb = KnowledgeBase(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        name=f"kb-{uuid.uuid4().hex[:8]}",
        doc_weight=0.5,
        metadata_json={},
    )
    session.add(kb)
    session.flush()

    src = Source(
        id=uuid.uuid4(),
        knowledge_base_id=kb.id,
        kind="local",
        uri="file:///test",
        config_json={},
    )
    session.add(src)
    session.flush()

    return ws, kb, src


def _seed_document_version(session, kb: KnowledgeBase, src: Source) -> DocumentVersion:
    doc = Document(
        id=uuid.uuid4(),
        knowledge_base_id=kb.id,
        source_id=src.id,
        uri=f"test://doc-{uuid.uuid4().hex[:6]}",
        content_hash="abc123",
        metadata_json={},
    )
    session.add(doc)
    session.flush()

    dv = DocumentVersion(
        id=uuid.uuid4(),
        document_id=doc.id,
        version_number=1,
        content_hash="abc123",
        parser_name="test",
        parser_config_json={},
        extracted_text="chunk text",
        metadata_json={},
    )
    session.add(dv)
    session.flush()

    return dv


# ---------------------------------------------------------------------------
# _apply_hybrid_fusion
# ---------------------------------------------------------------------------


def test_apply_hybrid_fusion_returns_empty_for_empty_input() -> None:
    result = _apply_hybrid_fusion([], "query", [])
    assert result == []


# ---------------------------------------------------------------------------
# _apply_rerank
# ---------------------------------------------------------------------------


def test_apply_rerank_returns_empty_tuple_for_empty_candidates() -> None:
    results, degraded, reason, trace = _apply_rerank([], "query")
    assert results == []
    assert degraded is False
    assert reason == ""
    assert trace == {}


def test_apply_rerank_provider_returning_results_covers_success_path() -> None:
    cand_id = uuid.uuid4()
    cand = _make_result(chunk_id=cand_id)

    rerank_cand = RerankCandidate(
        document_id=cand.document_id,
        document_version_id=cand.document_version_id,
        chunk_id=cand.chunk_id,
        chunk_index=cand.chunk_index,
        document_uri=cand.document_uri,
        source_uri=cand.source_uri,
        text=cand.text,
        text_preview=cand.text_preview,
        original_score=cand.score,
        original_index=0,
        chunk_metadata=cand.chunk_metadata,
    )
    fake_rr = [RerankResult(candidate=rerank_cand, rerank_score=0.95, new_rank=0)]

    with patch("ragrig.retrieval.provider_rerank", return_value=fake_rr):
        results, degraded, reason, trace = _apply_rerank(
            [cand], "hello world", reranker_provider="test-provider"
        )

    assert len(results) == 1
    assert results[0].score == 0.95
    assert degraded is False
    assert reason == ""
    assert trace["status"] == "applied"
    assert trace["provider"] == "test-provider"
    assert trace["candidate_count"] == 1
    assert trace["after"][0]["rerank_score"] == 0.95


# ---------------------------------------------------------------------------
# _apply_time_decay
# ---------------------------------------------------------------------------


def test_apply_time_decay_td_score_zero_when_created_at_is_none() -> None:
    """When time_decay_weight > 0 but chunk_created_at is None, td_score = 0.0."""
    r = _make_result(chunk_created_at=None)
    out = _apply_time_decay([r], time_decay_weight=0.5, sim_weight=1.0)
    assert len(out) == 1
    # td_score = 0, so final = score * 1.0 + 0 * 0.5
    assert abs(out[0].score - r.score) < 1e-6


def test_apply_time_decay_naive_datetime_gets_utc_attached() -> None:
    """A tz-naive chunk_created_at should be treated as UTC without error."""
    naive_dt = datetime(2024, 1, 1)
    r = _make_result(chunk_created_at=naive_dt)
    out = _apply_time_decay([r], time_decay_weight=0.5, sim_weight=1.0)
    assert len(out) == 1
    # Very old date → large decay → td_score ≈ 0; final_score < original
    assert out[0].score < r.score * 1.0 + 0.5 + 1.0  # sanity: finite


# ---------------------------------------------------------------------------
# _fetch_all_texts
# ---------------------------------------------------------------------------


def test_fetch_all_texts_returns_chunk_texts(sqlite_session) -> None:
    _, kb, src = _seed_kb(sqlite_session)
    dv = _seed_document_version(sqlite_session, kb, src)

    chunk = Chunk(
        id=uuid.uuid4(),
        document_version_id=dv.id,
        chunk_index=0,
        text="chunk text content",
        metadata_json={},
    )
    sqlite_session.add(chunk)
    sqlite_session.flush()

    emb = Embedding(
        id=uuid.uuid4(),
        chunk_id=chunk.id,
        provider="test-provider",
        model="test-model",
        dimensions=4,
        embedding=[0.1, 0.2, 0.3, 0.4],
        metadata_json={},
    )
    sqlite_session.add(emb)
    sqlite_session.flush()

    texts = _fetch_all_texts(
        sqlite_session,
        knowledge_base_id=kb.id,
        provider="test-provider",
        model="test-model",
        dimensions=4,
    )
    assert texts == ["chunk text content"]


def test_fetch_all_texts_returns_empty_when_no_embeddings(sqlite_session) -> None:
    _, kb, _ = _seed_kb(sqlite_session)
    texts = _fetch_all_texts(
        sqlite_session,
        knowledge_base_id=kb.id,
        provider="test-provider",
        model="test-model",
        dimensions=4,
    )
    assert texts == []


# ---------------------------------------------------------------------------
# _search_document_summaries
# ---------------------------------------------------------------------------


def test_search_document_summaries_returns_results_when_rows_exist(sqlite_session) -> None:
    _, kb, src = _seed_kb(sqlite_session)
    dv = _seed_document_version(sqlite_session, kb, src)

    ds = DocumentSummary(
        id=uuid.uuid4(),
        document_version_id=dv.id,
        summary_text="This is a document summary about testing.",
        provider="test-provider",
        model="test-model",
        dimensions=4,
        embedding=[1.0, 0.0, 0.0, 0.0],
        metadata_json={},
    )
    sqlite_session.add(ds)
    sqlite_session.flush()

    query_vector = [1.0, 0.0, 0.0, 0.0]  # identical → distance = 0
    results = _search_document_summaries(
        sqlite_session,
        knowledge_base_id=kb.id,
        provider="test-provider",
        model="test-model",
        dimensions=4,
        query_vector=query_vector,
        top_k=5,
    )
    assert len(results) == 1
    assert results[0].text == "This is a document summary about testing."
    assert results[0].result_source == "document_summary"


def test_search_document_summaries_returns_empty_when_no_rows(sqlite_session) -> None:
    _, kb, _ = _seed_kb(sqlite_session)
    results = _search_document_summaries(
        sqlite_session,
        knowledge_base_id=kb.id,
        provider="test-provider",
        model="test-model",
        dimensions=4,
        query_vector=[1.0, 0.0, 0.0, 0.0],
        top_k=5,
    )
    assert results == []


def test_search_document_summaries_with_workspace_id_filter(sqlite_session) -> None:
    ws, kb, src = _seed_kb(sqlite_session)
    dv = _seed_document_version(sqlite_session, kb, src)

    ds = DocumentSummary(
        id=uuid.uuid4(),
        document_version_id=dv.id,
        workspace_id=ws.id,
        summary_text="Workspace-scoped summary.",
        provider="test-provider",
        model="test-model",
        dimensions=4,
        embedding=[0.0, 1.0, 0.0, 0.0],
        metadata_json={},
    )
    sqlite_session.add(ds)
    sqlite_session.flush()

    results = _search_document_summaries(
        sqlite_session,
        knowledge_base_id=kb.id,
        provider="test-provider",
        model="test-model",
        dimensions=4,
        query_vector=[0.0, 1.0, 0.0, 0.0],
        top_k=5,
        workspace_id=ws.id,
    )
    assert len(results) == 1
    assert results[0].text == "Workspace-scoped summary."


# ---------------------------------------------------------------------------
# _hydrate_parent_text
# ---------------------------------------------------------------------------


def test_hydrate_parent_text_populates_parent_text(sqlite_session) -> None:
    _, kb, src = _seed_kb(sqlite_session)
    dv = _seed_document_version(sqlite_session, kb, src)

    parent_chunk = Chunk(
        id=uuid.uuid4(),
        document_version_id=dv.id,
        chunk_index=0,
        text="full parent text",
        metadata_json={},
    )
    sqlite_session.add(parent_chunk)
    sqlite_session.flush()

    child_chunk = Chunk(
        id=uuid.uuid4(),
        document_version_id=dv.id,
        chunk_index=1,
        text="child excerpt",
        parent_chunk_id=parent_chunk.id,
        metadata_json={},
    )
    sqlite_session.add(child_chunk)
    sqlite_session.flush()

    child_result = _make_result(chunk_id=child_chunk.id)
    hydrated = _hydrate_parent_text([child_result], sqlite_session)

    assert len(hydrated) == 1
    assert hydrated[0].parent_text == "full parent text"


def test_hydrate_parent_text_returns_unchanged_when_no_parents(sqlite_session) -> None:
    _, kb, src = _seed_kb(sqlite_session)
    dv = _seed_document_version(sqlite_session, kb, src)

    chunk = Chunk(
        id=uuid.uuid4(),
        document_version_id=dv.id,
        chunk_index=0,
        text="standalone chunk",
        metadata_json={},
    )
    sqlite_session.add(chunk)
    sqlite_session.flush()

    result = _make_result(chunk_id=chunk.id)
    hydrated = _hydrate_parent_text([result], sqlite_session)
    assert len(hydrated) == 1
    assert hydrated[0].parent_text is None


def test_hydrate_parent_text_returns_unchanged_for_empty_list(sqlite_session) -> None:
    out = _hydrate_parent_text([], sqlite_session)
    assert out == []
