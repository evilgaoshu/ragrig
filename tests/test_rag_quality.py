"""Unit tests for RAG quality features: chunking strategies, parsers, time decay, rewriting."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from ragrig.chunkers import ChunkDraft, ChunkingConfig, chunk_text

pytestmark = pytest.mark.unit


# ── ChunkingConfig ────────────────────────────────────────────────────────────


def test_chunking_config_default_strategy_is_char_window() -> None:
    config = ChunkingConfig(chunk_size=100, chunk_overlap=10)
    assert config.strategy == "char_window"


def test_chunking_config_rejects_invalid_strategy() -> None:
    with pytest.raises(ValueError, match="Unknown chunking strategy"):
        ChunkingConfig(chunk_size=100, chunk_overlap=10, strategy="invalid")


def test_chunking_config_hash_stable_for_char_window() -> None:
    c1 = ChunkingConfig(chunk_size=500, chunk_overlap=50)
    c2 = ChunkingConfig(chunk_size=500, chunk_overlap=50, strategy="char_window")
    assert c1.config_hash == c2.config_hash


def test_chunking_config_hash_differs_across_strategies() -> None:
    char = ChunkingConfig(chunk_size=500, chunk_overlap=50, strategy="char_window")
    para = ChunkingConfig(chunk_size=500, chunk_overlap=50, strategy="paragraph")
    assert char.config_hash != para.config_hash


def test_chunking_config_metadata_includes_strategy() -> None:
    config = ChunkingConfig(chunk_size=100, chunk_overlap=10, strategy="paragraph")
    meta = config.as_metadata()
    assert meta["chunker"] == "paragraph"


# ── Paragraph chunking ────────────────────────────────────────────────────────


def test_paragraph_chunk_splits_on_blank_lines() -> None:
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    # chunk_size smaller than combined text forces splits
    config = ChunkingConfig(chunk_size=20, chunk_overlap=0, strategy="paragraph")
    chunks = chunk_text(text, config)
    assert len(chunks) == 3
    assert chunks[0].text == "First paragraph."
    assert chunks[1].text == "Second paragraph."


def test_paragraph_chunk_merges_short_paragraphs() -> None:
    text = "A.\n\nB.\n\nC."
    config = ChunkingConfig(chunk_size=20, chunk_overlap=0, strategy="paragraph")
    chunks = chunk_text(text, config)
    # A (2) + B (2) together fit in 20; then C
    assert len(chunks) <= 3


def test_paragraph_chunk_splits_oversized_paragraph() -> None:
    long_para = "x" * 1000
    config = ChunkingConfig(chunk_size=200, chunk_overlap=0, strategy="paragraph")
    chunks = chunk_text(long_para, config)
    assert len(chunks) > 1
    for c in chunks:
        assert len(c.text) <= 200


# ── Heading chunking ──────────────────────────────────────────────────────────


def test_heading_chunk_splits_on_markdown_headings() -> None:
    text = "# Chapter 1\n\nContent one.\n\n## Section 1.1\n\nContent two."
    config = ChunkingConfig(chunk_size=500, chunk_overlap=0, strategy="heading")
    chunks = chunk_text(text, config)
    assert len(chunks) >= 2
    assert "# Chapter 1" in chunks[0].text
    assert "## Section 1.1" in chunks[1].text


def test_heading_chunk_preserves_heading_metadata() -> None:
    text = "# My Title\n\nBody content here."
    config = ChunkingConfig(chunk_size=500, chunk_overlap=0, strategy="heading")
    chunks = chunk_text(text, config)
    assert chunks[0].heading == "# My Title"


def test_heading_chunk_no_headings_returns_single_chunk() -> None:
    text = "Just plain text without any headings."
    config = ChunkingConfig(chunk_size=500, chunk_overlap=0, strategy="heading")
    chunks = chunk_text(text, config)
    assert len(chunks) == 1
    assert chunks[0].text == text


# ── Sentence chunking ─────────────────────────────────────────────────────────


def test_sentence_chunk_splits_on_sentence_boundaries() -> None:
    text = "First sentence. Second sentence. Third sentence."
    config = ChunkingConfig(chunk_size=20, chunk_overlap=0, strategy="sentence")
    chunks = chunk_text(text, config)
    assert len(chunks) >= 2


def test_sentence_chunk_preserves_all_content() -> None:
    text = "Hello world. How are you? I am fine!"
    config = ChunkingConfig(chunk_size=500, chunk_overlap=0, strategy="sentence")
    chunks = chunk_text(text, config)
    # All content should be in one chunk when it fits
    assert len(chunks) == 1
    assert "Hello world" in chunks[0].text


def test_sentence_chunk_handles_chinese_punctuation() -> None:
    text = "这是第一句话。这是第二句话。这是第三句话。"
    # chunk_size=8 ensures each 7-char Chinese sentence forces a split
    config = ChunkingConfig(chunk_size=8, chunk_overlap=0, strategy="sentence")
    chunks = chunk_text(text, config)
    assert len(chunks) > 1


# ── Excel parser ──────────────────────────────────────────────────────────────


def test_excel_parser_raises_on_missing_openpyxl(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "openpyxl":
            raise ImportError("No module named 'openpyxl'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    from ragrig.parsers.excel import ExcelParser, ExcelParserError

    parser = ExcelParser()
    with pytest.raises(ExcelParserError, match="openpyxl"):
        parser.parse(Path("dummy.xlsx"))


def test_excel_parser_name() -> None:
    from ragrig.parsers.excel import ExcelParser

    parser = ExcelParser()
    assert parser.parser_name == "excel"


# ── PPTX parser ───────────────────────────────────────────────────────────────


def test_pptx_parser_raises_on_missing_pptx(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "pptx":
            raise ImportError("No module named 'pptx'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    from ragrig.parsers.pptx import PptxParser, PptxParserError

    parser = PptxParser()
    with pytest.raises(PptxParserError, match="python-pptx"):
        parser.parse(Path("dummy.pptx"))


def test_pptx_parser_name() -> None:
    from ragrig.parsers.pptx import PptxParser

    parser = PptxParser()
    assert parser.parser_name == "pptx"


# ── LLM steps ─────────────────────────────────────────────────────────────────


def test_generate_chunk_description_returns_none_when_no_provider() -> None:
    from ragrig.indexing.llm_steps import generate_chunk_description

    result = generate_chunk_description("Some text", None)
    assert result is None


def test_generate_chunk_description_calls_provider_generate() -> None:
    from ragrig.indexing.llm_steps import generate_chunk_description

    provider = MagicMock()
    provider.generate.return_value = "A summary of the text."
    result = generate_chunk_description("Some text about revenue.", provider)
    assert result == "A summary of the text."
    provider.generate.assert_called_once()


def test_generate_chunk_description_returns_none_on_provider_error() -> None:
    from ragrig.indexing.llm_steps import generate_chunk_description

    provider = MagicMock()
    provider.generate.side_effect = RuntimeError("LLM unavailable")
    result = generate_chunk_description("Some text", provider)
    assert result is None


def test_build_embedding_text_with_description() -> None:
    from ragrig.indexing.llm_steps import build_embedding_text

    result = build_embedding_text("Body text.", "A description.")
    assert result == "A description.\n\nBody text."


def test_build_embedding_text_without_description() -> None:
    from ragrig.indexing.llm_steps import build_embedding_text

    result = build_embedding_text("Body text.", None)
    assert result == "Body text."


# ── Query rewriter ────────────────────────────────────────────────────────────


def test_rewrite_query_no_config_returns_original() -> None:
    from ragrig.retrieval_rewriter import rewrite_query

    result = rewrite_query("short query", config=None, provider=None)
    assert result == ["short query"]


def test_rewrite_query_no_provider_returns_original() -> None:
    from ragrig.retrieval_rewriter import RewriteConfig, rewrite_query

    config = RewriteConfig(provider_name="model.openai")
    result = rewrite_query("short query", config=config, provider=None)
    assert result == ["short query"]


def test_rewrite_query_short_query_unchanged() -> None:
    from ragrig.retrieval_rewriter import RewriteConfig, rewrite_query

    config = RewriteConfig(provider_name="model.openai", decompose_threshold_chars=300)
    provider = MagicMock()
    result = rewrite_query("short", config=config, provider=provider)
    assert result == ["short"]
    provider.generate.assert_not_called()


def test_rewrite_query_decomposes_multi_question() -> None:
    from ragrig.retrieval_rewriter import RewriteConfig, rewrite_query

    config = RewriteConfig(
        provider_name="model.openai",
        decompose_on_multi_question=True,
        decompose_threshold_chars=300,
    )
    provider = MagicMock()
    provider.generate.return_value = "Sub-question 1?\nSub-question 2?\nSub-question 3?"
    query = "First question? Second question?"
    result = rewrite_query(query, config=config, provider=provider)
    assert len(result) == 3
    assert "Sub-question 1?" in result


def test_rewrite_query_decomposes_on_provider_error_returns_original() -> None:
    from ragrig.retrieval_rewriter import RewriteConfig, rewrite_query

    config = RewriteConfig(provider_name="model.openai", decompose_on_multi_question=True)
    provider = MagicMock()
    provider.generate.side_effect = RuntimeError("fail")
    result = rewrite_query("First? Second?", config=config, provider=provider)
    assert result == ["First? Second?"]


def test_merge_retrieval_results_deduplicates_by_chunk_id() -> None:
    from ragrig.retrieval_rewriter import merge_retrieval_results
    import uuid

    chunk_id = uuid.uuid4()
    r1 = MagicMock(chunk_id=chunk_id, score=0.8)
    r2 = MagicMock(chunk_id=chunk_id, score=0.9)
    r3 = MagicMock(chunk_id=uuid.uuid4(), score=0.7)

    merged = merge_retrieval_results([[r1, r3], [r2]], top_k=10)
    assert len(merged) == 2
    # r2 (0.9) wins over r1 (0.8) for the same chunk
    chunk_results = {r.chunk_id: r for r in merged}
    assert chunk_results[chunk_id].score == 0.9


# ── Time decay ────────────────────────────────────────────────────────────────


def test_apply_time_decay_noop_when_weights_zero() -> None:
    from ragrig.retrieval import _apply_time_decay, RetrievalResult
    import uuid

    r = RetrievalResult(
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        chunk_index=0,
        document_uri="test",
        source_uri=None,
        text="text",
        text_preview="text",
        distance=0.1,
        score=0.9,
        chunk_metadata={},
    )
    result = _apply_time_decay([r], sim_weight=1.0, time_decay_weight=0.0, doc_weight=0.0)
    assert result[0].score == 0.9


def test_apply_time_decay_newer_doc_scores_higher() -> None:
    from ragrig.retrieval import _apply_time_decay, RetrievalResult
    import uuid

    now = datetime.now(timezone.utc)
    new_chunk = RetrievalResult(
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        chunk_index=0,
        document_uri="new",
        source_uri=None,
        text="text",
        text_preview="text",
        distance=0.2,
        score=0.8,
        chunk_metadata={},
        chunk_created_at=now,
    )
    old_chunk = RetrievalResult(
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        chunk_id=uuid.uuid4(),
        chunk_index=0,
        document_uri="old",
        source_uri=None,
        text="text",
        text_preview="text",
        distance=0.2,
        score=0.8,
        chunk_metadata={},
        chunk_created_at=now - timedelta(days=365),
    )
    results = _apply_time_decay(
        [old_chunk, new_chunk],
        sim_weight=0.5,
        time_decay_weight=0.5,
        doc_weight=0.0,
        decay_rate=0.1,
    )
    # new chunk should be first (higher score due to lower time decay penalty)
    assert results[0].document_uri == "new"
