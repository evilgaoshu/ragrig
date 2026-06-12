from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any

_VALID_STRATEGIES = {"char_window", "paragraph", "heading", "sentence"}
_TEMPLATE_VERSION = "1"


@dataclass(frozen=True)
class ChunkTemplate:
    id: str
    version: str
    display_name: str
    strategy: str
    parameters: dict[str, Any]
    split_rules: list[str]
    limitations: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "display_name": self.display_name,
            "strategy": self.strategy,
            "parameters": dict(self.parameters),
            "split_rules": list(self.split_rules),
            "limitations": list(self.limitations),
        }


CHUNK_TEMPLATES: dict[str, ChunkTemplate] = {
    "char_window_v1": ChunkTemplate(
        id="char_window_v1",
        version=_TEMPLATE_VERSION,
        display_name="Character window",
        strategy="char_window",
        parameters={"chunk_size": 500, "chunk_overlap": 50},
        split_rules=["Split at fixed character windows.", "Retain configured overlap."],
        limitations=["May split sentences, tables, and semantic blocks."],
    ),
    "paragraph_v1": ChunkTemplate(
        id="paragraph_v1",
        version=_TEMPLATE_VERSION,
        display_name="Paragraph-aware",
        strategy="paragraph",
        parameters={"chunk_size": 500, "chunk_overlap": 50},
        split_rules=["Split on blank-line paragraph boundaries.", "Merge short paragraphs."],
        limitations=["Oversized paragraphs fall back to character windows."],
    ),
    "heading_v1": ChunkTemplate(
        id="heading_v1",
        version=_TEMPLATE_VERSION,
        display_name="Heading-aware",
        strategy="heading",
        parameters={"chunk_size": 500, "chunk_overlap": 50},
        split_rules=[
            "Split Markdown sections at headings.",
            "Repeat the heading in section chunks.",
        ],
        limitations=["Oversized sections fall back to character windows."],
    ),
    "sentence_v1": ChunkTemplate(
        id="sentence_v1",
        version=_TEMPLATE_VERSION,
        display_name="Sentence-aware",
        strategy="sentence",
        parameters={"chunk_size": 500, "chunk_overlap": 50},
        split_rules=["Split at sentence punctuation.", "Merge sentences up to chunk_size."],
        limitations=["Oversized sentences fall back to character windows."],
    ),
    "parent_child_v1": ChunkTemplate(
        id="parent_child_v1",
        version=_TEMPLATE_VERSION,
        display_name="Parent-child",
        strategy="parent_child",
        parameters={
            "chunk_size": 500,
            "chunk_overlap": 50,
            "parent_chunk_size": 1500,
            "child_strategy": "char_window",
        },
        split_rules=["Create large parent context chunks.", "Embed smaller child chunks."],
        limitations=["P0 manual split/merge is disabled to preserve parent-child links."],
    ),
}

_STRATEGY_TEMPLATE_IDS = {
    "char_window": "char_window_v1",
    "paragraph": "paragraph_v1",
    "heading": "heading_v1",
    "sentence": "sentence_v1",
}


@dataclass(frozen=True)
class ChunkingConfig:
    chunk_size: int = 500
    chunk_overlap: int = 50
    strategy: str = "char_window"
    parent_chunk_size: int | None = None  # when set, enables parent-child chunking

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
        if self.parent_chunk_size is not None:
            if self.parent_chunk_size <= self.chunk_size:
                raise ValueError("parent_chunk_size must be greater than chunk_size")

    @property
    def _chunker_id(self) -> str:
        # Keep "char_window_v1" for the default strategy to preserve existing chunk hashes.
        return "char_window_v1" if self.strategy == "char_window" else self.strategy

    @property
    def template_id(self) -> str:
        if self.parent_chunk_size is not None:
            return "parent_child_v1"
        return _STRATEGY_TEMPLATE_IDS[self.strategy]

    @property
    def config_hash(self) -> str:
        payload: dict[str, Any] = {
            "chunker": self._chunker_id,
            "chunk_overlap": self.chunk_overlap,
            "chunk_size": self.chunk_size,
        }
        if self.parent_chunk_size is not None:
            payload["parent_chunk_size"] = self.parent_chunk_size
        return sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def as_metadata(self) -> dict[str, Any]:
        template = CHUNK_TEMPLATES[self.template_id]
        meta: dict[str, Any] = {
            "chunker": self._chunker_id,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "config_hash": self.config_hash,
            "chunk_template_id": template.id,
            "chunk_template_version": template.version,
            "chunk_strategy": template.strategy,
            "template_parameters": {
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
            },
        }
        if self.parent_chunk_size is not None:
            meta["parent_chunk_size"] = self.parent_chunk_size
            meta["template_parameters"]["parent_chunk_size"] = self.parent_chunk_size
            meta["template_parameters"]["child_strategy"] = self.strategy
        return meta


@dataclass(frozen=True)
class ChunkDraft:
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    metadata: dict[str, Any]
    heading: str | None = field(default=None)
    parent_chunk_index: int | None = field(default=None)  # set on child drafts only


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


