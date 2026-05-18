"""Tests for evaluation.answer_judge module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ragrig.evaluation.answer_judge import (
    _parse_judge_response,
    score_answer_correctness,
    score_answer_relevance,
    score_context_precision,
    score_context_recall,
)

# ---------------------------------------------------------------------------
# _parse_judge_response
# ---------------------------------------------------------------------------


def test_parse_valid_response() -> None:
    raw = "SCORE: 4\nREASON: The answer covers most key points."
    score, reason = _parse_judge_response(raw)
    assert score == 4
    assert reason == "The answer covers most key points."


def test_parse_score_only() -> None:
    score, reason = _parse_judge_response("SCORE: 2")
    assert score == 2
    assert reason is None


def test_parse_missing_score_returns_zero() -> None:
    score, reason = _parse_judge_response("No score here.")
    assert score == 0
    assert reason is None


def test_parse_score_case_insensitive() -> None:
    score, _ = _parse_judge_response("score: 5")
    assert score == 5


# ---------------------------------------------------------------------------
# score_answer_correctness
# ---------------------------------------------------------------------------


def _make_provider(response: str) -> MagicMock:
    p = MagicMock()
    p.complete.return_value = response
    return p


def test_score_answer_correctness_high() -> None:
    provider = _make_provider("SCORE: 5\nREASON: Perfect match.")
    result = score_answer_correctness(
        query="What is X?",
        generated_answer="X is Y.",
        expected_answer="X is Y.",
        provider=provider,
    )
    assert result is not None
    score, reason = result
    assert score == pytest.approx(1.0)
    assert reason == "Perfect match."


def test_score_answer_correctness_low() -> None:
    provider = _make_provider("SCORE: 1\nREASON: Completely wrong.")
    result = score_answer_correctness(
        query="What is X?",
        generated_answer="X is Z.",
        expected_answer="X is Y.",
        provider=provider,
    )
    assert result is not None
    score, _ = result
    assert score == pytest.approx(0.0)


def test_score_answer_correctness_mid() -> None:
    provider = _make_provider("SCORE: 3\nREASON: Partially correct.")
    result = score_answer_correctness(
        query="What is X?",
        generated_answer="X is somewhat Y.",
        expected_answer="X is Y.",
        provider=provider,
    )
    assert result is not None
    score, _ = result
    assert score == pytest.approx(0.5)


def test_score_answer_correctness_provider_error_returns_none() -> None:
    provider = MagicMock()
    provider.complete.side_effect = RuntimeError("API down")
    result = score_answer_correctness(
        query="q",
        generated_answer="a",
        expected_answer="e",
        provider=provider,
    )
    assert result is None


def test_score_answer_correctness_unparseable_returns_none() -> None:
    provider = _make_provider("I cannot score this.")
    result = score_answer_correctness(
        query="q",
        generated_answer="a",
        expected_answer="e",
        provider=provider,
    )
    assert result is None


# ---------------------------------------------------------------------------
# score_answer_relevance
# ---------------------------------------------------------------------------


def test_score_answer_relevance_high() -> None:
    provider = _make_provider("SCORE: 5\nREASON: Directly answers the question.")
    result = score_answer_relevance(
        query="What is X?",
        generated_answer="X is a widget used for Y.",
        provider=provider,
    )
    assert result is not None
    score, _ = result
    assert score == pytest.approx(1.0)


def test_score_answer_relevance_provider_error_returns_none() -> None:
    provider = MagicMock()
    provider.complete.side_effect = RuntimeError("timeout")
    result = score_answer_relevance(
        query="q",
        generated_answer="a",
        provider=provider,
    )
    assert result is None


# ---------------------------------------------------------------------------
# score_context_precision
# ---------------------------------------------------------------------------


def test_context_precision_all_relevant() -> None:
    texts = ["The cat sat on the mat.", "RAGRig is a framework."]
    citations = ["cat sat on the mat", "RAGRig is a framework"]
    assert score_context_precision(retrieved_texts=texts, expected_citations=citations) == 1.0


def test_context_precision_none_relevant() -> None:
    texts = ["unrelated content here"]
    citations = ["something completely different"]
    assert score_context_precision(retrieved_texts=texts, expected_citations=citations) == 0.0


def test_context_precision_partial() -> None:
    texts = ["relevant content here", "unrelated stuff"]
    citations = ["relevant content here"]
    # 1 of 2 chunks is relevant
    assert score_context_precision(retrieved_texts=texts, expected_citations=citations) == 0.5


def test_context_precision_empty_texts_returns_zero() -> None:
    assert score_context_precision(retrieved_texts=[], expected_citations=["x"]) == 0.0


def test_context_precision_empty_citations_returns_zero() -> None:
    assert score_context_precision(retrieved_texts=["text"], expected_citations=[]) == 0.0


def test_context_precision_case_insensitive() -> None:
    texts = ["The CAT sat on the mat."]
    citations = ["cat sat on the mat"]
    assert score_context_precision(retrieved_texts=texts, expected_citations=citations) == 1.0


# ---------------------------------------------------------------------------
# score_context_recall
# ---------------------------------------------------------------------------


def test_context_recall_all_found() -> None:
    texts = ["RAGRig supports pgvector and Qdrant backends."]
    citations = ["pgvector", "Qdrant"]
    assert score_context_recall(retrieved_texts=texts, expected_citations=citations) == 1.0


def test_context_recall_none_found() -> None:
    texts = ["completely unrelated"]
    citations = ["pgvector", "Qdrant"]
    assert score_context_recall(retrieved_texts=texts, expected_citations=citations) == 0.0


def test_context_recall_partial() -> None:
    texts = ["pgvector is supported."]
    citations = ["pgvector", "Qdrant"]
    assert score_context_recall(retrieved_texts=texts, expected_citations=citations) == 0.5


def test_context_recall_empty_citations_returns_zero() -> None:
    assert score_context_recall(retrieved_texts=["text"], expected_citations=[]) == 0.0


def test_context_recall_empty_texts_returns_zero() -> None:
    assert score_context_recall(retrieved_texts=[], expected_citations=["x"]) == 0.0


def test_context_recall_case_insensitive() -> None:
    texts = ["PGVECTOR is awesome."]
    citations = ["pgvector"]
    assert score_context_recall(retrieved_texts=texts, expected_citations=citations) == 1.0
