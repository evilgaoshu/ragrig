"""Tests for contextual retrieval — generate_chunk_context and pipeline wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ragrig.indexing.llm_steps import generate_chunk_context

# ---------------------------------------------------------------------------
# generate_chunk_context
# ---------------------------------------------------------------------------


def _make_provider(response: str) -> MagicMock:
    p = MagicMock()
    p.generate.return_value = response
    return p


def test_generate_chunk_context_returns_context() -> None:
    provider = _make_provider("This chunk describes the installation steps for RAGRig.")
    result = generate_chunk_context(
        doc_text="# RAGRig Guide\n\nInstallation...",
        chunk_text="Run pip install ragrig to install.",
        provider=provider,
    )
    assert result == "This chunk describes the installation steps for RAGRig."
    provider.generate.assert_called_once()


def test_generate_chunk_context_none_provider_returns_none() -> None:
    result = generate_chunk_context(
        doc_text="full doc",
        chunk_text="chunk",
        provider=None,
    )
    assert result is None


def test_generate_chunk_context_empty_chunk_returns_none() -> None:
    provider = _make_provider("some context")
    result = generate_chunk_context(
        doc_text="full doc",
        chunk_text="   ",
        provider=provider,
    )
    assert result is None
    provider.generate.assert_not_called()


def test_generate_chunk_context_provider_error_returns_none() -> None:
    provider = MagicMock()
    provider.generate.side_effect = RuntimeError("LLM timeout")
    result = generate_chunk_context(
        doc_text="full doc",
        chunk_text="some chunk",
        provider=provider,
    )
    assert result is None


def test_generate_chunk_context_empty_response_returns_none() -> None:
    provider = _make_provider("   ")
    result = generate_chunk_context(
        doc_text="full doc",
        chunk_text="some chunk",
        provider=provider,
    )
    assert result is None


def test_generate_chunk_context_truncates_doc() -> None:
    provider = _make_provider("context")
    long_doc = "x" * 20_000
    generate_chunk_context(
        doc_text=long_doc,
        chunk_text="chunk",
        provider=provider,
        max_doc_chars=500,
    )
    call_args = provider.generate.call_args[0][0]
    # doc in prompt must not exceed max_doc_chars
    assert "x" * 501 not in call_args


def test_generate_chunk_context_includes_doc_and_chunk_in_prompt() -> None:
    provider = _make_provider("context sentence")
    generate_chunk_context(
        doc_text="DOCUMENT_CONTENT",
        chunk_text="CHUNK_CONTENT",
        provider=provider,
    )
    prompt = provider.generate.call_args[0][0]
    assert "DOCUMENT_CONTENT" in prompt
    assert "CHUNK_CONTENT" in prompt


# ---------------------------------------------------------------------------
# Pipeline integration — _replace_version_index with contextual_provider
# ---------------------------------------------------------------------------


def _make_doc_version(text: str) -> MagicMock:
    dv = MagicMock()
    dv.id = __import__("uuid").uuid4()
    dv.extracted_text = text
    dv.content_hash = "abc123"
    dv.parser_name = "plain"
    dv.version_number = 1
    dv.metadata_json = {}
    return dv


def _make_document(dv: MagicMock) -> MagicMock:
    doc = MagicMock()
    doc.id = __import__("uuid").uuid4()
    doc.uri = "guide.md"
    doc.metadata_json = {}
    doc.knowledge_base_id = __import__("uuid").uuid4()
    return doc


def test_pipeline_stores_context_prefix_when_provider_set() -> None:
    """Verify context_prefix is saved on the Chunk when contextual_provider is given."""
    from ragrig.indexing.pipeline import _replace_version_index

    dv = _make_doc_version("Full document text for context.")
    doc = _make_document(dv)

    session = MagicMock()
    session.scalars.return_value = iter([])

    embedding_provider = MagicMock()
    embedding_result = MagicMock()
    embedding_result.provider = "test"
    embedding_result.model = "test-model"
    embedding_result.dimensions = 8
    embedding_result.vector = [0.1] * 8
    embedding_result.metadata = {}
    embedding_provider.embed_text.return_value = embedding_result

    contextual_provider = _make_provider("This chunk covers installation.")

    added_chunks = []

    def capture_add(obj):
        added_chunks.append(obj)

    session.add = capture_add

    with (
        patch("ragrig.indexing.pipeline.delete"),
        patch("ragrig.indexing.pipeline.select"),
        patch("ragrig.indexing.pipeline.Embedding"),
    ):
        _replace_version_index(
            session,
            document_version=dv,
            document=doc,
            chunking_config=__import__(
                "ragrig.chunkers", fromlist=["ChunkingConfig"]
            ).ChunkingConfig(chunk_size=50, chunk_overlap=0),
            embedding_provider=embedding_provider,
            chunk_profile_id="cp1",
            embed_profile_id="ep1",
            contextual_provider=contextual_provider,
        )

    from ragrig.db.models import Chunk

    chunk_objs = [o for o in added_chunks if isinstance(o, Chunk)]
    assert len(chunk_objs) > 0
    assert all(c.context_prefix == "This chunk covers installation." for c in chunk_objs)


def test_pipeline_no_context_prefix_when_provider_none() -> None:
    """context_prefix should be None when no contextual_provider is given."""
    from ragrig.indexing.pipeline import _replace_version_index

    dv = _make_doc_version("Some document text.")
    doc = _make_document(dv)

    session = MagicMock()
    session.scalars.return_value = iter([])

    embedding_provider = MagicMock()
    embedding_result = MagicMock()
    embedding_result.provider = "test"
    embedding_result.model = "test-model"
    embedding_result.dimensions = 8
    embedding_result.vector = [0.1] * 8
    embedding_result.metadata = {}
    embedding_provider.embed_text.return_value = embedding_result

    added_chunks = []

    def capture_add(obj):
        added_chunks.append(obj)

    session.add = capture_add

    with (
        patch("ragrig.indexing.pipeline.delete"),
        patch("ragrig.indexing.pipeline.select"),
        patch("ragrig.indexing.pipeline.Embedding"),
    ):
        _replace_version_index(
            session,
            document_version=dv,
            document=doc,
            chunking_config=__import__(
                "ragrig.chunkers", fromlist=["ChunkingConfig"]
            ).ChunkingConfig(chunk_size=50, chunk_overlap=0),
            embedding_provider=embedding_provider,
            chunk_profile_id="cp1",
            embed_profile_id="ep1",
            contextual_provider=None,
        )

    from ragrig.db.models import Chunk

    chunk_objs = [o for o in added_chunks if isinstance(o, Chunk)]
    assert all(c.context_prefix is None for c in chunk_objs)


def test_pipeline_uses_context_prefix_for_embedding_input() -> None:
    """Embedding input should be 'context\\n\\nchunk' when context is generated."""
    from ragrig.indexing.pipeline import _replace_version_index

    dv = _make_doc_version("Document about RAGRig features.")
    doc = _make_document(dv)

    session = MagicMock()
    session.scalars.return_value = iter([])

    embedding_provider = MagicMock()
    embedding_result = MagicMock()
    embedding_result.provider = "test"
    embedding_result.model = "test-model"
    embedding_result.dimensions = 8
    embedding_result.vector = [0.1] * 8
    embedding_result.metadata = {}
    embedding_provider.embed_text.return_value = embedding_result

    contextual_provider = _make_provider("Context: this covers RAGRig features.")

    session.add = MagicMock()

    with (
        patch("ragrig.indexing.pipeline.delete"),
        patch("ragrig.indexing.pipeline.select"),
        patch("ragrig.indexing.pipeline.Embedding"),
    ):
        _replace_version_index(
            session,
            document_version=dv,
            document=doc,
            chunking_config=__import__(
                "ragrig.chunkers", fromlist=["ChunkingConfig"]
            ).ChunkingConfig(chunk_size=50, chunk_overlap=0),
            embedding_provider=embedding_provider,
            chunk_profile_id="cp1",
            embed_profile_id="ep1",
            contextual_provider=contextual_provider,
        )

    # Every embed_text call should include the context prefix
    for call in embedding_provider.embed_text.call_args_list:
        text_arg = call[0][0]
        assert text_arg.startswith("Context: this covers RAGRig features.")
