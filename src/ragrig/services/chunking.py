from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.chunkers import (
    CHUNK_TEMPLATES,
    ChunkDraft,
    chunk_text,
    chunk_text_hierarchical,
    chunking_config_from_template,
    get_chunk_template,
)
from ragrig.db.models import Chunk, Document, DocumentVersion, KnowledgeBase
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.repositories import create_audit_event
from ragrig.services.common import ServiceError
from ragrig.web_console import list_document_version_chunks

_ALLOWED_SPLIT_REASONS = {
    "heading_boundary",
    "manual_merge",
    "manual_split",
    "paragraph_boundary",
    "sentence_boundary",
    "window_boundary",
}


def _version_for_workspace(
    session: Session,
    *,
    document_version_id: str,
    workspace_id: uuid.UUID,
) -> tuple[DocumentVersion, Document, KnowledgeBase]:
    try:
        version_id = uuid.UUID(document_version_id)
    except ValueError as exc:
        raise ServiceError(
            status_code=404, content={"error": "document_version_not_found"}
        ) from exc
    row = session.execute(
        select(DocumentVersion, Document, KnowledgeBase)
        .join(Document, Document.id == DocumentVersion.document_id)
        .join(KnowledgeBase, KnowledgeBase.id == Document.knowledge_base_id)
        .where(DocumentVersion.id == version_id, KnowledgeBase.workspace_id == workspace_id)
    ).one_or_none()
    if row is None:
        raise ServiceError(status_code=404, content={"error": "document_version_not_found"})
    return row[0], row[1], row[2]


def _serialize_draft(draft: ChunkDraft, *, is_parent: bool = False) -> dict[str, Any]:
    return {
        "chunk_index": draft.chunk_index,
        "text": draft.text,
        "char_start": draft.char_start,
        "char_end": draft.char_end,
        "heading": draft.heading,
        "parent_chunk_index": draft.parent_chunk_index,
        "is_parent": is_parent,
        "metadata": draft.metadata,
        "split_explanation": draft.metadata.get("split_explanation"),
    }


def list_templates() -> dict[str, list[dict[str, Any]]]:
    return {"items": [template.as_dict() for template in CHUNK_TEMPLATES.values()]}


