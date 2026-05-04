from __future__ import annotations

from hashlib import sha256

import pytest

from ragrig.embeddings import DeterministicEmbeddingProvider


def test_deterministic_embedding_provider_rejects_invalid_dimensions() -> None:
    with pytest.raises(ValueError, match="dimensions must be greater than zero"):
        DeterministicEmbeddingProvider(dimensions=0)


def test_deterministic_embedding_provider_embeds_empty_text() -> None:
    result = DeterministicEmbeddingProvider(dimensions=4).embed_text("")

    assert len(result.vector) == 4
    assert all(-1.0 <= value <= 1.0 for value in result.vector)
    assert result.metadata == {"text_hash": sha256(b"").hexdigest()}
