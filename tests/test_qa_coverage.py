"""QA coverage supplement: edge-case branches in lexical.py and reranker.py.

WARNING: These tests exercise implementation-internal code paths to push
line/branch coverage to 100% for the hybrid retrieval + reranking modules.
They are intentionally coupled to the current implementation and should be
updated if the implementation changes.
"""

from __future__ import annotations

import uuid as _uuid

import pytest

# ── lexical.py edge cases ──────────────────────────────────────────────────


def test_token_overlap_score_empty_query_tokens() -> None:
    """token_overlap_score returns 0 when query produces no tokens."""
    from ragrig.lexical import token_overlap_score

    assert token_overlap_score("some text", "...", ["corpus"]) == 0.0


def test_token_overlap_score_empty_chunk_tokens() -> None:
    """token_overlap_score returns 0 when chunk produces no tokens."""
    from ragrig.lexical import token_overlap_score

    assert token_overlap_score("...", "query", ["corpus"]) == 0.0


def test_token_overlap_score_empty_corpus_fallback() -> None:
    """token_overlap_score with empty corpus_texts uses pure overlap ratio."""
    from ragrig.lexical import token_overlap_score

    score = token_overlap_score("hello world", "hello", [])
    # 1 token overlap / 1 query token = 1.0
    assert score == 1.0


def test_token_overlap_score_empty_corpus_no_match() -> None:
    """Empty corpus fallback: no token overlap gives 0."""
    from ragrig.lexical import token_overlap_score

    score = token_overlap_score("foo bar", "baz", [])
    assert score == 0.0


def test_bm25_score_tokens_empty_corpus() -> None:
    """BM25 with empty corpus still returns 0 (all IDF = 0)."""
    from ragrig.lexical import bm25_score_tokens

    score = bm25_score_tokens(["hello"], ["hello"], [])
    assert score == 0.0


def test_bm25_score_tokens_empty_query() -> None:
    """BM25 returns 0 when query tokens are empty."""
    from ragrig.lexical import bm25_score_tokens

    score = bm25_score_tokens(["hello"], [], [["hello"]])
    assert score == 0.0


def test_bm25_score_tokens_empty_chunk() -> None:
    """BM25 returns 0 when chunk tokens are empty."""
    from ragrig.lexical import bm25_score_tokens

    score = bm25_score_tokens([], ["hello"], [["hello"]])
    assert score == 0.0


def test_compute_tf_empty_tokens() -> None:
    """_compute_tf returns empty dict for empty token list."""
    from ragrig.lexical import _compute_tf

    assert _compute_tf([]) == {}


def test_compute_idf_empty_corpus() -> None:
    """_compute_idf returns zero IDF for all terms when corpus is empty."""
    from ragrig.lexical import _compute_idf

    result = _compute_idf([], {"hello", "world"})
    assert result == {"hello": 0.0, "world": 0.0}


# ── reranker.py edge cases ────────────────────────────────────────────────


def test_fake_rerank_empty_query_tokens() -> None:
    """fake_rerank with empty query preserves original order and scores."""
    from ragrig.reranker import RerankCandidate, fake_rerank

    candidates = [
        RerankCandidate(
            document_id=_uuid.uuid4(),
            document_version_id=_uuid.uuid4(),
            chunk_id=_uuid.uuid4(),
            chunk_index=0,
            document_uri="test.txt",
            source_uri=None,
            text="hello world",
            text_preview="hello world",
            original_score=0.8,
            original_index=i,
            chunk_metadata={},
        )
        for i in range(3)
    ]

    results = fake_rerank("...", candidates)
    assert len(results) == 3
    for i, r in enumerate(results):
        assert r.new_rank == i
        assert r.candidate.original_index == i
        assert r.rerank_score == r.candidate.original_score


