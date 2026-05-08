from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.chunkers import ChunkingConfig, chunk_text
from ragrig.db.models import Base, Chunk, DocumentVersion, Embedding, PipelineRun, PipelineRunItem
from ragrig.embeddings import DeterministicEmbeddingProvider, EmbeddingResult
from ragrig.indexing.pipeline import (
    _embedding_provider_profile,
    _mirror_version_index,
    _replace_version_index,
    _version_already_indexed,
    index_knowledge_base,
)
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.vectorstore.base import VectorCollection, VectorCollectionStatus, VectorEmbeddingRecord


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


def test_chunk_text_splits_text_with_overlap_and_metadata() -> None:
    chunks = chunk_text(
        "abcdefghij",
        ChunkingConfig(chunk_size=4, chunk_overlap=1),
    )

    assert [chunk.text for chunk in chunks] == ["abcd", "defg", "ghij"]
    assert [(chunk.char_start, chunk.char_end) for chunk in chunks] == [
        (0, 4),
        (3, 7),
        (6, 10),
    ]
    assert all(chunk.metadata["chunker"] == "char_window_v1" for chunk in chunks)
    assert all(chunk.metadata["chunk_hash"] for chunk in chunks)


def test_deterministic_embedding_provider_returns_stable_dimensions() -> None:
    provider = DeterministicEmbeddingProvider(dimensions=8)

    first = provider.embed_text("alpha beta gamma")
    second = provider.embed_text("alpha beta gamma")

    assert first.provider == "deterministic-local"
    assert first.model == "hash-8d"
    assert first.dimensions == 8
    assert len(first.vector) == 8
    assert first.vector == second.vector


def test_embedding_provider_profile_requires_model_name() -> None:
    class NoModelProvider:
        provider_name = "missing-model"

    with pytest.raises(ValueError, match="embedding provider must expose a model name"):
        _embedding_provider_profile(NoModelProvider())


def test_index_knowledge_base_resolves_embedding_provider_from_registry(
    tmp_path, monkeypatch
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("alpha beta gamma delta", encoding="utf-8")

    calls: list[tuple[str, dict[str, int]]] = []

    class FakeRegistry:
        def get(self, name: str, **config):
            calls.append((name, config))
            return DeterministicEmbeddingProvider(dimensions=config["dimensions"])

    monkeypatch.setattr("ragrig.indexing.pipeline.get_provider_registry", lambda: FakeRegistry())

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )

        report = index_knowledge_base(session=session, knowledge_base_name="fixture-local")

    assert report.indexed_count == 1
    assert calls == [("deterministic-local", {"dimensions": 8})]


def test_index_knowledge_base_creates_chunks_embeddings_and_pipeline_items(tmp_path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text(
        "# Guide\n\nAlpha beta gamma delta epsilon zeta eta theta\n",
        encoding="utf-8",
    )
    (docs / "notes.txt").write_text(
        "One two three four five six seven eight nine ten\n",
        encoding="utf-8",
    )

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )

        report = index_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            chunk_size=18,
            chunk_overlap=4,
        )

        chunks = session.scalars(
            select(Chunk).order_by(Chunk.document_version_id, Chunk.chunk_index)
        ).all()
        embeddings = session.scalars(select(Embedding).order_by(Embedding.chunk_id)).all()
        run = session.scalars(
            select(PipelineRun).where(PipelineRun.run_type == "chunk_embedding")
        ).one()
        items = session.scalars(
            select(PipelineRunItem)
            .where(PipelineRunItem.pipeline_run_id == run.id)
            .order_by(PipelineRunItem.document_id)
        ).all()
        versions = session.scalars(
            select(DocumentVersion).order_by(DocumentVersion.version_number)
        ).all()

    assert report.chunk_count == len(chunks)
    assert report.embedding_count == len(embeddings)
    assert report.indexed_count == len(versions)
    assert len(chunks) >= 4
    assert len(embeddings) == len(chunks)
    assert run.status == "completed"
    assert run.success_count == len(versions)
    assert run.failure_count == 0
    assert run.total_items == len(versions)
    assert all(item.status == "success" for item in items)
    assert all(chunk.metadata_json["config_hash"] for chunk in chunks)
    assert all(embedding.provider == "deterministic-local" for embedding in embeddings)
    assert all(embedding.dimensions == 8 for embedding in embeddings)


