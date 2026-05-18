from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

_VALID_STRATEGIES = {"char_window", "paragraph", "heading", "sentence"}


@dataclass(frozen=True)
class ChunkingConfig:
    chunk_size: int = 500
    chunk_overlap: int = 50
    strategy: str = "char_window"

    def __post_init__(self) -> None:
        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be greater than zero")
        if self.chunk_overlap < 0:
            raise ValueError("chunk_overlap must be zero or greater")
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        if self.strategy not in _VALID_STRATEGIES:
            raise ValueError(
                f"Unknown chunking strategy '{self.strategy}'. "
                f"Valid options: {sorted(_VALID_STRATEGIES)}"
            )

    @property
    def _chunker_id(self) -> str:
        # Keep "char_window_v1" for the default strategy to preserve existing chunk hashes.
        return "char_window_v1" if self.strategy == "char_window" else self.strategy

    @property
    def config_hash(self) -> str:
        payload = json.dumps(
            {
                "chunker": self._chunker_id,
                "chunk_overlap": self.chunk_overlap,
                "chunk_size": self.chunk_size,
            },
            sort_keys=True,
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    def as_metadata(self) -> dict[str, Any]:
        return {
            "chunker": self._chunker_id,
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
    heading: str | None = field(default=None)


# ── Internal helpers ──────────────────────────────────────────────────────────


def _make_draft(
    index: int,
    text: str,
    char_start: int,
    shared_metadata: dict[str, Any],
    heading: str | None = None,
) -> ChunkDraft:
    extra: dict[str, Any] = {
        "chunk_hash": sha256(text.encode("utf-8")).hexdigest(),
        "text_length": len(text),
    }
    if heading:
        extra["heading"] = heading
    return ChunkDraft(
        chunk_index=index,
        text=text,
        char_start=char_start,
        char_end=char_start + len(text),
        metadata={**shared_metadata, **extra},
        heading=heading,
    )


# ── Strategy implementations ──────────────────────────────────────────────────


def _char_window_chunk(text: str, config: ChunkingConfig) -> list[ChunkDraft]:
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


def _paragraph_chunk(text: str, config: ChunkingConfig) -> list[ChunkDraft]:
    """Split on blank lines; merge short paragraphs, further split oversized ones."""
    shared = config.as_metadata()
    raw_paras = re.split(r"\n{2,}", text)
    buckets: list[str] = []
    current = ""
    for para in raw_paras:
        para = para.strip()
        if not para:
            continue
        joined = f"{current}\n\n{para}".strip() if current else para
        if current and len(joined) > config.chunk_size:
            buckets.append(current)
            current = para
        else:
            current = joined

    if current:
        buckets.append(current)

    out: list[ChunkDraft] = []
    global_index = 0
    char_cursor = 0
    for bucket in buckets:
        if len(bucket) <= config.chunk_size:
            out.append(_make_draft(global_index, bucket, char_cursor, shared))
            global_index += 1
        else:
            sub_config = ChunkingConfig(
                chunk_size=config.chunk_size,
                chunk_overlap=config.chunk_overlap,
                strategy="char_window",
            )
            sub_chunks = _char_window_chunk(bucket, sub_config)
            for sc in sub_chunks:
                out.append(
                    ChunkDraft(
                        chunk_index=global_index,
                        text=sc.text,
                        char_start=char_cursor + sc.char_start,
                        char_end=char_cursor + sc.char_end,
                        metadata={**shared, **sc.metadata},
                    )
                )
                global_index += 1
        char_cursor += len(bucket)

    return out


def _heading_chunk(text: str, config: ChunkingConfig) -> list[ChunkDraft]:
    """Split on Markdown headings; prepend heading to every chunk of that section."""
    shared = config.as_metadata()
    heading_re = re.compile(r"^(#{1,6} .+)$", re.MULTILINE)
    positions = [(m.start(), m.group(1)) for m in heading_re.finditer(text)]

    sections: list[tuple[str | None, str]] = []
    if not positions:
        sections.append((None, text))
    else:
        if positions[0][0] > 0:
            sections.append((None, text[: positions[0][0]].strip()))
        for i, (pos, heading_text) in enumerate(positions):
            end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
            body = text[pos + len(heading_text) : end].strip()
            sections.append((heading_text, body))

    sub_config = ChunkingConfig(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        strategy="char_window",
    )
    out: list[ChunkDraft] = []
    index = 0
    char_cursor = 0
    for heading_text, body in sections:
        prefix = f"{heading_text}\n\n" if heading_text else ""
        full_body = f"{prefix}{body}".strip()
        if not full_body:
            continue
        if len(full_body) <= config.chunk_size:
            out.append(_make_draft(index, full_body, char_cursor, shared, heading=heading_text))
            index += 1
        else:
            sub_chunks = _char_window_chunk(full_body, sub_config)
            for sc in sub_chunks:
                out.append(
                    ChunkDraft(
                        chunk_index=index,
                        text=sc.text,
                        char_start=char_cursor + sc.char_start,
                        char_end=char_cursor + sc.char_end,
                        metadata={**shared, **sc.metadata},
                        heading=heading_text,
                    )
                )
                index += 1
        char_cursor += len(full_body)

    return out


def _sentence_chunk(text: str, config: ChunkingConfig) -> list[ChunkDraft]:
    """Split on sentence boundaries; merge until reaching chunk_size."""
    shared = config.as_metadata()
    # Split after sentence-ending punctuation followed by whitespace or a CJK character.
    # This handles both Western text (space after .) and Chinese text (no space after 。).
    sent_re = re.compile(r"(?<=[.!?。！？])(?=\s|[一-鿿぀-ヿ]|\Z)")
    sentences = sent_re.split(text)

    buckets: list[str] = []
    current = ""
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        joined = f"{current} {sent}".strip() if current else sent
        if current and len(joined) > config.chunk_size:
            buckets.append(current)
            current = sent
        else:
            current = joined

    if current:
        buckets.append(current)

    sub_config = ChunkingConfig(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        strategy="char_window",
    )
    out: list[ChunkDraft] = []
    global_index = 0
    char_cursor = 0
    for bucket in buckets:
        if len(bucket) <= config.chunk_size:
            out.append(_make_draft(global_index, bucket, char_cursor, shared))
            global_index += 1
        else:
            sub_chunks = _char_window_chunk(bucket, sub_config)
            for sc in sub_chunks:
                out.append(
                    ChunkDraft(
                        chunk_index=global_index,
                        text=sc.text,
                        char_start=char_cursor + sc.char_start,
                        char_end=char_cursor + sc.char_end,
                        metadata={**shared, **sc.metadata},
                    )
                )
                global_index += 1
        char_cursor += len(bucket)

    return out


# ── Public API ────────────────────────────────────────────────────────────────


def chunk_text(text: str, config: ChunkingConfig) -> list[ChunkDraft]:
    if text == "":
        return []
    if config.strategy == "char_window":
        return _char_window_chunk(text, config)
    if config.strategy == "paragraph":
        return _paragraph_chunk(text, config)
    if config.strategy == "heading":
        return _heading_chunk(text, config)
    if config.strategy == "sentence":
        return _sentence_chunk(text, config)
    raise ValueError(f"Unknown strategy: {config.strategy}")


__all__ = ["ChunkDraft", "ChunkingConfig", "chunk_text"]
