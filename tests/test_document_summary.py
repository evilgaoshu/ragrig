"""Unit tests for document-level summary indexing."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ragrig.indexing.llm_steps import generate_document_summary

pytestmark = pytest.mark.unit


# ── generate_document_summary ─────────────────────────────────────────────────


def test_summary_returns_none_when_no_provider() -> None:
    result = generate_document_summary("Some document text.", None)
    assert result is None


def test_summary_returns_none_for_empty_text() -> None:
    provider = MagicMock()
    result = generate_document_summary("   ", provider)
    assert result is None
    provider.generate.assert_not_called()


def test_summary_calls_provider_generate() -> None:
    provider = MagicMock()
    provider.generate.return_value = "This document covers enterprise RAG patterns."
    result = generate_document_summary("Long document text here.", provider)
    assert result == "This document covers enterprise RAG patterns."
    provider.generate.assert_called_once()


def test_summary_prompt_includes_document_text() -> None:
    provider = MagicMock()
    provider.generate.return_value = "Summary."
    generate_document_summary("Unique document content XYZ.", provider)
    prompt = provider.generate.call_args[0][0]
    assert "Unique document content XYZ." in prompt


def test_summary_truncates_very_long_text() -> None:
    provider = MagicMock()
    provider.generate.return_value = "Summary."
    long_text = "A" * 20000
    generate_document_summary(long_text, provider)
    prompt = provider.generate.call_args[0][0]
    # The document portion passed to the LLM must be ≤ 12000 chars
    assert len(prompt) < 20000


def test_summary_returns_none_on_provider_error() -> None:
    provider = MagicMock()
    provider.generate.side_effect = RuntimeError("LLM unavailable")
    result = generate_document_summary("Some text.", provider)
    assert result is None


def test_summary_returns_none_when_provider_returns_empty() -> None:
    provider = MagicMock()
    provider.generate.return_value = "   "
    result = generate_document_summary("Some text.", provider)
    assert result is None


def test_summary_strips_whitespace_from_result() -> None:
    provider = MagicMock()
    provider.generate.return_value = "  Trimmed summary.  "
    result = generate_document_summary("Text.", provider)
    assert result == "Trimmed summary."


# ── result_source field ───────────────────────────────────────────────────────


def test_retrieval_result_default_source_is_chunk() -> None:
    import uuid

    from ragrig.retrieval import RetrievalResult

    r = RetrievalResult(
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        chunk_index=0,
        document_uri="doc",
        source_uri=None,
        text="text",
        text_preview="text",
        distance=0.1,
        score=0.9,
        chunk_metadata={},
    )
    assert r.result_source == "chunk"


def test_retrieval_result_can_be_document_summary() -> None:
    import uuid

    from ragrig.retrieval import RetrievalResult

    r = RetrievalResult(
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        chunk_index=-1,
        document_uri="doc",
        source_uri=None,
        text="This document discusses RAG architecture.",
        text_preview="This document discusses RAG architecture.",
        distance=0.05,
        score=0.95,
        chunk_metadata={},
        result_source="document_summary",
    )
    assert r.result_source == "document_summary"
