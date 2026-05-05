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
from ragrig.embeddings import DeterministicEmbeddingProvider
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.main import create_app
from ragrig.retrieval import (
    EmbeddingProfileMismatchError,
    EmptyQueryError,
    InvalidTopKError,
    KnowledgeBaseNotFoundError,
    _cosine_distance,
    _normalize_vector,
    _search_with_sql_distance,
    search_knowledge_base,
)
from ragrig.vectorstore.base import VectorCollection, VectorSearchResult


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
    assert report.backend == "pgvector"
    assert report.backend_metadata["distance_metric"] == "cosine"
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


def test_search_knowledge_base_rejects_empty_query_before_lookup(sqlite_session) -> None:
    with pytest.raises(EmptyQueryError, match="Query must not be empty"):
        search_knowledge_base(
            session=sqlite_session,
            knowledge_base_name="fixture-local",
            query="   ",
        )


def test_search_knowledge_base_raises_for_missing_knowledge_base(sqlite_session) -> None:
    with pytest.raises(KnowledgeBaseNotFoundError, match="Knowledge base 'missing' was not found"):
        search_knowledge_base(
            session=sqlite_session,
            knowledge_base_name="missing",
            query="fixture",
        )


def test_search_knowledge_base_accepts_explicit_matching_profile(tmp_path) -> None:
    docs = _seed_documents(tmp_path, {"guide.txt": "matching profile"})

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

        report = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="matching profile",
            provider="deterministic-local",
            model="hash-16d",
            dimensions=16,
        )

    assert report.total_results == 1
    assert report.dimensions == 16
    assert report.model == "hash-16d"


def test_search_knowledge_base_resolves_query_embedding_provider_from_registry(
    tmp_path, monkeypatch
) -> None:
    docs = _seed_documents(tmp_path, {"guide.txt": "matching profile"})
    calls: list[tuple[str, dict[str, int]]] = []

    class FakeRegistry:
        def get(self, name: str, **config):
            calls.append((name, config))
            return DeterministicEmbeddingProvider(dimensions=config["dimensions"])

    monkeypatch.setattr("ragrig.retrieval.get_provider_registry", lambda: FakeRegistry())

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

        report = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="matching profile",
            provider="deterministic-local",
            model="hash-16d",
            dimensions=16,
        )

    assert report.total_results == 1
    assert calls == [("deterministic-local", {"dimensions": 16})]


def test_retrieval_vector_helpers_cover_edge_cases() -> None:
    assert _normalize_vector((1, "2.5", 3)) == [1.0, 2.5, 3.0]
    assert _cosine_distance([], [1.0]) == 1.0
    assert _cosine_distance([0.0, 0.0], [1.0, 0.0]) == 1.0
    assert _cosine_distance([1.0, 0.0], [1.0, 0.0]) == 0.0


def test_search_knowledge_base_uses_sql_distance_for_postgresql_bind(tmp_path, monkeypatch) -> None:
    docs = _seed_documents(tmp_path, {"guide.txt": "postgres branch target"})

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        original_name = session.bind.dialect.name
        monkeypatch.setattr(session.bind.dialect, "name", "postgresql")
        calls: list[tuple[str, int]] = []

        def fake_sql_distance(_session, **kwargs):
            calls.append((kwargs["provider"], kwargs["top_k"]))
            return []

        def fail_python_distance(_session, **kwargs):
            raise AssertionError("python distance fallback should not be used")

        monkeypatch.setattr("ragrig.retrieval._search_with_sql_distance", fake_sql_distance)
        monkeypatch.setattr("ragrig.retrieval._search_with_python_distance", fail_python_distance)

        report = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="postgres branch target",
            top_k=3,
        )

        monkeypatch.setattr(session.bind.dialect, "name", original_name)

    assert report.total_results == 0
    assert calls == [("deterministic-local", 3)]


