"""Unit tests for faithfulness / hallucination detection."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ragrig.answer.faithfulness import (
    FaithfulnessConfig,
    FaithfulnessResult,
    _parse_response,
    check_faithfulness,
)

pytestmark = pytest.mark.unit


# ── FaithfulnessConfig validation ─────────────────────────────────────────────


def test_config_default_threshold() -> None:
    config = FaithfulnessConfig(provider_name="model.openai")
    assert config.threshold == 0.6


def test_config_threshold_zero_rejected() -> None:
    with pytest.raises(ValueError, match="threshold must be in"):
        FaithfulnessConfig(provider_name="model.openai", threshold=0.0)


def test_config_threshold_above_one_rejected() -> None:
    with pytest.raises(ValueError, match="threshold must be in"):
        FaithfulnessConfig(provider_name="model.openai", threshold=1.1)


def test_config_threshold_one_valid() -> None:
    config = FaithfulnessConfig(provider_name="model.openai", threshold=1.0)
    assert config.threshold == 1.0


# ── _parse_response ───────────────────────────────────────────────────────────


def test_parse_score_and_reason() -> None:
    response = "SCORE: 4\nREASON: The answer is mostly supported by the passages."
    score, reason = _parse_response(response)
    assert score == 4
    assert reason == "The answer is mostly supported by the passages."


def test_parse_score_5() -> None:
    response = "SCORE: 5\nREASON: Fully supported."
    score, reason = _parse_response(response)
    assert score == 5


def test_parse_score_1_no_reason() -> None:
    response = "SCORE: 1"
    score, reason = _parse_response(response)
    assert score == 1
    assert reason is None


def test_parse_invalid_returns_zero() -> None:
    response = "I cannot determine faithfulness."
    score, reason = _parse_response(response)
    assert score == 0
    assert reason is None


def test_parse_case_insensitive() -> None:
    response = "score: 3\nreason: Partially supported."
    score, reason = _parse_response(response)
    assert score == 3


def test_parse_score_out_of_range_not_matched() -> None:
    response = "SCORE: 6\nREASON: Invalid."
    score, _ = _parse_response(response)
    assert score == 0


# ── check_faithfulness ────────────────────────────────────────────────────────


def test_check_returns_none_when_no_provider() -> None:
    config = FaithfulnessConfig(provider_name="model.openai")
    result = check_faithfulness(
        query="What is RAG?",
        answer="RAG is retrieval-augmented generation.",
        context_passages=["RAG stands for retrieval-augmented generation."],
        config=config,
        provider=None,
    )
    assert result is None


def test_check_returns_none_for_empty_answer() -> None:
    config = FaithfulnessConfig(provider_name="model.openai")
    provider = MagicMock()
    result = check_faithfulness(
        query="What is RAG?",
        answer="   ",
        context_passages=["Some passage."],
        config=config,
        provider=provider,
    )
    assert result is None
    provider.generate.assert_not_called()


def test_check_returns_none_for_empty_context() -> None:
    config = FaithfulnessConfig(provider_name="model.openai")
    provider = MagicMock()
    result = check_faithfulness(
        query="What is RAG?",
        answer="Some answer.",
        context_passages=[],
        config=config,
        provider=provider,
    )
    assert result is None
    provider.generate.assert_not_called()


def test_check_faithful_score_5() -> None:
    config = FaithfulnessConfig(provider_name="model.openai", threshold=0.6)
    provider = MagicMock()
    provider.generate.return_value = "SCORE: 5\nREASON: Fully supported."
    result = check_faithfulness(
        query="What is RAG?",
        answer="RAG is retrieval-augmented generation.",
        context_passages=["RAG stands for retrieval-augmented generation."],
        config=config,
        provider=provider,
    )
    assert isinstance(result, FaithfulnessResult)
    assert result.raw_score == 5
    assert result.score == 1.0
    assert result.is_faithful is True
    assert result.reason == "Fully supported."


def test_check_unfaithful_score_1() -> None:
    config = FaithfulnessConfig(provider_name="model.openai", threshold=0.6)
    provider = MagicMock()
    provider.generate.return_value = "SCORE: 1\nREASON: Hallucinated content."
    result = check_faithfulness(
        query="What is X?",
        answer="X is something not in the passages.",
        context_passages=["Passage about Y."],
        config=config,
        provider=provider,
    )
    assert result is not None
    assert result.raw_score == 1
    assert result.score == 0.0
    assert result.is_faithful is False


def test_check_score_3_below_default_threshold() -> None:
    config = FaithfulnessConfig(provider_name="model.openai", threshold=0.6)
    provider = MagicMock()
    provider.generate.return_value = "SCORE: 3\nREASON: Partially supported."
    result = check_faithfulness(
        query="Q?",
        answer="A.",
        context_passages=["Passage."],
        config=config,
        provider=provider,
    )
    assert result is not None
    # score = (3-1)/4 = 0.5 < 0.6 threshold → not faithful
    assert result.score == 0.5
    assert result.is_faithful is False


def test_check_score_4_above_default_threshold() -> None:
    config = FaithfulnessConfig(provider_name="model.openai", threshold=0.6)
    provider = MagicMock()
    provider.generate.return_value = "SCORE: 4\nREASON: Mostly supported."
    result = check_faithfulness(
        query="Q?",
        answer="A.",
        context_passages=["Passage."],
        config=config,
        provider=provider,
    )
    assert result is not None
    # score = (4-1)/4 = 0.75 > 0.6 → faithful
    assert result.score == 0.75
    assert result.is_faithful is True


def test_check_returns_none_on_provider_error() -> None:
    config = FaithfulnessConfig(provider_name="model.openai")
    provider = MagicMock()
    provider.generate.side_effect = RuntimeError("LLM down")
    result = check_faithfulness(
        query="Q?",
        answer="A.",
        context_passages=["Passage."],
        config=config,
        provider=provider,
    )
    assert result is None


def test_check_returns_none_when_parse_fails() -> None:
    config = FaithfulnessConfig(provider_name="model.openai")
    provider = MagicMock()
    provider.generate.return_value = "I cannot determine this."
    result = check_faithfulness(
        query="Q?",
        answer="A.",
        context_passages=["Passage."],
        config=config,
        provider=provider,
    )
    assert result is None


def test_check_truncates_context_to_max_chars() -> None:
    config = FaithfulnessConfig(provider_name="model.openai", max_context_chars=50)
    provider = MagicMock()
    provider.generate.return_value = "SCORE: 5\nREASON: OK."
    check_faithfulness(
        query="Q?",
        answer="A.",
        context_passages=["A" * 200, "B" * 200],
        config=config,
        provider=provider,
    )
    prompt = provider.generate.call_args[0][0]
    # Only the first passage (truncated) should appear in the prompt
    assert "B" * 10 not in prompt


# ── AnswerReport faithfulness fields ─────────────────────────────────────────


def test_answer_report_faithfulness_defaults_to_none() -> None:
    from ragrig.answer.schema import AnswerReport

    report = AnswerReport(
        answer="answer",
        citations=[],
        evidence_chunks=[],
        model="m",
        provider="p",
        retrieval_trace={},
        grounding_status="grounded",
    )
    assert report.faithfulness_score is None
    assert report.faithfulness_reason is None


def test_answer_report_stores_faithfulness_fields() -> None:
    from ragrig.answer.schema import AnswerReport

    report = AnswerReport(
        answer="answer",
        citations=[],
        evidence_chunks=[],
        model="m",
        provider="p",
        retrieval_trace={},
        grounding_status="grounded",
        faithfulness_score=0.75,
        faithfulness_reason="Mostly supported.",
    )
    assert report.faithfulness_score == 0.75
    assert report.faithfulness_reason == "Mostly supported."