def _source_block_id(source_block_type: str, char_start: int, char_end: int) -> str:
    value = f"{source_block_type}:{char_start}:{char_end}"
    return sha256(value.encode("utf-8")).hexdigest()[:20]


def _explain_drafts(
    drafts: list[ChunkDraft],
    *,
    config: ChunkingConfig,
    split_reason: str,
    source_block_type: str,
) -> list[ChunkDraft]:
    explained: list[ChunkDraft] = []
    for draft in drafts:
        metadata = {
            **draft.metadata,
            **config.as_metadata(),
            "split_reason": split_reason,
            "split_explanation": f"{config.template_id} applied {split_reason}.",
            "char_start": draft.char_start,
            "char_end": draft.char_end,
            "source_block_type": source_block_type,
            "source_block_id": _source_block_id(
                source_block_type,
                draft.char_start,
                draft.char_end,
            ),
        }
        if draft.heading:
            metadata["heading"] = draft.heading
            metadata["section_id"] = _source_block_id(
                "section",
                draft.char_start,
                draft.char_end,
            )
        if draft.parent_chunk_index is not None:
            metadata["parent_chunk_index"] = draft.parent_chunk_index
        explained.append(
            ChunkDraft(
                chunk_index=draft.chunk_index,
                text=draft.text,
                char_start=draft.char_start,
                char_end=draft.char_end,
                metadata=metadata,
                heading=draft.heading,
                parent_chunk_index=draft.parent_chunk_index,
            )
        )
    return explained


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
        drafts = _char_window_chunk(text, config)
        return _explain_drafts(
            drafts,
            config=config,
            split_reason="window_boundary",
            source_block_type="unknown",
        )
    if config.strategy == "paragraph":
        drafts = _paragraph_chunk(text, config)
        return _explain_drafts(
            drafts,
            config=config,
            split_reason="paragraph_boundary",
            source_block_type="paragraph",
        )
    if config.strategy == "heading":
        drafts = _heading_chunk(text, config)
        return _explain_drafts(
            drafts,
            config=config,
            split_reason="heading_boundary",
            source_block_type="heading",
        )
    if config.strategy == "sentence":
        drafts = _sentence_chunk(text, config)
        return _explain_drafts(
            drafts,
            config=config,
            split_reason="sentence_boundary",
            source_block_type="paragraph",
        )
    raise ValueError(f"Unknown strategy: {config.strategy}")


def chunk_text_hierarchical(
    text: str, config: ChunkingConfig
) -> tuple[list[ChunkDraft], list[ChunkDraft]]:
    """Split text into (parent_drafts, child_drafts) for parent-child indexing.

    Parents are large segments used to provide full context to the LLM.
    Children are small segments embedded for precise retrieval.
    Each child carries ``parent_chunk_index`` pointing at its parent.

    Requires ``config.parent_chunk_size`` to be set.
    """
    if config.parent_chunk_size is None:
        raise ValueError("parent_chunk_size must be set to use chunk_text_hierarchical")
    if text == "":
        return [], []

    parent_config = ChunkingConfig(
        chunk_size=config.parent_chunk_size,
        chunk_overlap=0,
        strategy=config.strategy,
    )
    parent_drafts = chunk_text(text, parent_config)
    parent_drafts = _explain_drafts(
        parent_drafts,
        config=config,
        split_reason="parent_boundary",
        source_block_type="unknown",
    )

    child_config = ChunkingConfig(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        strategy=config.strategy,
    )

    shared_meta = config.as_metadata()
    child_drafts: list[ChunkDraft] = []
    child_index = 0

    for parent_draft in parent_drafts:
        raw_children = chunk_text(parent_draft.text, child_config)
        for rc in raw_children:
            child_drafts.append(
                ChunkDraft(
                    chunk_index=child_index,
                    text=rc.text,
                    char_start=parent_draft.char_start + rc.char_start,
                    char_end=parent_draft.char_start + rc.char_end,
                    metadata={
                        **rc.metadata,
                        **shared_meta,
                        "split_reason": rc.metadata["split_reason"],
                        "parent_chunk_index": parent_draft.chunk_index,
                    },
                    heading=rc.heading or parent_draft.heading,
                    parent_chunk_index=parent_draft.chunk_index,
                )
            )
            child_index += 1

    return parent_drafts, child_drafts


def get_chunk_template(template_id: str) -> ChunkTemplate:
    try:
        return CHUNK_TEMPLATES[template_id]
    except KeyError as exc:
        raise ValueError(f"Unknown chunk template '{template_id}'") from exc


def chunking_config_from_template(
    template_id: str,
    parameters: dict[str, Any] | None = None,
) -> ChunkingConfig:
    template = get_chunk_template(template_id)
    values = {**template.parameters, **(parameters or {})}
    allowed = set(template.parameters)
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f"Unknown chunk template parameters: {unknown}")
    strategy = values.pop("child_strategy", template.strategy)
    return ChunkingConfig(strategy=strategy, **values)


__all__ = [
    "CHUNK_TEMPLATES",
    "ChunkDraft",
    "ChunkTemplate",
    "ChunkingConfig",
    "chunk_text",
    "chunk_text_hierarchical",
    "chunking_config_from_template",
    "get_chunk_template",
]