def test_search_with_sql_distance_returns_ranked_results(tmp_path, monkeypatch) -> None:
    del tmp_path

    class FakeDistanceExpr:
        def label(self, _name: str) -> "FakeDistanceExpr":
            return self

        def asc(self) -> "FakeDistanceExpr":
            return self

    class FakeStatement:
        def add_columns(self, _column) -> "FakeStatement":
            return self

        def order_by(self, *_args) -> "FakeStatement":
            return self

        def limit(self, _value: int) -> "FakeStatement":
            return self

    class FakeEmbeddingColumn:
        def cosine_distance(self, vector: list[float]) -> FakeDistanceExpr:
            assert vector == [0.0] * 8
            return FakeDistanceExpr()

    row = type(
        "Row",
        (),
        {
            "document_id": "doc-id",
            "document_version_id": "doc-version-id",
            "chunk_id": "chunk-id",
            "chunk_index": 0,
            "document_uri": "/tmp/guide.txt",
            "source_uri": "/tmp",
            "text": "sql retrieval branch target",
            "chunk_metadata": {"chunker": "char_window_v1"},
            "distance": 0.125,
        },
    )()

    class FakeResult:
        def all(self) -> list[object]:
            return [row]

    class FakeSession:
        def execute(self, statement):
            return FakeResult()

    monkeypatch.setattr("ragrig.retrieval.Embedding.embedding", FakeEmbeddingColumn())
    monkeypatch.setattr("ragrig.retrieval.Chunk.chunk_index", FakeDistanceExpr())
    monkeypatch.setattr("ragrig.retrieval._build_base_statement", lambda **kwargs: FakeStatement())

    report = _search_with_sql_distance(
        FakeSession(),
        knowledge_base_id="kb-id",
        provider="deterministic-local",
        model="hash-8d",
        dimensions=8,
        query_vector=[0.0] * 8,
        top_k=1,
    )

    assert len(report) == 1
    assert report[0].text == "sql retrieval branch target"
    assert report[0].distance == 0.125
    assert report[0].score == 0.875


def test_search_knowledge_base_can_use_explicit_vector_backend(tmp_path) -> None:
    docs = _seed_documents(tmp_path, {"guide.txt": "explicit backend query target"})

    class FakeBackend:
        backend_name = "qdrant"
        distance_metric = "cosine"

        def __init__(self) -> None:
            self.collection: VectorCollection | None = None

        def ensure_collection(self, session, collection: VectorCollection):
            del session
            self.collection = collection
            return None

        def search(
            self, session, collection: VectorCollection, *, query_vector, top_k, filters=None
        ):
            del session, collection, query_vector, top_k, filters
            return [
                VectorSearchResult(
                    embedding_id=response_embedding_id,
                    document_id=response_document_id,
                    document_version_id=response_document_version_id,
                    chunk_id=response_chunk_id,
                    chunk_index=0,
                    text="explicit backend query target",
                    score=0.91,
                    distance=0.09,
                    metadata={
                        "document_uri": str(docs / "guide.txt"),
                        "source_uri": str(docs),
                        "chunk_metadata": {"chunker": "char_window_v1"},
                    },
                )
            ]

        def upsert_embeddings(self, session, collection, records):
            del session, collection, records
            return []

        def delete_embeddings(self, session, collection, *, embedding_ids):
            del session, collection, embedding_ids
            return 0

        def health(self, session):
            del session
            raise AssertionError("health should not be called in retrieval")

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        latest_version = session.scalars(
            select(DocumentVersion).order_by(DocumentVersion.version_number.desc())
        ).first()
        assert latest_version is not None
        document = latest_version.document
        chunk = latest_version.chunks[0]
        response_document_id = document.id
        response_document_version_id = latest_version.id
        response_chunk_id = chunk.id
        response_embedding_id = chunk.embeddings[0].id

        report = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="explicit backend query target",
            vector_backend=FakeBackend(),
        )

    assert report.backend == "qdrant"
    assert report.distance_metric == "cosine_similarity"
    assert report.results[0].text == "explicit backend query target"
    assert report.results[0].document_uri.endswith("guide.txt")


def test_search_knowledge_base_explicit_backend_empty_results(tmp_path) -> None:
    docs = _seed_documents(tmp_path, {"guide.txt": "explicit backend empty result"})

    class FakeBackend:
        backend_name = "qdrant"
        distance_metric = "cosine"

        def ensure_collection(self, session, collection):
            del session, collection
            return None

        def search(self, session, collection, *, query_vector, top_k, filters=None):
            del session, collection, query_vector, top_k, filters
            return []

        def upsert_embeddings(self, session, collection, records):
            del session, collection, records
            return []

        def delete_embeddings(self, session, collection, *, embedding_ids):
            del session, collection, embedding_ids
            return 0

        def health(self, session):
            del session
            return None

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        report = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="explicit backend empty result",
            vector_backend=FakeBackend(),
        )

    assert report.backend == "qdrant"
    assert report.total_results == 0
    assert report.results == []


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
        "backend": "pgvector",
        "backend_metadata": {
            "distance_metric": "cosine",
            "status": "ready",
        },
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
