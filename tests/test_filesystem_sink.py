"""Tests for the filesystem export sink (JSONL, Markdown, NFS path)."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ragrig.db.models import Base, DocumentVersion
from ragrig.plugins.sinks.filesystem.connector import export_to_filesystem
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


def _seed(session):
    kb = get_or_create_knowledge_base(session, "test-kb")
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
        uri="test-kb/doc.md",
        content_hash="abc123",
        mime_type="text/markdown",
        metadata_json={},
    )
    version = DocumentVersion(
        document_id=doc.id,
        version_number=1,
        content_hash="abc123",
        parser_name="markdown",
        parser_config_json={},
        extracted_text="Hello world",
        metadata_json={},
    )
    session.add(version)
    session.commit()
    return kb


def test_dry_run_returns_planned_files(mem_session, tmp_path):
    _seed(mem_session)
    report = export_to_filesystem(
        mem_session,
        knowledge_base_name="test-kb",
        base_path=str(tmp_path),
        format="both",
        dry_run=True,
    )
    assert report.dry_run is True
    assert len(report.planned_files) > 0
    assert report.written_files == []
    assert not (tmp_path / "test-kb").exists()


def test_jsonl_export_writes_files(mem_session, tmp_path):
    _seed(mem_session)
    report = export_to_filesystem(
        mem_session,
        knowledge_base_name="test-kb",
        base_path=str(tmp_path),
        format="jsonl",
    )
    assert report.dry_run is False
    assert len(report.written_files) >= 2

    docs_path = tmp_path / "test-kb" / "documents.jsonl"
    assert docs_path.exists()
    rows = [json.loads(line) for line in docs_path.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["document_uri"] == "test-kb/doc.md"


def test_markdown_export_writes_summary(mem_session, tmp_path):
    _seed(mem_session)
    report = export_to_filesystem(
        mem_session,
        knowledge_base_name="test-kb",
        base_path=str(tmp_path),
        format="markdown",
    )
    summary_path = tmp_path / "test-kb" / "export_summary.md"
    assert summary_path.exists()
    content = summary_path.read_text()
    assert "test-kb" in content
    assert "Documents:" in content


def test_both_format_writes_all_files(mem_session, tmp_path):
    _seed(mem_session)
    report = export_to_filesystem(
        mem_session,
        knowledge_base_name="test-kb",
        base_path=str(tmp_path),
        format="both",
    )
    out = tmp_path / "test-kb"
    assert (out / "chunks.jsonl").exists()
    assert (out / "documents.jsonl").exists()
    assert (out / "export_summary.md").exists()


def test_overwrite_false_skips_existing_files(mem_session, tmp_path):
    _seed(mem_session)
    export_to_filesystem(
        mem_session,
        knowledge_base_name="test-kb",
        base_path=str(tmp_path),
        format="jsonl",
    )
    docs_path = tmp_path / "test-kb" / "documents.jsonl"
    original_mtime = docs_path.stat().st_mtime

    report2 = export_to_filesystem(
        mem_session,
        knowledge_base_name="test-kb",
        base_path=str(tmp_path),
        format="jsonl",
        overwrite=False,
    )
    assert report2.written_files == []
    assert docs_path.stat().st_mtime == original_mtime


def test_invalid_knowledge_base_raises(mem_session, tmp_path):
    with pytest.raises(ValueError, match="was not found"):
        export_to_filesystem(
            mem_session,
            knowledge_base_name="nonexistent-kb",
            base_path=str(tmp_path),
        )


def test_invalid_format_raises(mem_session, tmp_path):
    _seed(mem_session)
    with pytest.raises(ValueError, match="format must be"):
        export_to_filesystem(
            mem_session,
            knowledge_base_name="test-kb",
            base_path=str(tmp_path),
            format="csv",
        )


def test_nfs_path_creates_nested_dirs(mem_session, tmp_path):
    nfs_mount = tmp_path / "nfs" / "share" / "ragrig"
    _seed(mem_session)
    report = export_to_filesystem(
        mem_session,
        knowledge_base_name="test-kb",
        base_path=str(nfs_mount),
        format="jsonl",
    )
    assert (nfs_mount / "test-kb" / "documents.jsonl").exists()
    assert report.base_path == str(nfs_mount)
