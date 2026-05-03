from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from typing import Any


@dataclass(frozen=True)
class ChunkingConfig:
    chunk_size: int = 500
    chunk_overlap: int = 50

    def __post_init__(self) -> None:
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be greater than zero")
        if self.chunk_overlap < 0:
            raise ValueError("chunk_overlap must be zero or greater")
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")

    @property
    def config_hash(self) -> str:
        payload = json.dumps(
            {
                "chunker": "char_window_v1",
                "chunk_overlap": self.chunk_overlap,
                "chunk_size": self.chunk_size,
            },
            sort_keys=True,
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def as_metadata(self) -> dict[str, Any]:
        return {
            "chunker": "char_window_v1",
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "config_hash": self.config_hash,
        }


@dataclass(frozen=True)
class ChunkDraft:
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    metadata: dict[str, Any]


def chunk_text(text: str, config: ChunkingConfig) -> list[ChunkDraft]:
    if text == "":
        return []

    chunks: list[ChunkDraft] = []
    step = config.chunk_size - config.chunk_overlap
    start = 0
    index = 0
    shared_metadata = config.as_metadata()

    while start < len(text):
        end = min(len(text), start + config.chunk_size)
        chunk_text_value = text[start:end]
        chunks.append(
            ChunkDraft(
                chunk_index=index,
                text=chunk_text_value,
                char_start=start,
                char_end=end,
                metadata={
                    **shared_metadata,
                    "chunk_hash": sha256(chunk_text_value.encode("utf-8")).hexdigest(),
                    "text_length": len(chunk_text_value),
                },
            )
        )
        if end == len(text):
            break
        start += step
        index += 1

    return chunks


__all__ = ["ChunkDraft", "ChunkingConfig", "chunk_text"]
