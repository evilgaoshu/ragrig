from __future__ import annotations

import pytest

from ragrig.chunkers import (
    CHUNK_TEMPLATES,
    ChunkingConfig,
    chunk_text,
    chunk_text_hierarchical,
    chunking_config_from_template,
)

pytestmark = pytest.mark.unit


def test_chunking_config_rejects_invalid_sizes() -> None:
    with pytest.raises(ValueError, match="chunk_size must be greater than zero"):
        ChunkingConfig(chunk_size=0)

    with pytest.raises(ValueError, match="chunk_overlap must be zero or greater"):
        ChunkingConfig(chunk_size=10, chunk_overlap=-1)

    with pytest.raises(ValueError, match="chunk_overlap must be smaller than chunk_size"):
        ChunkingConfig(chunk_size=10, chunk_overlap=10)


def test_chunk_text_returns_empty_list_for_empty_input() -> None:
    assert chunk_text("", ChunkingConfig()) == []


def test_chunking_config_metadata_exposes_stable_hash() -> None:
    config = ChunkingConfig(chunk_size=32, chunk_overlap=8)

    metadata = config.as_metadata()

    assert metadata["chunker"] == "char_window_v1"
    assert metadata["chunk_size"] == 32
    assert metadata["chunk_overlap"] == 8
    assert metadata["config_hash"] == config.config_hash
    assert metadata["chunk_template_id"] == "char_window_v1"
    assert metadata["chunk_template_version"] == "1"
    assert metadata["chunk_strategy"] == "char_window"
    assert metadata["template_parameters"] == {"chunk_size": 32, "chunk_overlap": 8}


@pytest.mark.parametrize(
    ("template_id", "split_reason"),
    [
        ("char_window_v1", "window_boundary"),
        ("paragraph_v1", "paragraph_boundary"),
        ("heading_v1", "heading_boundary"),
        ("sentence_v1", "sentence_boundary"),
    ],
)
def test_templates_produce_explainable_chunk_metadata(
    template_id: str,
    split_reason: str,
) -> None:
    config = chunking_config_from_template(
        template_id,
        {"chunk_size": 20, "chunk_overlap": 2},
    )
    chunks = chunk_text("# Heading\n\nOne sentence. Two sentence.", config)

    assert chunks
    assert all(chunk.metadata["chunk_template_id"] == template_id for chunk in chunks)
    assert all(chunk.metadata["split_reason"] == split_reason for chunk in chunks)
    assert all(chunk.metadata["char_start"] == chunk.char_start for chunk in chunks)
    assert all(chunk.metadata["char_end"] == chunk.char_end for chunk in chunks)
    assert all(chunk.metadata["source_block_id"] for chunk in chunks)


def test_all_existing_strategies_have_stable_templates() -> None:
    assert set(CHUNK_TEMPLATES) == {
        "char_window_v1",
        "paragraph_v1",
        "heading_v1",
        "sentence_v1",
        "parent_child_v1",
        "recursive_v1",
        "token_aware_v1",
    }


def test_parent_child_chunks_expose_parent_template_and_linkage() -> None:
    config = chunking_config_from_template(
        "parent_child_v1",
        {
            "chunk_size": 10,
            "chunk_overlap": 1,
            "parent_chunk_size": 20,
            "child_strategy": "char_window",
        },
    )
    parents, children = chunk_text_hierarchical("abcdefghijklmnopqrstuvwxyz", config)

    assert parents and children
    assert all(draft.metadata["chunk_template_id"] == "parent_child_v1" for draft in parents)
    assert all(draft.metadata["chunk_template_id"] == "parent_child_v1" for draft in children)
    assert all(draft.metadata["parent_chunk_index"] is not None for draft in children)


def test_template_metadata_does_not_change_legacy_config_hash() -> None:
    config = ChunkingConfig(chunk_size=32, chunk_overlap=8)

    assert config.config_hash == (
        "5107b53f1dca5db77445fc5b67f370541ff9efbda0b86f6856763f19b769cec3"
    )


def test_recursive_template_prefers_boundaries_then_falls_back_to_windows() -> None:
    config = chunking_config_from_template(
        "recursive_v1",
        {"chunk_size": 45, "chunk_overlap": 5},
    )
    text = (
        "# First\n\nShort paragraph.\n\n"
        "This sentence is deliberately much longer than the configured recursive chunk size."
        "\n\n# Second\n\nTail."
    )

    chunks = chunk_text(text, config)
    reasons = {chunk.metadata["split_reason"] for chunk in chunks}

    assert chunks
    assert "heading_boundary" in reasons
    assert "window_boundary" in reasons
    assert all(chunk.metadata["chunk_template_id"] == "recursive_v1" for chunk in chunks)
    assert all(chunk.metadata["split_explanation"] for chunk in chunks)


def test_token_aware_template_respects_budget_and_overlap() -> None:
    config = chunking_config_from_template(
        "token_aware_v1",
        {"max_tokens": 4, "token_overlap": 1},
    )
    chunks = chunk_text("one two three four five six seven", config)

    assert [chunk.metadata["estimated_tokens"] for chunk in chunks] == [4, 4]
    assert all(chunk.metadata["estimated_tokens"] <= 4 for chunk in chunks)
    assert chunks[0].text.split()[-1] == chunks[1].text.split()[0]
    assert all(chunk.metadata["split_reason"] == "token_budget" for chunk in chunks)


def test_recursive_short_text_records_that_no_fallback_was_needed() -> None:
    chunks = chunk_text(
        "Short text.",
        chunking_config_from_template(
            "recursive_v1",
            {"chunk_size": 50, "chunk_overlap": 5},
        ),
    )

    assert chunks[0].metadata["split_reason"] == "recursive_fit"


def test_parent_child_rejects_token_aware_without_token_parameter_surface() -> None:
    with pytest.raises(ValueError, match="does not support token_aware"):
        chunking_config_from_template(
            "parent_child_v1",
            {
                "chunk_size": 10,
                "chunk_overlap": 1,
                "parent_chunk_size": 20,
                "child_strategy": "token_aware",
            },
        )
