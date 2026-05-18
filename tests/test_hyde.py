"""Unit tests for HyDE (Hypothetical Document Embeddings)."""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest

from ragrig.hyde import HydeConfig, blend_vectors, generate_hypothetical_document

pytestmark = pytest.mark.unit


# ── HydeConfig validation ─────────────────────────────────────────────────────


def test_hyde_config_default_blend_is_one() -> None:
    config = HydeConfig(provider_name="model.openai")
    assert config.blend == 1.0


def test_hyde_config_blend_zero_valid() -> None:
    config = HydeConfig(provider_name="model.openai", blend=0.0)
    assert config.blend == 0.0


def test_hyde_config_blend_half_valid() -> None:
    config = HydeConfig(provider_name="model.openai", blend=0.5)
    assert config.blend == 0.5


def test_hyde_config_blend_above_one_rejected() -> None:
    with pytest.raises(ValueError, match="blend must be in"):
        HydeConfig(provider_name="model.openai", blend=1.1)


def test_hyde_config_blend_below_zero_rejected() -> None:
    with pytest.raises(ValueError, match="blend must be in"):
        HydeConfig(provider_name="model.openai", blend=-0.1)


# ── generate_hypothetical_document ───────────────────────────────────────────


def test_generate_returns_none_when_no_provider() -> None:
    result = generate_hypothetical_document("What is RAG?", None)
    assert result is None


def test_generate_calls_provider_generate() -> None:
    provider = MagicMock()
    provider.generate.return_value = "RAG stands for Retrieval-Augmented Generation."
    result = generate_hypothetical_document("What is RAG?", provider)
    assert result == "RAG stands for Retrieval-Augmented Generation."
    provider.generate.assert_called_once()


def test_generate_prompt_includes_query() -> None:
    provider = MagicMock()
    provider.generate.return_value = "Some passage."
    generate_hypothetical_document("What is chunking?", provider)
    call_args = provider.generate.call_args[0][0]
    assert "What is chunking?" in call_args


def test_generate_returns_none_on_provider_error() -> None:
    provider = MagicMock()
    provider.generate.side_effect = RuntimeError("LLM unavailable")
    result = generate_hypothetical_document("What is RAG?", provider)
    assert result is None


# ── blend_vectors ─────────────────────────────────────────────────────────────


def test_blend_zero_returns_query_vector_unchanged() -> None:
    query = [1.0, 0.0, 0.0]
    hyde = [0.0, 1.0, 0.0]
    result = blend_vectors(query, hyde, 0.0)
    assert result is query


def test_blend_one_returns_hyde_vector_unchanged() -> None:
    query = [1.0, 0.0, 0.0]
    hyde = [0.0, 1.0, 0.0]
    result = blend_vectors(query, hyde, 1.0)
    assert result is hyde


def test_blend_half_is_normalised() -> None:
    query = [1.0, 0.0]
    hyde = [0.0, 1.0]
    result = blend_vectors(query, hyde, 0.5)
    norm = math.sqrt(sum(x * x for x in result))
    assert abs(norm - 1.0) < 1e-9


def test_blend_half_is_midpoint_direction() -> None:
    query = [1.0, 0.0]
    hyde = [0.0, 1.0]
    result = blend_vectors(query, hyde, 0.5)
    # 45-degree direction: both components equal
    assert abs(result[0] - result[1]) < 1e-9


def test_blend_quarter_weight_skews_toward_query() -> None:
    query = [1.0, 0.0]
    hyde = [0.0, 1.0]
    result = blend_vectors(query, hyde, 0.25)
    # 0.75*query + 0.25*hyde → first component dominates
    assert result[0] > result[1]


def test_blend_three_quarter_weight_skews_toward_hyde() -> None:
    query = [1.0, 0.0]
    hyde = [0.0, 1.0]
    result = blend_vectors(query, hyde, 0.75)
    assert result[1] > result[0]


def test_blend_preserves_dimensionality() -> None:
    query = [0.1, 0.2, 0.3, 0.4]
    hyde = [0.4, 0.3, 0.2, 0.1]
    result = blend_vectors(query, hyde, 0.5)
    assert len(result) == 4


def test_blend_zero_vector_does_not_crash() -> None:
    query = [0.0, 0.0, 0.0]
    hyde = [0.0, 0.0, 0.0]
    result = blend_vectors(query, hyde, 0.5)
    assert len(result) == 3