def test_provider_rerank_success_path(monkeypatch) -> None:
    """provider_rerank returns results when provider succeeds."""
    from ragrig.reranker import RerankCandidate, provider_rerank

    candidates = [
        RerankCandidate(
            document_id=_uuid.uuid4(),
            document_version_id=_uuid.uuid4(),
            chunk_id=_uuid.uuid4(),
            chunk_index=0,
            document_uri="a.txt",
            source_uri=None,
            text="first document",
            text_preview="first document",
            original_score=0.5,
            original_index=0,
            chunk_metadata={},
        ),
        RerankCandidate(
            document_id=_uuid.uuid4(),
            document_version_id=_uuid.uuid4(),
            chunk_id=_uuid.uuid4(),
            chunk_index=0,
            document_uri="b.txt",
            source_uri=None,
            text="second document",
            text_preview="second document",
            original_score=0.9,
            original_index=1,
            chunk_metadata={},
        ),
    ]

    class FakeRerankerProvider:
        """Fake provider that returns deterministic scores."""

        def rerank(self, query: str, documents: list[str]) -> list[dict]:
            return [
                {"document": doc, "index": i, "score": 1.0 if "second" in doc else 0.5}
                for i, doc in enumerate(documents)
            ]

    class FakeRegistry:
        def get(self, name, **config):
            return FakeRerankerProvider()

    monkeypatch.setattr("ragrig.providers._provider_registry", FakeRegistry(), raising=False)
    monkeypatch.setattr("ragrig.providers.get_provider_registry", lambda: FakeRegistry())

    results = provider_rerank("test query", candidates, provider_name="fake.reranker")
    assert results is not None
    assert len(results) == 2
    # "second document" should rank first (score 1.0)
    assert results[0].rerank_score == 1.0
    assert "second" in results[0].candidate.text


def test_provider_rerank_scores_out_of_bounds() -> None:
    """provider_rerank with out-of-bounds index is skipped safely."""
    from ragrig.reranker import RerankCandidate, provider_rerank

    candidates = [
        RerankCandidate(
            document_id=_uuid.uuid4(),
            document_version_id=_uuid.uuid4(),
            chunk_id=_uuid.uuid4(),
            chunk_index=0,
            document_uri="test.txt",
            source_uri=None,
            text="valid doc",
            text_preview="valid doc",
            original_score=0.5,
            original_index=0,
            chunk_metadata={},
        )
    ]

    class FakeRerankerProvider:
        def rerank(self, query: str, documents: list[str]) -> list[dict]:
            return [
                {"document": "valid doc", "index": 0, "score": 0.8},
                {"document": "bogus", "index": 999, "score": 0.9},
            ]

    import ragrig.providers as provs

    mp = pytest.MonkeyPatch()
    mp.setattr(provs, "_provider_registry", None, raising=False)
    mp.setattr(
        provs,
        "get_provider_registry",
        lambda: type("FakeReg", (), {"get": lambda s, n, **c: FakeRerankerProvider()})(),
    )
    try:
        results = provider_rerank("test", candidates, provider_name="fake")
        assert results is not None
        assert len(results) == 1
        assert results[0].candidate.text == "valid doc"
    finally:
        mp.undo()


def test_provider_rerank_empty_results_returns_none(monkeypatch) -> None:
    """provider_rerank returns None when scored results come back empty."""
    from ragrig.reranker import RerankCandidate, provider_rerank

    candidates = [
        RerankCandidate(
            document_id=_uuid.uuid4(),
            document_version_id=_uuid.uuid4(),
            chunk_id=_uuid.uuid4(),
            chunk_index=0,
            document_uri="test.txt",
            source_uri=None,
            text="test",
            text_preview="test",
            original_score=0.5,
            original_index=0,
            chunk_metadata={},
        )
    ]

    class FakeEmptyProvider:
        def rerank(self, query: str, documents: list[str]) -> list[dict]:
            # Returns out-of-bounds indices → results list empty
            return [{"document": "x", "index": 999, "score": 0.9}]

    monkeypatch.setattr("ragrig.providers._provider_registry", None, raising=False)
    monkeypatch.setattr(
        "ragrig.providers.get_provider_registry",
        lambda: type("FakeReg", (), {"get": lambda s, n, **c: FakeEmptyProvider()})(),
    )

    results = provider_rerank("test", candidates, provider_name="fake")
    assert results is None


