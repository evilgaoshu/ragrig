from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.db.models import Base, DocumentVersion
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.main import create_app
from ragrig.retrieval import (
    EmbeddingProfileMismatchError,
    InvalidTopKError,
    search_knowledge_base,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def _create_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def _seed_documents(tmp_path, files: dict[str, str]):
    docs = tmp_path / "docs"
    docs.mkdir()
    for name, content in files.items():
        (docs / name).write_text(content, encoding="utf-8")
    return docs


def _create_file_session_factory(database_path) -> Callable[[], Session]:
    engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
    Base.metadata.create_all(engine)

    def _factory() -> Session:
        return Session(engine, expire_on_commit=False)

    return _factory


def test_search_knowledge_base_returns_ranked_results_with_citation_fields(tmp_path) -> None:
    docs = _seed_documents(
        tmp_path,
        {
            "guide.txt": "retrieval ranking target text",
            "notes.txt": "another unrelated chunk for retrieval",
            "faq.txt": "fallback fixture content",
        },
    )

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            chunk_size=500,
        )

        report = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="retrieval ranking target text",
            top_k=2,
        )

    assert report.knowledge_base == "fixture-local"
    assert report.provider == "deterministic-local"
    assert report.model == "hash-8d"
    assert report.dimensions == 8
    assert report.distance_metric == "cosine_distance"
    assert len(report.results) == 2
    assert report.results[0].document_uri.endswith("guide.txt")
    assert report.results[0].text == "retrieval ranking target text"
    assert report.results[0].text_preview == "retrieval ranking target text"
    assert report.results[0].score >= report.results[1].score
    assert report.results[0].distance <= report.results[1].distance
    assert report.results[0].document_id
    assert report.results[0].document_version_id
    assert report.results[0].chunk_id
    assert report.results[0].chunk_index == 0


def test_search_knowledge_base_only_returns_latest_document_versions(tmp_path) -> None:
    docs = _seed_documents(tmp_path, {"guide.txt": "version one obsolete term"})
    guide_path = docs / "guide.txt"

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        guide_path.write_text("version two current term", encoding="utf-8")
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        latest_version = session.scalars(
            select(DocumentVersion).order_by(DocumentVersion.version_number.desc())
        ).first()
        report = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="version two current term",
            top_k=1,
        )

    assert latest_version is not None
    assert len(report.results) == 1
    assert report.results[0].document_version_id == latest_version.id
    assert report.results[0].text == "version two current term"


def test_search_knowledge_base_returns_empty_results_when_not_indexed(tmp_path) -> None:
    docs = _seed_documents(tmp_path, {"guide.txt": "ingested but not indexed"})

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )

        report = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="ingested but not indexed",
        )

    assert report.total_results == 0
    assert report.results == []


def test_search_knowledge_base_raises_on_embedding_profile_mismatch(tmp_path) -> None:
    docs = _seed_documents(tmp_path, {"guide.txt": "custom dimension fixture"})

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            embedding_dimensions=16,
        )

        with pytest.raises(EmbeddingProfileMismatchError) as exc_info:
            search_knowledge_base(
                session=session,
                knowledge_base_name="fixture-local",
                query="custom dimension fixture",
                dimensions=8,
            )

    assert exc_info.value.details["available_profiles"] == [
        {"provider": "deterministic-local", "model": "hash-16d", "dimensions": 16}
    ]


def test_search_knowledge_base_rejects_non_positive_top_k(tmp_path) -> None:
    docs = _seed_documents(tmp_path, {"guide.txt": "top k validation fixture"})

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        with pytest.raises(InvalidTopKError) as exc_info:
            search_knowledge_base(
                session=session,
                knowledge_base_name="fixture-local",
                query="top k validation fixture",
                top_k=0,
            )

    assert exc_info.value.details == {"top_k": 0}


@pytest.mark.anyio
async def test_retrieval_search_api_returns_contract_payload(tmp_path) -> None:
    database_path = tmp_path / "retrieval-api.db"
    session_factory = _create_file_session_factory(database_path)

    docs = _seed_documents(tmp_path, {"guide.txt": "retrieval api contract"})
    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/retrieval/search",
            json={
                "knowledge_base": "fixture-local",
                "query": "retrieval api contract",
                "top_k": 1,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "knowledge_base": "fixture-local",
        "query": "retrieval api contract",
        "top_k": 1,
        "provider": "deterministic-local",
        "model": "hash-8d",
        "dimensions": 8,
        "distance_metric": "cosine_distance",
        "total_results": 1,
        "results": [
            {
                "document_id": response.json()["results"][0]["document_id"],
                "document_version_id": response.json()["results"][0]["document_version_id"],
                "chunk_id": response.json()["results"][0]["chunk_id"],
                "chunk_index": 0,
                "document_uri": str(docs / "guide.txt"),
                "source_uri": str(docs),
                "text": "retrieval api contract",
                "text_preview": "retrieval api contract",
                "distance": response.json()["results"][0]["distance"],
                "score": response.json()["results"][0]["score"],
                "chunk_metadata": response.json()["results"][0]["chunk_metadata"],
            }
        ],
    }


@pytest.mark.anyio
async def test_retrieval_search_api_returns_not_found_error_for_missing_knowledge_base() -> None:
    app = create_app(check_database=lambda: None, session_factory=_create_session)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/retrieval/search",
            json={
                "knowledge_base": "missing-kb",
                "query": "missing",
                "top_k": 1,
            },
        )

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "knowledge_base_not_found",
            "details": {"knowledge_base": "missing-kb"},
            "message": "Knowledge base 'missing-kb' was not found",
        }
    }


@pytest.mark.anyio
async def test_retrieval_search_api_rejects_empty_query() -> None:
    app = create_app(check_database=lambda: None, session_factory=_create_session)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/retrieval/search",
            json={
                "knowledge_base": "fixture-local",
                "query": "   ",
                "top_k": 1,
            },
        )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "empty_query",
            "details": {"query": "   "},
            "message": "Query must not be empty",
        }
    }


@pytest.mark.anyio
async def test_retrieval_search_api_rejects_non_positive_top_k() -> None:
    app = create_app(check_database=lambda: None, session_factory=_create_session)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/retrieval/search",
            json={
                "knowledge_base": "fixture-local",
                "query": "fixture",
                "top_k": 0,
            },
        )

    assert response.status_code == 422