def preview(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    text: str | None,
    document_version_id: str | None,
    template_id: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    if (text is None) == (document_version_id is None):
        raise ServiceError(
            status_code=400,
            content={"error": "chunk_preview_requires_exactly_one_source"},
        )
    try:
        template = get_chunk_template(template_id)
        config = chunking_config_from_template(template_id, parameters)
    except (TypeError, ValueError) as exc:
        code = (
            "chunk_template_not_found"
            if "Unknown chunk template" in str(exc)
            else "invalid_chunk_parameters"
        )
        raise ServiceError(status_code=400, content={"error": code, "message": str(exc)}) from exc

    source_text = text
    if document_version_id is not None:
        version, _, _ = _version_for_workspace(
            session,
            document_version_id=document_version_id,
            workspace_id=workspace_id,
        )
        source_text = version.extracted_text
    assert source_text is not None

    if config.parent_chunk_size is not None:
        parents, children = chunk_text_hierarchical(source_text, config)
    else:
        parents, children = [], chunk_text(source_text, config)
    if len(parents) + len(children) > 10_000:
        raise ServiceError(status_code=400, content={"error": "chunk_preview_limit_exceeded"})
    return {
        "template": template.as_dict(),
        "parameters": config.as_metadata()["template_parameters"],
        "chunks": [_serialize_draft(draft) for draft in children],
        "parent_chunks": [_serialize_draft(draft, is_parent=True) for draft in parents],
    }


def review(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    document_version_id: str,
) -> dict[str, Any]:
    version, _, _ = _version_for_workspace(
        session,
        document_version_id=document_version_id,
        workspace_id=workspace_id,
    )
    items = list_document_version_chunks(
        session,
        document_version_id,
        workspace_id=workspace_id,
    )
    edit_supported = not any(item["metadata"].get("has_parent") for item in items)
    return {
        "items": items,
        "override": (version.metadata_json or {}).get("chunk_override"),
        "index_status": (version.metadata_json or {}).get(
            "chunk_index_status",
            {"status": "unknown", "reindex_required": False},
        ),
        "edit_supported": edit_supported,
        "edit_limitation": None if edit_supported else "parent_child_manual_override_unsupported",
    }


def _validate_drafts(source_text: str, drafts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not drafts or len(drafts) > 10_000:
        raise ServiceError(status_code=400, content={"error": "invalid_chunk_override_count"})
    normalized: list[dict[str, Any]] = []
    previous_start = -1
    for item in drafts:
        try:
            start = int(item["char_start"])
            end = int(item["char_end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ServiceError(status_code=400, content={"error": "invalid_chunk_range"}) from exc
        if start < 0 or end <= start or end > len(source_text) or start < previous_start:
            raise ServiceError(status_code=400, content={"error": "invalid_chunk_range"})
        reason = str(item.get("split_reason") or "manual_split")
        if reason not in _ALLOWED_SPLIT_REASONS:
            raise ServiceError(status_code=400, content={"error": "invalid_split_reason"})
        normalized.append(
            {
                "char_start": start,
                "char_end": end,
                "split_reason": reason,
                "heading": item.get("heading"),
                "source_block_type": item.get("source_block_type") or "unknown",
                "source_block_id": item.get("source_block_id"),
                "section_id": item.get("section_id"),
                "table_id": item.get("table_id"),
                "parser_page_number": item.get("parser_page_number"),
            }
        )
        previous_start = start
    return normalized


def save_override(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    document_version_id: str,
    actor: str | None,
    reason: str,
    template_id: str,
    template_parameters: dict[str, Any],
    drafts: list[dict[str, Any]],
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    version, document, knowledge_base = _version_for_workspace(
        session,
        document_version_id=document_version_id,
        workspace_id=workspace_id,
    )
    if session.scalar(
        select(Chunk.id).where(
            Chunk.document_version_id == version.id,
            Chunk.parent_chunk_id.is_not(None),
        )
    ):
        raise ServiceError(
            status_code=409,
            content={"error": "parent_child_manual_override_unsupported"},
        )
    try:
        template = get_chunk_template(template_id)
        selected_config = chunking_config_from_template(template_id, template_parameters)
    except (TypeError, ValueError) as exc:
        raise ServiceError(
            status_code=400,
            content={"error": "invalid_chunk_parameters", "message": str(exc)},
        ) from exc
    if selected_config.parent_chunk_size is not None:
        raise ServiceError(
            status_code=409,
            content={"error": "parent_child_manual_override_unsupported"},
        )
    normalized = _validate_drafts(version.extracted_text, drafts)
    old_override = (version.metadata_json or {}).get("chunk_override")
    revision = int(old_override.get("revision", 0)) + 1 if isinstance(old_override, dict) else 1
    now = datetime.now(timezone.utc).isoformat()
    resolved_parameters = selected_config.as_metadata()["template_parameters"]
    override = {
        "revision": revision,
        "status": "pending_reindex",
        "reindex_required": True,
        "actor": actor,
        "reason": reason,
        "updated_at": now,
        "template_id": template.id,
        "template_version": template.version,
        "chunk_strategy": template.strategy,
        "template_parameters": resolved_parameters,
        "chunks": normalized,
        "operations": operations[-100:],
    }
    version.metadata_json = {
        **(version.metadata_json or {}),
        "chunk_override": override,
        "chunk_template_config": {
            "template_id": template.id,
            "template_version": template.version,
            "parameters": resolved_parameters,
        },
        "chunk_index_status": {
            "status": "stale",
            "reindex_required": True,
            "reason": "manual_chunk_override_pending",
            "updated_at": now,
        },
    }
    create_audit_event(
        session,
        event_type="chunk_override_save",
        actor=actor,
        workspace_id=workspace_id,
        knowledge_base_id=knowledge_base.id,
        document_id=document.id,
        payload_json={
            "document_version_id": str(version.id),
            "revision": revision,
            "reason": reason,
            "before_chunk_count": len(version.chunks),
            "after_chunk_count": len(normalized),
            "operation_count": len(operations),
            "operations": operations[-100:],
        },
    )
    session.commit()
    return {"override": override, "index_status": version.metadata_json["chunk_index_status"]}


def reset_override(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    document_version_id: str,
    actor: str | None,
    reason: str,
    template_id: str,
    template_parameters: dict[str, Any],
) -> dict[str, Any]:
    version, document, knowledge_base = _version_for_workspace(
        session,
        document_version_id=document_version_id,
        workspace_id=workspace_id,
    )
    try:
        template = get_chunk_template(template_id)
        selected_config = chunking_config_from_template(template_id, template_parameters)
    except (TypeError, ValueError) as exc:
        raise ServiceError(
            status_code=400,
            content={"error": "invalid_chunk_parameters", "message": str(exc)},
        ) from exc
    metadata = dict(version.metadata_json or {})
    previous = metadata.pop("chunk_override", None)
    now = datetime.now(timezone.utc).isoformat()
    metadata["chunk_index_status"] = {
        "status": "stale",
        "reindex_required": True,
        "reason": "chunk_override_reset_pending",
        "updated_at": now,
    }
    metadata["chunk_template_config"] = {
        "template_id": template.id,
        "template_version": template.version,
        "parameters": selected_config.as_metadata()["template_parameters"],
    }
    version.metadata_json = metadata
    create_audit_event(
        session,
        event_type="chunk_override_reset",
        actor=actor,
        workspace_id=workspace_id,
        knowledge_base_id=knowledge_base.id,
        document_id=document.id,
        payload_json={
            "document_version_id": str(version.id),
            "reason": reason,
            "template_id": template.id,
            "previous_revision": previous.get("revision") if isinstance(previous, dict) else None,
        },
    )
    session.commit()
    return {"override": None, "index_status": metadata["chunk_index_status"]}


def reindex_override(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    document_version_id: str,
    actor: str | None,
) -> dict[str, Any]:
    version, document, knowledge_base = _version_for_workspace(
        session,
        document_version_id=document_version_id,
        workspace_id=workspace_id,
    )
    report = index_knowledge_base(
        session=session,
        knowledge_base_name=knowledge_base.name,
        workspace_id=workspace_id,
        force_reindex=True,
        document_version_ids={version.id},
    )
    create_audit_event(
        session,
        event_type="chunk_override_reindex",
        actor=actor,
        workspace_id=workspace_id,
        knowledge_base_id=knowledge_base.id,
        document_id=document.id,
        run_id=report.pipeline_run_id,
        payload_json={
            "document_version_id": str(version.id),
            "indexed_count": report.indexed_count,
            "chunk_count": report.chunk_count,
        },
    )
    session.commit()
    return {
        "pipeline_run_id": str(report.pipeline_run_id),
        "indexed_count": report.indexed_count,
        "chunk_count": report.chunk_count,
        "embedding_count": report.embedding_count,
    }


__all__ = [
    "list_templates",
    "preview",
    "reindex_override",
    "reset_override",
    "review",
    "save_override",
]