def test_provider_rerank_reranker_bge_lookup(monkeypatch) -> None:
    """provider_rerank uses 'reranker.bge' when provider_name is None."""
    from ragrig.reranker import RerankCandidate, provider_rerank

    candidates = [
        RerankCandidate(
            document_id=_uuid.uuid4(),
            document_version_id=_uuid.uuid4(),
            chunk_id=_uuid.uuid4(),
            chunk_index=0,
            document_uri="test.txt",
            source_uri=None,
            text="test",
            text_preview="test",
            original_score=0.5,
            original_index=0,
            chunk_metadata={},
        )
    ]

    called_name: list[str] = []

    class FakeProvider:
        def rerank(self, query, docs):
            return [{"document": d, "index": i, "score": 0.8} for i, d in enumerate(docs)]

    class FakeRegistry:
        def get(self, name, **config):
            called_name.append(name)
            return FakeProvider()

    monkeypatch.setattr("ragrig.providers._provider_registry", None, raising=False)
    monkeypatch.setattr("ragrig.providers.get_provider_registry", lambda: FakeRegistry())

    results = provider_rerank("test", candidates, provider_name=None)
    assert results is not None
    assert len(results) == 1
    assert called_name == ["reranker.bge"]


def test_provider_rerank_provider_error_during_rerank(monkeypatch) -> None:
    """provider_rerank returns None when provider.rerank raises ProviderError."""
    from ragrig.providers import ProviderError
    from ragrig.reranker import RerankCandidate, provider_rerank

    candidates = [
        RerankCandidate(
            document_id=_uuid.uuid4(),
            document_version_id=_uuid.uuid4(),
            chunk_id=_uuid.uuid4(),
            chunk_index=0,
            document_uri="test.txt",
            source_uri=None,
            text="test",
            text_preview="test",
            original_score=0.5,
            original_index=0,
            chunk_metadata={},
        )
    ]

    class FailingProvider:
        def rerank(self, query, docs):
            raise ProviderError("bang", code="test", retryable=False)

    monkeypatch.setattr("ragrig.providers._provider_registry", None, raising=False)
    monkeypatch.setattr(
        "ragrig.providers.get_provider_registry",
        lambda: type("FakeReg", (), {"get": lambda s, n, **c: FailingProvider()})(),
    )

    results = provider_rerank("test", candidates, provider_name="failing")
    assert results is None


def test_fake_rerank_empty_candidates() -> None:
    """fake_rerank with empty candidate list returns empty list."""
    from ragrig.reranker import fake_rerank

    results = fake_rerank("query", [])
    assert results == []


def test_fake_rerank_all_candidates_matched_equally() -> None:
    """fake_rerank with all candidates matching equally preserves original order."""
    from ragrig.reranker import RerankCandidate, fake_rerank

    candidates = [
        RerankCandidate(
            document_id=_uuid.uuid4(),
            document_version_id=_uuid.uuid4(),
            chunk_id=_uuid.uuid4(),
            chunk_index=0,
            document_uri=f"doc_{i}.txt",
            source_uri=None,
            text="exact match text",
            text_preview="exact match text",
            original_score=1.0,
            original_index=i,
            chunk_metadata={},
        )
        for i in range(3)
    ]

    results = fake_rerank("exact match text", candidates)
    assert len(results) == 3
    # All have same match ratio, sorted by original_index
    assert [r.candidate.original_index for r in results] == [0, 1, 2]
    assert all(r.rerank_score == 1.0 for r in results)


def test_provider_rerank_with_model_name(monkeypatch) -> None:
    """provider_rerank passes model_name through to provider config."""
    from ragrig.reranker import RerankCandidate, provider_rerank

    candidates = [
        RerankCandidate(
            document_id=_uuid.uuid4(),
            document_version_id=_uuid.uuid4(),
            chunk_id=_uuid.uuid4(),
            chunk_index=0,
            document_uri="test.txt",
            source_uri=None,
            text="test",
            text_preview="test",
            original_score=0.5,
            original_index=0,
            chunk_metadata={},
        )
    ]

    received_config: list[dict] = []

    class FakeProvider:
        def rerank(self, query, docs):
            return [{"document": d, "index": i, "score": 0.8} for i, d in enumerate(docs)]

    class FakeRegistry:
        def get(self, name, **config):
            received_config.append(config)
            return FakeProvider()

    monkeypatch.setattr("ragrig.providers._provider_registry", None, raising=False)
    monkeypatch.setattr("ragrig.providers.get_provider_registry", lambda: FakeRegistry())

    results = provider_rerank(
        "test",
        candidates,
        provider_name="custom.reranker",
        model_name="BAAI/bge-reranker-base",
    )
    assert results is not None
    assert len(results) == 1
    assert received_config == [
        {"provider": "custom.reranker", "model_name": "BAAI/bge-reranker-base"}
    ]
