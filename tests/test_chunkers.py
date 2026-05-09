from __future__ import annotations

import pytest

from ragrig.chunkers import ChunkingConfig, chunk_text

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

    assert metadata == {
        "chunker": "char_window_v1",
        "chunk_size": 32,
        "chunk_overlap": 8,
        "config_hash": config.config_hash,
    }
