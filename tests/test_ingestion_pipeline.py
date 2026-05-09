from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.db.models import Base, Document, DocumentVersion, PipelineRun, PipelineRunItem
from ragrig.ingestion.pipeline import _select_parser, ingest_local_directory

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@contextmanager
def _create_session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def test_ingest_local_directory_creates_documents_versions_and_run_items(tmp_path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Guide\n\nAlpha\n", encoding="utf-8")
    (docs / "notes.txt").write_text("plain text\n", encoding="utf-8")
    (docs / "empty.txt").write_text("", encoding="utf-8")
    (docs / "ignored.bin").write_bytes(b"\x01\x02")

    with _create_session() as session:
        report = ingest_local_directory(
            session=session,
            knowledge_base_name="default",
            root_path=docs,
        )

        documents = session.scalars(select(Document).order_by(Document.uri)).all()
        versions = session.scalars(
            select(DocumentVersion).order_by(DocumentVersion.version_number)
        ).all()
        pipeline_run = session.scalars(select(PipelineRun)).one()
        run_items = session.scalars(select(PipelineRunItem).order_by(PipelineRunItem.status)).all()

    assert report.pipeline_run_id == pipeline_run.id
    assert report.created_documents == 4
    assert report.created_versions == 3
    assert report.skipped_count == 1
    assert report.failed_count == 0
    assert [Path(document.uri).name for document in documents] == [
        "empty.txt",
        "guide.md",
        "ignored.bin",
        "notes.txt",
    ]
    assert len(versions) == 3
    assert pipeline_run.status == "completed"
    assert pipeline_run.total_items == 4
    assert pipeline_run.success_count == 3
    assert pipeline_run.failure_count == 0
    assert sorted(item.status for item in run_items) == [
        "skipped",
        "success",
        "success",
        "success",
    ]
    skipped_item = next(item for item in run_items if item.status == "skipped")
    assert skipped_item.metadata_json["skip_reason"] == "unsupported_extension"


def test_ingest_local_directory_is_idempotent_for_unchanged_content_and_versions_on_change(
    tmp_path,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    file_path = docs / "guide.md"
    file_path.write_text("# Guide\n", encoding="utf-8")

    with _create_session() as session:
        first_report = ingest_local_directory(
            session=session,
            knowledge_base_name="default",
            root_path=docs,
        )
        second_report = ingest_local_directory(
            session=session,
            knowledge_base_name="default",
            root_path=docs,
        )

        file_path.write_text("# Guide\n\nUpdated\n", encoding="utf-8")
        third_report = ingest_local_directory(
            session=session,
            knowledge_base_name="default",
            root_path=docs,
        )

        versions = session.scalars(
            select(DocumentVersion).order_by(DocumentVersion.version_number)
        ).all()
        runs = session.scalars(select(PipelineRun).order_by(PipelineRun.started_at)).all()
        run_items = session.scalars(
            select(PipelineRunItem).order_by(PipelineRunItem.started_at)
        ).all()

    assert first_report.created_versions == 1
    assert second_report.created_versions == 0
    assert second_report.skipped_count == 1
    assert third_report.created_versions == 1
    assert [version.version_number for version in versions] == [1, 2]
    assert [run.status for run in runs] == ["completed", "completed", "completed"]
    assert [item.status for item in run_items] == ["success", "skipped", "success"]


def test_ingest_local_directory_records_file_level_failure_without_failing_entire_run(
    tmp_path,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "good.md").write_text("# Good\n", encoding="utf-8")
    bad_path = docs / "bad.txt"
    bad_path.write_bytes(b"\xff\xfe\xfd")

    with _create_session() as session:
        report = ingest_local_directory(
            session=session,
            knowledge_base_name="default",
            root_path=docs,
        )

        run = session.scalars(select(PipelineRun)).one()
        items = session.scalars(select(PipelineRunItem).order_by(PipelineRunItem.status)).all()
        documents = session.scalars(select(Document).order_by(Document.uri)).all()
        versions = session.scalars(select(DocumentVersion)).all()

    assert report.failed_count == 1
    assert report.created_documents == 2
    assert report.created_versions == 1
    assert run.status == "completed_with_failures"
    assert run.total_items == 2
    assert run.success_count == 1
    assert run.failure_count == 1
    assert sorted(item.status for item in items) == ["failed", "success"]
    failed_item = next(item for item in items if item.status == "failed")
    assert failed_item.error_message
    assert failed_item.metadata_json["file_name"] == "bad.txt"
    assert [Path(document.uri).name for document in documents] == ["bad.txt", "good.md"]
    assert len(versions) == 1


def test_ingest_skip_does_not_overwrite_existing_document_hash_or_metadata(tmp_path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    file_path = docs / "guide.md"
    file_path.write_text("# Guide\n", encoding="utf-8")

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="default",
            root_path=docs,
        )

        file_path.unlink()
        binary_path = docs / "guide.bin"
        binary_path.write_bytes(b"\x00\x01bad")

        ingest_local_directory(
            session=session,
            knowledge_base_name="default",
            root_path=docs,
        )

        document = session.scalars(select(Document).where(Document.uri == str(file_path))).one()
        version = session.scalars(
            select(DocumentVersion).where(DocumentVersion.document_id == document.id)
        ).one()

    assert document.content_hash == version.content_hash
    assert document.mime_type == "text/markdown"
    assert document.metadata_json["extension"] == ".md"


def test_select_parser_uses_markdown_parser_for_markdown_extensions() -> None:
    assert _select_parser(Path("guide.md")).parser_name == "markdown"
    assert _select_parser(Path("guide.markdown")).parser_name == "markdown"
    assert _select_parser(Path("notes.txt")).parser_name == "plaintext"


def test_ingest_local_directory_persists_parser_plugin_id_in_version_config(tmp_path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (docs / "notes.txt").write_text("hello\n", encoding="utf-8")

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="default",
            root_path=docs,
        )

        versions = session.scalars(
            select(DocumentVersion).order_by(DocumentVersion.parser_name.asc())
        ).all()

    assert [version.parser_config_json["plugin_id"] for version in versions] == [
        "parser.markdown",
        "parser.text",
    ]


def test_ingest_local_directory_returns_dry_run_report(tmp_path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (docs / "ignored.bin").write_bytes(b"\x00bad")

    with _create_session() as session:
        report = ingest_local_directory(
            session=session,
            knowledge_base_name="default",
            root_path=docs,
            dry_run=True,
        )

        assert session.scalars(select(PipelineRun)).all() == []

    assert report.pipeline_run_id == "dry-run"
    assert report.created_documents == 0
    assert report.created_versions == 0
    assert report.skipped_count == 2
    assert report.failed_count == 0


def test_ingest_local_directory_propagates_missing_root_path(sqlite_session, tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="scan root does not exist"):
        ingest_local_directory(
            session=sqlite_session,
            knowledge_base_name="default",
            root_path=tmp_path / "missing",
        )