def test_index_knowledge_base_is_idempotent_for_unchanged_document_versions(tmp_path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text(
        "# Guide\n\nAlpha beta gamma delta epsilon zeta eta theta\n",
        encoding="utf-8",
    )

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )

        first = index_knowledge_base(session=session, knowledge_base_name="fixture-local")
        second = index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        chunks = session.scalars(select(Chunk)).all()
        embeddings = session.scalars(select(Embedding)).all()
        runs = session.scalars(
            select(PipelineRun)
            .where(PipelineRun.run_type == "chunk_embedding")
            .order_by(PipelineRun.started_at)
        ).all()
        run_items = session.scalars(
            select(PipelineRunItem)
            .where(PipelineRunItem.pipeline_run_id == runs[-1].id)
            .order_by(PipelineRunItem.started_at)
        ).all()

    assert first.indexed_count == 1
    assert first.skipped_count == 0
    assert second.indexed_count == 0
    assert second.skipped_count == 1
    assert len(chunks) == first.chunk_count
    assert len(embeddings) == first.embedding_count
    assert runs[-1].status == "completed"
    assert runs[-1].success_count == 0
    assert all(item.status == "skipped" for item in run_items)


def test_index_knowledge_base_reindexes_new_document_version_after_ingestion_change(
    tmp_path,
) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    guide_path = docs / "guide.md"
    guide_path.write_text("# Guide\n\nAlpha beta gamma delta\n", encoding="utf-8")

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local", chunk_size=14)

        guide_path.write_text(
            "# Guide\n\nAlpha beta gamma delta epsilon zeta eta theta\n",
            encoding="utf-8",
        )
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )

        report = index_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            chunk_size=14,
        )

        versions = session.scalars(
            select(DocumentVersion).order_by(DocumentVersion.version_number)
        ).all()
        latest_version = versions[-1]
        latest_chunks = session.scalars(
            select(Chunk)
            .where(Chunk.document_version_id == latest_version.id)
            .order_by(Chunk.chunk_index)
        ).all()
        latest_embeddings = session.scalars(
            select(Embedding)
            .join(Chunk, Embedding.chunk_id == Chunk.id)
            .where(Chunk.document_version_id == latest_version.id)
        ).all()

    assert [version.version_number for version in versions] == [1, 2]
    assert report.indexed_count == 1
    assert len(latest_chunks) == report.chunk_count
    assert len(latest_embeddings) == report.embedding_count
    assert latest_chunks[0].metadata_json["version_number"] == 2


