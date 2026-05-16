"""Filesystem sink: write knowledge-base exports to a local path (or NFS mount).

Supports JSONL (one JSON record per line) and Markdown summary formats.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.db.models import Chunk, Document, DocumentVersion
from ragrig.repositories import (
    get_knowledge_base_by_name,
    list_latest_document_versions,
)


@dataclass(frozen=True)
class FilesystemExportReport:
    base_path: str
    knowledge_base: str
    format: str
    dry_run: bool
    planned_files: list[str]
    written_files: list[str]
    document_count: int
    chunk_count: int


def export_to_filesystem(
    session: Session,
    *,
    knowledge_base_name: str,
    base_path: str,
    format: str = "jsonl",
    overwrite: bool = True,
    dry_run: bool = False,
) -> FilesystemExportReport:
    """Export a knowledge base to local filesystem files (JSONL and/or Markdown).

    Args:
        base_path: Directory to write files into (may be an NFS mount point).
        format: One of "jsonl", "markdown", or "both".
        overwrite: If False, skip files that already exist.
        dry_run: Plan the export without writing any files.
    """
    if format not in ("jsonl", "markdown", "both"):
        raise ValueError(f"format must be 'jsonl', 'markdown', or 'both'; got {format!r}")

    knowledge_base = get_knowledge_base_by_name(session, knowledge_base_name)
    if knowledge_base is None:
        raise ValueError(f"Knowledge base '{knowledge_base_name}' was not found")

    versions = list_latest_document_versions(session, knowledge_base_id=knowledge_base.id)
    documents = [v.document for v in versions]
    chunks = list(
        session.scalars(
            select(Chunk)
            .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
            .join(Document, Document.id == DocumentVersion.document_id)
            .where(Document.knowledge_base_id == knowledge_base.id)
            .order_by(Document.uri, Chunk.chunk_index)
        )
    )

    out_dir = Path(base_path) / knowledge_base_name
    planned: list[str] = []
    written: list[str] = []

    def _plan(filename: str) -> Path:
        p = out_dir / filename
        planned.append(str(p))
        return p

    chunks_jsonl_path = _plan("chunks.jsonl") if format in ("jsonl", "both") else None
    docs_jsonl_path = _plan("documents.jsonl") if format in ("jsonl", "both") else None
    summary_md_path = _plan("export_summary.md") if format in ("markdown", "both") else None

    if dry_run:
        return FilesystemExportReport(
            base_path=base_path,
            knowledge_base=knowledge_base_name,
            format=format,
            dry_run=True,
            planned_files=planned,
            written_files=[],
            document_count=len(documents),
            chunk_count=len(chunks),
        )

    out_dir.mkdir(parents=True, exist_ok=True)

    def _should_write(path: Path) -> bool:
        return overwrite or not path.exists()

    if chunks_jsonl_path is not None and _should_write(chunks_jsonl_path):
        lines = [
            json.dumps(
                {
                    "chunk_id": str(chunk.id),
                    "document_version_id": str(chunk.document_version_id),
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "page_number": chunk.page_number,
                    "heading": chunk.heading,
                    "metadata": chunk.metadata_json,
                },
                sort_keys=True,
            )
            for chunk in chunks
        ]
        chunks_jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append(str(chunks_jsonl_path))

    if docs_jsonl_path is not None and _should_write(docs_jsonl_path):
        lines = [
            json.dumps(
                {
                    "document_id": str(doc.id),
                    "knowledge_base_id": str(doc.knowledge_base_id),
                    "document_uri": doc.uri,
                    "content_hash": doc.content_hash,
                    "mime_type": doc.mime_type,
                },
                sort_keys=True,
            )
            for doc in documents
        ]
        docs_jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append(str(docs_jsonl_path))

    if summary_md_path is not None and _should_write(summary_md_path):
        md = _build_markdown_summary(
            knowledge_base_name=knowledge_base_name,
            base_path=base_path,
            document_count=len(documents),
            chunk_count=len(chunks),
            exported_at=datetime.now(timezone.utc).isoformat(),
        )
        summary_md_path.write_text(md, encoding="utf-8")
        written.append(str(summary_md_path))

    return FilesystemExportReport(
        base_path=base_path,
        knowledge_base=knowledge_base_name,
        format=format,
        dry_run=False,
        planned_files=planned,
        written_files=written,
        document_count=len(documents),
        chunk_count=len(chunks),
    )


def _build_markdown_summary(
    *,
    knowledge_base_name: str,
    base_path: str,
    document_count: int,
    chunk_count: int,
    exported_at: str,
) -> str:
    return "\n".join(
        [
            "# Filesystem Export Summary",
            "",
            f"- Knowledge base: `{knowledge_base_name}`",
            f"- Base path: `{base_path}`",
            f"- Documents: {document_count}",
            f"- Chunks: {chunk_count}",
            f"- Exported at: {exported_at}",
            "",
            "## Files",
            "",
            "| File | Description |",
            "|------|-------------|",
            "| `chunks.jsonl` | One JSON record per chunk |",
            "| `documents.jsonl` | One JSON record per document |",
            "| `export_summary.md` | This file |",
        ]
    )


__all__ = ["FilesystemExportReport", "export_to_filesystem"]
