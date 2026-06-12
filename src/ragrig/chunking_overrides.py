from __future__ import annotations

from hashlib import sha256
from typing import Any

from ragrig.chunkers import ChunkDraft, ChunkingConfig, chunking_config_from_template

OVERRIDE_METADATA_KEY = "chunk_override"
INDEX_STATUS_METADATA_KEY = "chunk_index_status"
TEMPLATE_CONFIG_METADATA_KEY = "chunk_template_config"

_MANUAL_REASONS = {"manual_merge", "manual_split"}


def override_drafts(
    source_text: str,
    document_version_metadata: dict[str, Any],
    config: ChunkingConfig,
) -> list[ChunkDraft] | None:
    override = document_version_metadata.get(OVERRIDE_METADATA_KEY)
    if not isinstance(override, dict):
        return None
    chunks = override.get("chunks")
    if not isinstance(chunks, list):
        return None

    shared = config.as_metadata()
    for key in (
        "template_id",
        "template_version",
        "chunk_strategy",
        "template_parameters",
    ):
        if override.get(key) is not None:
            shared[
                {
                    "template_id": "chunk_template_id",
                    "template_version": "chunk_template_version",
                }.get(key, key)
            ] = override[key]
    drafts: list[ChunkDraft] = []
    for index, item in enumerate(chunks):
        if not isinstance(item, dict):
            continue
        char_start = int(item["char_start"])
        char_end = int(item["char_end"])
        text = source_text[char_start:char_end]
        split_reason = str(item.get("split_reason") or "manual_split")
        if split_reason not in _MANUAL_REASONS:
            split_reason = "manual_split"
        source_block_type = item.get("source_block_type") or "unknown"
        source_block_id = (
            item.get("source_block_id")
            or sha256(f"{source_block_type}:{char_start}:{char_end}".encode("utf-8")).hexdigest()[
                :20
            ]
        )
        metadata = {
            **shared,
            "chunk_hash": sha256(text.encode("utf-8")).hexdigest(),
            "text_length": len(text),
            "split_reason": split_reason,
            "split_explanation": (
                f"Manual override revision {override.get('revision', 1)} applied {split_reason}."
            ),
            "char_start": char_start,
            "char_end": char_end,
            "source_block_type": source_block_type,
            "source_block_id": source_block_id,
            "manual_override_revision": int(override.get("revision", 1)),
            "manual_override_actor": override.get("actor"),
        }
        for key in ("section_id", "table_id", "parser_page_number"):
            if item.get(key) is not None:
                metadata[key] = item[key]
        heading = item.get("heading")
        if heading:
            metadata["heading"] = heading
        drafts.append(
            ChunkDraft(
                chunk_index=index,
                text=text,
                char_start=char_start,
                char_end=char_end,
                metadata=metadata,
                heading=heading,
            )
        )
    return drafts


def override_revision(document_version_metadata: dict[str, Any]) -> int | None:
    override = document_version_metadata.get(OVERRIDE_METADATA_KEY)
    if not isinstance(override, dict):
        return None
    return int(override.get("revision", 1))


def configured_chunking(
    document_version_metadata: dict[str, Any],
    fallback: ChunkingConfig,
) -> ChunkingConfig:
    configured = document_version_metadata.get(TEMPLATE_CONFIG_METADATA_KEY)
    if not isinstance(configured, dict):
        return fallback
    try:
        return chunking_config_from_template(
            str(configured["template_id"]),
            configured.get("parameters") or {},
        )
    except (KeyError, TypeError, ValueError):
        return fallback


def mark_index_current(
    document_version_metadata: dict[str, Any],
    *,
    indexed_at: str,
) -> dict[str, Any]:
    metadata = dict(document_version_metadata)
    metadata[INDEX_STATUS_METADATA_KEY] = {
        "status": "current",
        "reindex_required": False,
        "indexed_at": indexed_at,
    }
    override = metadata.get(OVERRIDE_METADATA_KEY)
    if isinstance(override, dict):
        metadata[OVERRIDE_METADATA_KEY] = {
            **override,
            "status": "applied",
            "reindex_required": False,
            "indexed_at": indexed_at,
        }
    return metadata


__all__ = [
    "INDEX_STATUS_METADATA_KEY",
    "OVERRIDE_METADATA_KEY",
    "TEMPLATE_CONFIG_METADATA_KEY",
    "configured_chunking",
    "mark_index_current",
    "override_drafts",
    "override_revision",
]
