"""Unit tests for the DuckDB analytics sink connector."""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ragrig.db.models import Base, Chunk, DocumentVersion, Embedding
from ragrig.plugins.sinks.analytics.connector import (
    AnalyticsExportReport,
    AnalyticsSinkUnavailableError,
    export_to_duckdb,
)
from ragrig.repositories import (
    get_or_create_document,
    get_or_create_knowledge_base,
    get_or_create_source,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def mem_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=True, autocommit=False, expire_on_commit=False)
    with factory() as session:
        yield session


def _seed(session, kb_name: str = "test-kb", chunk_count: int = 2):
    kb = get_or_create_knowledge_base(session, kb_name)
    source = get_or_create_source(
        session,
        knowledge_base_id=kb.id,
        kind="local_directory",
        uri="/tmp/test-kb",
        config_json={"root_path": "/tmp/test-kb"},
    )
    doc, _ = get_or_create_document(
        session,
        knowledge_base_id=kb.id,
        source_id=source.id,
        uri="test-kb/doc.txt",
        content_hash="deadbeef",
        mime_type="text/plain",
        metadata_json={},
    )
    dv = DocumentVersion(
        document_id=doc.id,
        version_number=1,
        content_hash="deadbeef",
        parser_name="text",
        parser_config_json={},
        extracted_text="chunk one\nchunk two",
        metadata_json={},
    )
    session.add(dv)
    session.flush()

    chunks = []
    for i in range(chunk_count):
        chunk = Chunk(
            id=uuid.uuid4(),
            document_version_id=dv.id,
            chunk_index=i,
            text=f"chunk text {i}",
            metadata_json={"index": i},
        )
        session.add(chunk)
        chunks.append(chunk)
    session.flush()

    return kb, dv, chunks


def _seed_embeddings(session, chunks):
    embs = []
    for chunk in chunks:
        emb = Embedding(
            id=uuid.uuid4(),
            chunk_id=chunk.id,
            provider="test",
            model="test-model",
            dimensions=3,
            embedding=[0.1, 0.2, 0.3],
            metadata_json={},
        )
        session.add(emb)
        embs.append(emb)
    session.flush()
    return embs


class TestDryRun:
    def test_dry_run_returns_counts_without_writing(self, mem_session) -> None:
        _seed(mem_session, chunk_count=2)
        report = export_to_duckdb(
            mem_session,
            knowledge_base_name="test-kb",
            db_path=":memory:",
            dry_run=True,
        )
        assert report.dry_run is True
        assert report.document_count == 1
        assert report.chunk_count == 2
        assert report.tables_written == []

    def test_dry_run_embedding_count_when_include_embeddings(self, mem_session) -> None:
        _, _, chunks = _seed(mem_session, chunk_count=3)
        _seed_embeddings(mem_session, chunks)
        report = export_to_duckdb(
            mem_session,
            knowledge_base_name="test-kb",
            db_path=":memory:",
            include_embeddings=True,
            dry_run=True,
        )
        assert report.embedding_count == 3
        assert report.tables_written == []


class TestWrite:
    def test_exports_documents_and_chunks_tables(self, mem_session) -> None:
        _seed(mem_session, chunk_count=2)
        report = export_to_duckdb(
            mem_session,
            knowledge_base_name="test-kb",
            db_path=":memory:",
        )
        assert report.dry_run is False
        assert report.document_count == 1
        assert report.chunk_count == 2
        assert "documents" in report.tables_written
        assert "chunks" in report.tables_written
        assert "embeddings" not in report.tables_written

    def test_exports_embeddings_table_when_requested(self, mem_session) -> None:
        _, _, chunks = _seed(mem_session, chunk_count=2)
        _seed_embeddings(mem_session, chunks)
        report = export_to_duckdb(
            mem_session,
            knowledge_base_name="test-kb",
            db_path=":memory:",
            include_embeddings=True,
        )
        assert "embeddings" in report.tables_written
        assert report.embedding_count == 2

    def test_table_prefix_applied(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        report = export_to_duckdb(
            mem_session,
            knowledge_base_name="test-kb",
            db_path=":memory:",
            table_prefix="ragrig_",
        )
        assert "ragrig_documents" in report.tables_written
        assert "ragrig_chunks" in report.tables_written

    def test_roundtrip_query_returns_correct_rows(self, mem_session, tmp_path) -> None:
        import duckdb

        _seed(mem_session, chunk_count=3)
        db_file = str(tmp_path / "kb.duckdb")
        export_to_duckdb(
            mem_session,
            knowledge_base_name="test-kb",
            db_path=db_file,
        )
        con = duckdb.connect(db_file, read_only=True)
        chunk_count = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        doc_count = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        con.close()

        assert chunk_count == 3
        assert doc_count == 1

    def test_idempotent_export_overwrites_existing_table(self, mem_session, tmp_path) -> None:
        _seed(mem_session, chunk_count=2)
        db_file = str(tmp_path / "kb.duckdb")
        export_to_duckdb(mem_session, knowledge_base_name="test-kb", db_path=db_file)
        report2 = export_to_duckdb(mem_session, knowledge_base_name="test-kb", db_path=db_file)
        assert report2.chunk_count == 2


class TestErrorCases:
    def test_raises_for_missing_knowledge_base(self, mem_session) -> None:
        with pytest.raises(ValueError, match="was not found"):
            export_to_duckdb(
                mem_session,
                knowledge_base_name="nonexistent-kb",
                db_path=":memory:",
            )

    def test_raises_unavailable_error_when_duckdb_not_installed(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        with patch.dict("sys.modules", {"duckdb": None}):
            with pytest.raises(AnalyticsSinkUnavailableError, match="duckdb"):
                export_to_duckdb(
                    mem_session,
                    knowledge_base_name="test-kb",
                    db_path=":memory:",
                )


class TestReport:
    def test_report_fields_match_input(self, mem_session) -> None:
        _seed(mem_session, chunk_count=1)
        report = export_to_duckdb(
            mem_session,
            knowledge_base_name="test-kb",
            db_path=":memory:",
        )
        assert isinstance(report, AnalyticsExportReport)
        assert report.knowledge_base == "test-kb"
        assert report.db_path == ":memory:"

    def test_empty_kb_exports_zero_rows(self, mem_session) -> None:
        get_or_create_knowledge_base(mem_session, "empty-kb")
        report = export_to_duckdb(
            mem_session,
            knowledge_base_name="empty-kb",
            db_path=":memory:",
        )
        assert report.document_count == 0
        assert report.chunk_count == 0
        assert report.tables_written == ["documents", "chunks"]
