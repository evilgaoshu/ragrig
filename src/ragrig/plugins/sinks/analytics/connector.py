"""Analytics sink: export knowledge-base chunks to a DuckDB analytical database.

The exported schema has three tables:
  - ``documents``   — one row per document (URI, content_hash, parser, timestamps)
  - ``chunks``      — one row per chunk (text, chunk_index, metadata JSON)
  - ``embeddings``  — one row per embedding vector (provider, model, dimensions, vector)

DuckDB is an optional dependency.  When not installed the connector raises
``AnalyticsSinkUnavailableError`` so callers can degrade gracefully.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.db.models import Chunk, Document, Embedding
from ragrig.repositories import (
    get_knowledge_base_by_name,
    list_latest_document_versions,
)


class AnalyticsSinkUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class AnalyticsExportReport:
    db_path: str
    knowledge_base: str
    dry_run: bool
    document_count: int
    chunk_count: int
    embedding_count: int
    tables_written: list[str]


def _ensure_duckdb() -> Any:
    try:
        import duckdb  # type: ignore[import-untyped]

        return duckdb
    except ImportError as exc:
        raise AnalyticsSinkUnavailableError(
            "duckdb is not installed; install it with: pip install duckdb"
        ) from exc


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def export_to_duckdb(
    session: Session,
    *,
    knowledge_base_name: str,
    db_path: str,
    table_prefix: str = "",
    include_embeddings: bool = False,
    dry_run: bool = False,
) -> AnalyticsExportReport:
    """Export a knowledge base to a DuckDB file.

    Args:
        db_path: Path for the DuckDB database file (e.g. ``/data/kb.duckdb``).
            Use ``:memory:`` for an in-memory database (useful in tests).
        table_prefix: Optional prefix for all table names (e.g. ``"ragrig_"``).
        include_embeddings: When True, also export the embeddings table.
        dry_run: Plan the export without writing anything; returns counts only.
    """
    knowledge_base = get_knowledge_base_by_name(session, knowledge_base_name)
    if knowledge_base is None:
        raise ValueError(f"Knowledge base '{knowledge_base_name}' was not found")

    versions = list_latest_document_versions(session, knowledge_base_id=knowledge_base.id)

    doc_rows: list[dict[str, Any]] = []
    chunk_rows: list[dict[str, Any]] = []
    embedding_rows: list[dict[str, Any]] = []

    for dv in versions:
        doc: Document = dv.document
        doc_rows.append(
            {
                "document_id": str(doc.id),
                "document_version_id": str(dv.id),
                "uri": doc.uri,
                "content_hash": dv.content_hash,
                "parser_name": dv.parser_name,
                "version_number": dv.version_number,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
                "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
            }
        )

        chunks_q = (
            select(Chunk).where(Chunk.document_version_id == dv.id).order_by(Chunk.chunk_index)
        )
        chunks: list[Chunk] = list(session.scalars(chunks_q))

        for chunk in chunks:
            chunk_rows.append(
                {
                    "chunk_id": str(chunk.id),
                    "document_id": str(doc.id),
                    "document_version_id": str(dv.id),
                    "document_uri": doc.uri,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "metadata": json.dumps(chunk.metadata_json or {}),
                    "created_at": chunk.created_at.isoformat() if chunk.created_at else None,
                }
            )

            if include_embeddings:
                embs_q = select(Embedding).where(Embedding.chunk_id == chunk.id)
                for emb in session.scalars(embs_q):
                    vector = emb.embedding
                    if hasattr(vector, "tolist"):
                        vector = vector.tolist()
                    embedding_rows.append(
                        {
                            "embedding_id": str(emb.id),
                            "chunk_id": str(chunk.id),
                            "document_id": str(doc.id),
                            "provider": emb.provider,
                            "model": emb.model,
                            "dimensions": emb.dimensions,
                            "vector": json.dumps(vector),
                        }
                    )

    if dry_run:
        return AnalyticsExportReport(
            db_path=db_path,
            knowledge_base=knowledge_base_name,
            dry_run=True,
            document_count=len(doc_rows),
            chunk_count=len(chunk_rows),
            embedding_count=len(embedding_rows),
            tables_written=[],
        )

    duckdb = _ensure_duckdb()
    con = duckdb.connect(db_path)
    tables_written: list[str] = []

    try:
        _write_documents_table(con, doc_rows, prefix=table_prefix)
        tables_written.append(f"{table_prefix}documents")

        _write_chunks_table(con, chunk_rows, prefix=table_prefix)
        tables_written.append(f"{table_prefix}chunks")

        if include_embeddings:
            _write_embeddings_table(con, embedding_rows, prefix=table_prefix)
            tables_written.append(f"{table_prefix}embeddings")
    finally:
        con.close()

    return AnalyticsExportReport(
        db_path=db_path,
        knowledge_base=knowledge_base_name,
        dry_run=False,
        document_count=len(doc_rows),
        chunk_count=len(chunk_rows),
        embedding_count=len(embedding_rows),
        tables_written=tables_written,
    )


def _write_documents_table(con: Any, rows: list[dict[str, Any]], prefix: str) -> None:
    table = f"{prefix}documents"
    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(f"""
        CREATE TABLE {table} (
            document_id       VARCHAR PRIMARY KEY,
            document_version_id VARCHAR NOT NULL,
            uri               VARCHAR NOT NULL,
            content_hash      VARCHAR,
            parser_name       VARCHAR,
            version_number    INTEGER,
            created_at        VARCHAR,
            updated_at        VARCHAR
        )
    """)
    for row in rows:
        con.execute(
            f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                row["document_id"],
                row["document_version_id"],
                row["uri"],
                row["content_hash"],
                row["parser_name"],
                row["version_number"],
                row["created_at"],
                row["updated_at"],
            ],
        )


def _write_chunks_table(con: Any, rows: list[dict[str, Any]], prefix: str) -> None:
    table = f"{prefix}chunks"
    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(f"""
        CREATE TABLE {table} (
            chunk_id            VARCHAR PRIMARY KEY,
            document_id         VARCHAR NOT NULL,
            document_version_id VARCHAR NOT NULL,
            document_uri        VARCHAR NOT NULL,
            chunk_index         INTEGER NOT NULL,
            text                VARCHAR,
            metadata            VARCHAR,
            created_at          VARCHAR
        )
    """)
    for row in rows:
        con.execute(
            f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                row["chunk_id"],
                row["document_id"],
                row["document_version_id"],
                row["document_uri"],
                row["chunk_index"],
                row["text"],
                row["metadata"],
                row["created_at"],
            ],
        )


def _write_embeddings_table(con: Any, rows: list[dict[str, Any]], prefix: str) -> None:
    table = f"{prefix}embeddings"
    con.execute(f"DROP TABLE IF EXISTS {table}")
    con.execute(f"""
        CREATE TABLE {table} (
            embedding_id VARCHAR PRIMARY KEY,
            chunk_id     VARCHAR NOT NULL,
            document_id  VARCHAR NOT NULL,
            provider     VARCHAR,
            model        VARCHAR,
            dimensions   INTEGER,
            vector       VARCHAR
        )
    """)
    for row in rows:
        con.execute(
            f"INSERT INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                row["embedding_id"],
                row["chunk_id"],
                row["document_id"],
                row["provider"],
                row["model"],
                row["dimensions"],
                row["vector"],
            ],
        )