def test_replace_version_index_replaces_existing_chunks_and_embeddings(tmp_path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("alpha beta gamma delta", encoding="utf-8")

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local", chunk_size=8)

        version = session.scalars(select(DocumentVersion)).one()
        document = version.document
        original_chunk_ids = set(session.scalars(select(Chunk.id)).all())

        created_chunks, created_embeddings = _replace_version_index(
            session,
            document_version=version,
            document=document,
            chunking_config=ChunkingConfig(chunk_size=6, chunk_overlap=1),
            embedding_provider=DeterministicEmbeddingProvider(dimensions=4),
            chunk_profile_id="*.chunk.default",
            embed_profile_id="*.embed.default",
        )

        replacement_chunks = session.scalars(
            select(Chunk).where(Chunk.document_version_id == version.id)
        ).all()
        replacement_chunk_ids = {chunk.id for chunk in replacement_chunks}

    assert created_chunks == len(replacement_chunks)
    assert created_embeddings == len(replacement_chunks)
    assert replacement_chunk_ids
    assert replacement_chunk_ids.isdisjoint(original_chunk_ids)


def test_version_already_indexed_rejects_chunks_with_different_config_hash(tmp_path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("alpha beta gamma delta", encoding="utf-8")

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local", chunk_size=8)

        version = session.scalars(select(DocumentVersion)).one()

        assert (
            _version_already_indexed(
                session,
                document_version=version,
                config_hash="different-config-hash",
                provider_name="deterministic-local",
                model_name="hash-8d",
            )
            is False
        )


def test_index_knowledge_base_skips_empty_document_versions(tmp_path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "empty.txt").write_text("", encoding="utf-8")

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        report = index_knowledge_base(session=session, knowledge_base_name="fixture-local")
        run = session.scalars(
            select(PipelineRun).where(PipelineRun.run_type == "chunk_embedding")
        ).one()
        item = session.scalars(
            select(PipelineRunItem).where(PipelineRunItem.pipeline_run_id == run.id)
        ).one()

    assert report.indexed_count == 0
    assert report.skipped_count == 1
    assert report.chunk_count == 0
    assert report.embedding_count == 0
    assert run.status == "completed"
    assert item.status == "skipped"
    assert item.metadata_json["skip_reason"] == "empty_extracted_text"


def test_index_knowledge_base_raises_for_missing_knowledge_base(sqlite_session) -> None:
    with pytest.raises(ValueError, match="Knowledge base 'missing' was not found"):
        index_knowledge_base(session=sqlite_session, knowledge_base_name="missing")


def test_index_knowledge_base_records_failures_without_aborting_run(tmp_path, monkeypatch) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("alpha beta gamma", encoding="utf-8")

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )

        def failing_embed(self, text: str) -> EmbeddingResult:
            raise RuntimeError("embedding failed")

        monkeypatch.setattr(DeterministicEmbeddingProvider, "embed_text", failing_embed)

        report = index_knowledge_base(session=session, knowledge_base_name="fixture-local")
        run = session.scalars(
            select(PipelineRun).where(PipelineRun.run_type == "chunk_embedding")
        ).one()
        item = session.scalars(
            select(PipelineRunItem).where(PipelineRunItem.pipeline_run_id == run.id)
        ).one()

    assert report.failed_count == 1
    assert report.indexed_count == 0
    assert report.chunk_count == 0
    assert report.embedding_count == 0
    assert run.status == "completed_with_failures"
    assert item.status == "failed"
    assert item.error_message == "embedding failed"


def test_index_knowledge_base_mirrors_embeddings_to_explicit_vector_backend(tmp_path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("alpha beta gamma", encoding="utf-8")

    class FakeBackend:
        backend_name = "qdrant"
        distance_metric = "cosine"

        def __init__(self) -> None:
            self.collection: VectorCollection | None = None
            self.records: list[VectorEmbeddingRecord] = []

        def ensure_collection(
            self, session, collection: VectorCollection
        ) -> VectorCollectionStatus:
            del session
            self.collection = collection
            return VectorCollectionStatus(
                name=collection.name,
                exists=True,
                dimensions=collection.dimensions,
                distance_metric="cosine",
                vector_count=0,
                backend="qdrant",
            )

        def upsert_embeddings(
            self, session, collection: VectorCollection, records: list[VectorEmbeddingRecord]
        ):
            del session, collection
            self.records.extend(records)
            return [record.embedding_id for record in records]

        def delete_embeddings(self, session, collection: VectorCollection, *, embedding_ids):
            del session, collection, embedding_ids
            return 0

        def search(
            self, session, collection: VectorCollection, *, query_vector, top_k, filters=None
        ):
            del session, collection, query_vector, top_k, filters
            return []

        def health(self, session):
            del session
            raise AssertionError("health should not be called during indexing")

    backend = FakeBackend()

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )

        report = index_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            vector_backend=backend,
        )

    assert report.embedding_count == len(backend.records)
    assert backend.collection is not None
    assert backend.collection.knowledge_base == "fixture-local"


def test_mirror_version_index_returns_zero_when_no_embeddings(sqlite_session) -> None:
    class FakeBackend:
        def ensure_collection(self, session, collection):
            del session, collection
            raise AssertionError("ensure_collection should not be called")

        def upsert_embeddings(self, session, collection, records):
            del session, collection, records
            raise AssertionError("upsert_embeddings should not be called")

    version = DocumentVersion(
        document_id="00000000-0000-0000-0000-000000000000",
        version_number=1,
        content_hash="hash",
        parser_name="plaintext",
        parser_config_json={},
        extracted_text="text",
        metadata_json={},
    )

    count = _mirror_version_index(
        sqlite_session,
        knowledge_base_name="fixture-local",
        knowledge_base_id="00000000-0000-0000-0000-000000000000",
        document_version=version,
        embedding_provider=DeterministicEmbeddingProvider(dimensions=8),
        vector_backend=FakeBackend(),
    )

    assert count == 0
