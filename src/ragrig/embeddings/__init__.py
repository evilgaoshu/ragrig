from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any


@dataclass(frozen=True)
class EmbeddingResult:
    provider: str
    model: str
    dimensions: int
    vector: list[float]
    metadata: dict[str, Any]


class DeterministicEmbeddingProvider:
    provider_name = "deterministic-local"

    def __init__(self, *, dimensions: int = 8) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be greater than zero")
        self.dimensions = dimensions
        self.model_name = f"hash-{dimensions}d"

    def embed_text(self, text: str) -> EmbeddingResult:
        digest = sha256(text.encode("utf-8")).digest()
        values = [0.0] * self.dimensions

        for index, byte in enumerate(digest):
            values[index % self.dimensions] += byte / 255.0
        for index, byte in enumerate(text.encode("utf-8")):
            values[index % self.dimensions] += ((byte % 29) - 14) / 29.0

        max_abs = max((abs(value) for value in values), default=1.0) or 1.0
        normalized = [round(value / max_abs, 6) for value in values]

        return EmbeddingResult(
            provider=self.provider_name,
            model=self.model_name,
            dimensions=self.dimensions,
            vector=normalized,
            metadata={
                "text_hash": sha256(text.encode("utf-8")).hexdigest(),
            },
        )


__all__ = ["DeterministicEmbeddingProvider", "EmbeddingResult"]
