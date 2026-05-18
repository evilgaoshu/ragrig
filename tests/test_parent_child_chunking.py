"""Unit tests for parent-child chunking."""

from __future__ import annotations

import pytest

from ragrig.chunkers import ChunkingConfig, chunk_text_hierarchical

pytestmark = pytest.mark.unit


# ── ChunkingConfig validation ─────────────────────────────────────────────────


def test_parent_chunk_size_none_by_default() -> None:
    config = ChunkingConfig(chunk_size=100, chunk_overlap=10)
    assert config.parent_chunk_size is None


def test_parent_chunk_size_must_exceed_chunk_size() -> None:
    with pytest.raises(ValueError, match="parent_chunk_size must be greater than chunk_size"):
        ChunkingConfig(chunk_size=200, chunk_overlap=0, parent_chunk_size=100)


def test_parent_chunk_size_equal_to_chunk_size_rejected() -> None:
    with pytest.raises(ValueError, match="parent_chunk_size must be greater than chunk_size"):
        ChunkingConfig(chunk_size=200, chunk_overlap=0, parent_chunk_size=200)


def test_parent_chunk_size_valid() -> None:
    config = ChunkingConfig(chunk_size=100, chunk_overlap=10, parent_chunk_size=500)
    assert config.parent_chunk_size == 500


def test_config_hash_differs_with_and_without_parent_chunk_size() -> None:
    flat = ChunkingConfig(chunk_size=100, chunk_overlap=10)
    hierarchical = ChunkingConfig(chunk_size=100, chunk_overlap=10, parent_chunk_size=500)
    assert flat.config_hash != hierarchical.config_hash


def test_config_hash_stable_same_parent_chunk_size() -> None:
    c1 = ChunkingConfig(chunk_size=100, chunk_overlap=10, parent_chunk_size=500)
    c2 = ChunkingConfig(chunk_size=100, chunk_overlap=10, parent_chunk_size=500)
    assert c1.config_hash == c2.config_hash


def test_as_metadata_includes_parent_chunk_size() -> None:
    config = ChunkingConfig(chunk_size=100, chunk_overlap=0, parent_chunk_size=400)
    meta = config.as_metadata()
    assert meta["parent_chunk_size"] == 400


def test_as_metadata_excludes_parent_chunk_size_when_none() -> None:
    config = ChunkingConfig(chunk_size=100, chunk_overlap=0)
    assert "parent_chunk_size" not in config.as_metadata()


# ── chunk_text_hierarchical ───────────────────────────────────────────────────


def test_hierarchical_requires_parent_chunk_size() -> None:
    config = ChunkingConfig(chunk_size=100, chunk_overlap=0)
    with pytest.raises(ValueError, match="parent_chunk_size must be set"):
        chunk_text_hierarchical("some text", config)


def test_hierarchical_empty_text_returns_empty_lists() -> None:
    config = ChunkingConfig(chunk_size=50, chunk_overlap=0, parent_chunk_size=200)
    parents, children = chunk_text_hierarchical("", config)
    assert parents == []
    assert children == []


def test_hierarchical_returns_parent_and_child_lists() -> None:
    text = "A" * 600
    config = ChunkingConfig(chunk_size=100, chunk_overlap=0, parent_chunk_size=300)
    parents, children = chunk_text_hierarchical(text, config)
    assert len(parents) >= 1
    assert len(children) >= len(parents)


def test_children_reference_parent_index() -> None:
    text = "Word " * 200  # 1000 chars
    config = ChunkingConfig(chunk_size=100, chunk_overlap=0, parent_chunk_size=400)
    parents, children = chunk_text_hierarchical(text, config)
    parent_indices = {p.chunk_index for p in parents}
    for child in children:
        assert child.parent_chunk_index in parent_indices


def test_children_have_sequential_chunk_index() -> None:
    text = "X" * 800
    config = ChunkingConfig(chunk_size=100, chunk_overlap=0, parent_chunk_size=400)
    _, children = chunk_text_hierarchical(text, config)
    indices = [c.chunk_index for c in children]
    assert indices == list(range(len(children)))


def test_child_char_positions_are_document_relative() -> None:
    text = "A" * 200 + "B" * 200
    config = ChunkingConfig(chunk_size=100, chunk_overlap=0, parent_chunk_size=200)
    _, children = chunk_text_hierarchical(text, config)
    # The second parent starts at char 200; its first child must start >= 200
    second_parent_children = [c for c in children if c.parent_chunk_index == 1]
    if second_parent_children:
        assert second_parent_children[0].char_start >= 200


def test_all_child_text_covers_full_content() -> None:
    text = "Hello world. " * 40  # 520 chars
    config = ChunkingConfig(chunk_size=50, chunk_overlap=0, parent_chunk_size=200)
    _, children = chunk_text_hierarchical(text, config)
    # Concatenate all child texts and verify they contain the original content
    combined = "".join(c.text for c in children)
    assert len(combined) >= len(text.strip()) * 0.95


def test_single_chunk_document_yields_one_parent_one_child() -> None:
    text = "Short text."
    config = ChunkingConfig(chunk_size=100, chunk_overlap=0, parent_chunk_size=500)
    parents, children = chunk_text_hierarchical(text, config)
    assert len(parents) == 1
    assert len(children) == 1
    assert children[0].parent_chunk_index == parents[0].chunk_index


def test_hierarchical_with_paragraph_strategy() -> None:
    text = "Para one.\n\nPara two.\n\nPara three.\n\nPara four."
    config = ChunkingConfig(
        chunk_size=15, chunk_overlap=0, parent_chunk_size=30, strategy="paragraph"
    )
    parents, children = chunk_text_hierarchical(text, config)
    assert len(parents) >= 1
    assert len(children) >= len(parents)


def test_hierarchical_with_sentence_strategy() -> None:
    text = "First sentence. Second sentence. Third sentence. Fourth sentence."
    config = ChunkingConfig(
        chunk_size=20, chunk_overlap=0, parent_chunk_size=60, strategy="sentence"
    )
    parents, children = chunk_text_hierarchical(text, config)
    assert len(parents) >= 1
    assert all(c.parent_chunk_index is not None for c in children)


def test_child_metadata_includes_parent_chunk_size() -> None:
    text = "A" * 300
    config = ChunkingConfig(chunk_size=100, chunk_overlap=0, parent_chunk_size=300)
    _, children = chunk_text_hierarchical(text, config)
    assert children[0].metadata.get("parent_chunk_size") == 300
