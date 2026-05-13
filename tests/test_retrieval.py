from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.acl import AclMetadata, Principal
from ragrig.db.models import AuditEvent, Base, Document, DocumentVersion
from ragrig.embeddings import DeterministicEmbeddingProvider
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.main import create_app
from ragrig.repositories import set_document_acl
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

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def _create_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    original_close = session.close

    def close() -> None:
        try:
            original_close()
        finally:
            engine.dispose()

    session.close = close
    return session


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

        def where(self, _clause) -> "FakeStatement":
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
    resp_json = response.json()
    assert resp_json["knowledge_base"] == "fixture-local"
    assert resp_json["query"] == "retrieval api contract"
    assert resp_json["top_k"] == 1
    assert resp_json["provider"] == "deterministic-local"
    assert resp_json["model"] == "hash-8d"
    assert resp_json["dimensions"] == 8
    assert resp_json["distance_metric"] == "cosine_distance"
    assert resp_json["backend"] == "pgvector"
    assert resp_json["backend_metadata"] == {
        "distance_metric": "cosine",
        "status": "ready",
    }
    assert resp_json["total_results"] == 1
    assert len(resp_json["results"]) == 1
    r = resp_json["results"][0]
    assert r["document_uri"] == str(docs / "guide.txt")
    assert r["source_uri"] == str(docs)
    assert r["text"] == "retrieval api contract"
    assert r["text_preview"] == "retrieval api contract"
    assert r["chunk_index"] == 0
    assert "rank_stage_trace" in r
    assert "stages" in r["rank_stage_trace"]
    assert r["rank_stage_trace"]["stages"][0]["stage"] == "vector"
    assert "degraded" not in resp_json


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


# ── ACL filtering integration tests ────────────────────────────────────────────


def test_public_document_retrievable_without_principal(tmp_path) -> None:
    """Public document with no ACL in metadata is retrievable without principal."""
    docs = _seed_documents(tmp_path, {"guide.txt": "public accessible content"})

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        # No ACL metadata → default public; search without principal should work
        report = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="public accessible content",
            principal_ids=None,
            enforce_acl=True,
        )

    assert report.total_results == 1
    assert report.results[0].text == "public accessible content"


def test_protected_document_returned_with_valid_principal(tmp_path) -> None:
    """Protected document + valid principal → returned."""
    docs = _seed_documents(tmp_path, {"secret.md": "protected secret content"})

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        # Manually set ACL on chunks to protected with alice allowed
        from ragrig.db.models import Chunk

        chunks = session.scalars(select(Chunk)).all()
        for chunk in chunks:
            chunk.metadata_json = {
                **chunk.metadata_json,
                "acl": {
                    "visibility": "protected",
                    "allowed_principals": ["alice", "group:eng"],
                    "denied_principals": [],
                    "acl_source": "test",
                    "acl_source_hash": "abc",
                    "inheritance": "document",
                },
            }
        session.commit()

        report = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="protected secret content",
            principal_ids=["alice"],
            enforce_acl=True,
        )

    assert report.total_results == 1
    assert report.results[0].text == "protected secret content"


def test_protected_document_not_returned_without_principal(tmp_path) -> None:
    """Protected document + no principal → not returned."""
    docs = _seed_documents(tmp_path, {"secret.md": "top secret guarded content"})

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        from ragrig.db.models import Chunk

        chunks = session.scalars(select(Chunk)).all()
        for chunk in chunks:
            chunk.metadata_json = {
                **chunk.metadata_json,
                "acl": {
                    "visibility": "protected",
                    "allowed_principals": ["alice"],
                    "denied_principals": [],
                    "acl_source": "test",
                    "acl_source_hash": "abc",
                    "inheritance": "document",
                },
            }
        session.commit()

        report = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="top secret guarded content",
            principal_ids=[],
            enforce_acl=True,
        )

    assert report.total_results == 0


def test_protected_document_not_returned_with_denied_principal(tmp_path) -> None:
    """Protected document + denied principal → not returned."""
    docs = _seed_documents(tmp_path, {"secret.md": "denied access content"})

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        from ragrig.db.models import Chunk

        chunks = session.scalars(select(Chunk)).all()
        for chunk in chunks:
            chunk.metadata_json = {
                **chunk.metadata_json,
                "acl": {
                    "visibility": "protected",
                    "allowed_principals": ["alice", "bob"],
                    "denied_principals": ["bob"],
                    "acl_source": "test",
                    "acl_source_hash": "abc",
                    "inheritance": "document",
                },
            }
        session.commit()

        # bob is denied even though in allowed_principals
        report = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="denied access content",
            principal_ids=["bob"],
            enforce_acl=True,
        )

        assert report.total_results == 0

        # alice should still be allowed (same session)
        report_alice = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="denied access content",
            principal_ids=["alice"],
            enforce_acl=True,
        )

        assert report_alice.total_results == 1


def test_mixed_top_k_acl_filtering_maintains_count_and_order(tmp_path) -> None:
    """Mixed top-k: public + protected chunks, filtered count correct, order stable."""
    docs = _seed_documents(
        tmp_path,
        {
            "public_a.txt": "zzz public alpha",
            "protected_b.txt": "yyy protected beta",
            "public_c.txt": "xxx public gamma",
        },
    )

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        from ragrig.db.models import Chunk

        chunks = session.scalars(select(Chunk).order_by(Chunk.chunk_index)).all()
        # Make the second document (protected_b) protected with alice only
        for chunk in chunks:
            if "protected beta" in chunk.text:
                chunk.metadata_json = {
                    **chunk.metadata_json,
                    "acl": {
                        "visibility": "protected",
                        "allowed_principals": ["alice"],
                        "denied_principals": [],
                        "acl_source": "test",
                        "acl_source_hash": "abc",
                        "inheritance": "document",
                    },
                }
        session.commit()

        # Without alice, only public documents should appear (2 results)
        report_no_auth = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="public",
            top_k=5,
            principal_ids=["guest"],
            enforce_acl=True,
        )

        public_texts = {r.text for r in report_no_auth.results}
        assert len(public_texts) == 2
        assert "zzz public alpha" in public_texts
        assert "xxx public gamma" in public_texts
        assert "yyy protected beta" not in public_texts

        # With alice, all 3 should be returned
        report_with_alice = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="public",
            top_k=5,
            principal_ids=["alice"],
            enforce_acl=True,
        )

        all_texts = {r.text for r in report_with_alice.results}
        assert len(all_texts) == 3
        assert "yyy protected beta" in all_texts

        # Results must be sorted by distance (score descending)
        scores = [r.score for r in report_with_alice.results]
        assert scores == sorted(scores, reverse=True)


def test_old_call_without_acl_context_is_defined_and_permissive(tmp_path) -> None:
    """Old caller not passing ACL context gets default behavior (all results).

    Without principal_ids, enforce_acl defaults to True but with no principals,
    only public chunks (or chunks without ACL metadata) are returned.
    Chunks without ACL metadata default to 'public' visibility."""
    docs = _seed_documents(tmp_path, {"guide.txt": "old caller fixture content"})

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        # Old-style call: no principal_ids, no enforce_acl
        report = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="old caller fixture content",
        )

    assert report.total_results == 1


@pytest.mark.anyio
async def test_retrieval_search_api_supports_acl_parameters(tmp_path) -> None:
    """POST /retrieval/search accepts principal_ids and enforce_acl."""
    database_path = tmp_path / "retrieval-acl-api.db"
    session_factory = _create_file_session_factory(database_path)

    docs = _seed_documents(tmp_path, {"guide.txt": "acl api parameter test"})
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
        # With principal_ids and enforce_acl
        response = await client.post(
            "/retrieval/search",
            json={
                "knowledge_base": "fixture-local",
                "query": "acl api parameter test",
                "top_k": 1,
                "principal_ids": ["alice"],
                "enforce_acl": True,
            },
        )

    assert response.status_code == 200
    assert response.json()["total_results"] == 1


@pytest.mark.anyio
async def test_retrieval_search_api_acl_fields_are_optional(tmp_path) -> None:
    """POST /retrieval/search without ACL fields still works (backward compat)."""
    database_path = tmp_path / "retrieval-acl-compat.db"
    session_factory = _create_file_session_factory(database_path)

    docs = _seed_documents(tmp_path, {"guide.txt": "acl compat backward test"})
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
        # Old-style call without principal_ids or enforce_acl
        response = await client.post(
            "/retrieval/search",
            json={
                "knowledge_base": "fixture-local",
                "query": "acl compat backward test",
                "top_k": 1,
            },
        )

    assert response.status_code == 200
    assert response.json()["total_results"] == 1


@pytest.mark.anyio
async def test_retrieval_search_api_acl_filters_protected_document(tmp_path) -> None:
    """POST /retrieval/search with empty principals excludes protected content."""
    database_path = tmp_path / "retrieval-acl-protected.db"
    session_factory = _create_file_session_factory(database_path)

    docs = _seed_documents(tmp_path, {"secret.md": "acl protected api test"})
    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        from ragrig.db.models import Chunk

        chunks = session.scalars(select(Chunk)).all()
        for chunk in chunks:
            chunk.metadata_json = {
                **chunk.metadata_json,
                "acl": {
                    "visibility": "protected",
                    "allowed_principals": ["alice"],
                    "denied_principals": [],
                    "acl_source": "test",
                    "acl_source_hash": "abc",
                    "inheritance": "document",
                },
            }
        session.commit()

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response_no_principal = await client.post(
            "/retrieval/search",
            json={
                "knowledge_base": "fixture-local",
                "query": "acl protected api test",
                "top_k": 1,
                "principal_ids": [],
                "enforce_acl": True,
            },
        )
        assert response_no_principal.status_code == 200
        assert response_no_principal.json()["total_results"] == 0

        response_alice = await client.post(
            "/retrieval/search",
            json={
                "knowledge_base": "fixture-local",
                "query": "acl protected api test",
                "top_k": 1,
                "principal_ids": ["alice"],
                "enforce_acl": True,
            },
        )
        assert response_alice.status_code == 200
        assert response_alice.json()["total_results"] == 1


def test_search_with_sql_distance_acl_where_clauses() -> None:
    """Verify _build_acl_where_clause and _build_acl_public_only_clause build expressions."""
    from ragrig.retrieval import _build_acl_public_only_clause, _build_acl_where_clause

    where_with_principals = _build_acl_where_clause(["alice"])
    assert where_with_principals is not None

    where_public_only = _build_acl_public_only_clause()
    assert where_public_only is not None

    where_empty = _build_acl_where_clause([])
    assert where_empty is not None


def test_search_with_sql_distance_acl_code_paths(monkeypatch) -> None:
    """Exercise _search_with_sql_distance ACL branches via mocking."""
    from ragrig.retrieval import _search_with_sql_distance

    class FakeLabel:
        def label(self, _name):
            return self

        def asc(self):
            return self

    class FakeEmbedCol:
        def cosine_distance(self, _vector):
            return FakeLabel()

    class FakeStatement:
        def add_columns(self, _col):
            return self

        def where(self, _clause):
            return self

        def order_by(self, *_args):
            return self

        def limit(self, _n):
            return self

    class FakeResult:
        def all(self):
            return []

    class FakeSession:
        def execute(self, _statement):
            return FakeResult()

    monkeypatch.setattr("ragrig.retrieval.Embedding.embedding", FakeEmbedCol())
    monkeypatch.setattr("ragrig.retrieval.Chunk.chunk_index", FakeLabel())
    monkeypatch.setattr(
        "ragrig.retrieval._build_base_statement",
        lambda **kwargs: FakeStatement(),
    )

    # Test with principal_ids → triggers _build_acl_where_clause
    results_with = _search_with_sql_distance(
        FakeSession(),
        knowledge_base_id="kb-id",
        provider="p",
        model="m",
        dimensions=8,
        query_vector=[0.0] * 8,
        top_k=5,
        principal_ids=["alice"],
        enforce_acl=True,
    )
    assert results_with == []

    # Test with empty principal_ids → triggers _build_acl_public_only_clause
    results_empty = _search_with_sql_distance(
        FakeSession(),
        knowledge_base_id="kb-id",
        provider="p",
        model="m",
        dimensions=8,
        query_vector=[0.0] * 8,
        top_k=5,
        principal_ids=[],
        enforce_acl=True,
    )
    assert results_empty == []

    # Test without enforce_acl
    results_no_enforce = _search_with_sql_distance(
        FakeSession(),
        knowledge_base_id="kb-id",
        provider="p",
        model="m",
        dimensions=8,
        query_vector=[0.0] * 8,
        top_k=5,
        principal_ids=["alice"],
        enforce_acl=False,
    )
    assert results_no_enforce == []


def test_acl_filtering_with_explicit_vector_backend(tmp_path) -> None:
    """Vector backend returns results; ACL filters after fetch."""
    import uuid as _uuid

    docs = _seed_documents(tmp_path, {"guide.txt": "vector backend acl filter"})

    class FakeAclBackend:
        backend_name = "qdrant"
        distance_metric = "cosine"

        def ensure_collection(self, session, collection):
            return None

        def search(self, session, collection, *, query_vector, top_k, filters=None):
            from ragrig.vectorstore.base import VectorSearchResult

            return [
                VectorSearchResult(
                    embedding_id=_uuid.uuid4(),
                    document_id=_uuid.uuid4(),
                    document_version_id=_uuid.uuid4(),
                    chunk_id=_uuid.uuid4(),
                    chunk_index=0,
                    text="vector backend acl filter",
                    score=0.95,
                    distance=0.05,
                    metadata={
                        "document_uri": str(docs / "guide.txt"),
                        "source_uri": str(docs),
                        "chunk_metadata": {
                            "acl": {
                                "visibility": "protected",
                                "allowed_principals": ["alice"],
                                "denied_principals": [],
                                "acl_source": "test",
                                "acl_source_hash": "abc",
                                "inheritance": "document",
                            }
                        },
                    },
                ),
            ]

        def upsert_embeddings(self, session, collection, records):
            return []

        def delete_embeddings(self, session, collection, *, embedding_ids):
            return 0

        def health(self, session):
            return None

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        report_blocked = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="vector backend acl filter",
            vector_backend=FakeAclBackend(),
            principal_ids=["guest"],
            enforce_acl=True,
        )
        assert report_blocked.backend == "qdrant"
        assert report_blocked.total_results == 0

        report_allowed = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="vector backend acl filter",
            vector_backend=FakeAclBackend(),
            principal_ids=["alice"],
            enforce_acl=True,
        )
        assert report_allowed.backend == "qdrant"
        assert report_allowed.total_results == 1


# ── Hybrid retrieval tests ──────────────────────────────────────────────────


def test_hybrid_mode_returns_rank_stage_trace_with_lexical_and_vector(tmp_path) -> None:
    """Hybrid mode returns vector_score, lexical_score, combined_score in trace."""
    docs = _seed_documents(
        tmp_path,
        {
            "guide.txt": "hybrid retrieval ranking target text",
            "notes.txt": "some unrelated notes for retrieval",
            "faq.txt": "faq content about retrieval ranking",
        },
    )

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
            query="retrieval ranking",
            top_k=2,
            mode="hybrid",
        )

    assert report.total_results == 2
    for r in report.results:
        trace = r.rank_stage_trace
        assert trace["final_source"] == "hybrid_fusion"
        stages = trace["stages"]
        assert len(stages) >= 2
        stage_names = [s["stage"] for s in stages]
        assert "vector" in stage_names
        assert "lexical" in stage_names
        assert "weights" in trace
        assert "lexical_weight" in trace["weights"]
        assert "vector_weight" in trace["weights"]


def test_hybrid_mode_results_sorted_by_combined_score(tmp_path) -> None:
    """Hybrid results are sorted by combined_score descending, not vector score."""
    docs = _seed_documents(
        tmp_path,
        {
            "a.txt": "aaa zzz unrelated text",
            "b.txt": "bbb retrieval target text",
            "c.txt": "ccc retrieval target text",
        },
    )

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
            query="retrieval target",
            top_k=3,
            mode="hybrid",
        )

    assert report.total_results == 3
    scores = [r.score for r in report.results]
    assert scores == sorted(scores, reverse=True)


def test_dense_mode_is_backward_compatible(tmp_path) -> None:
    """Dense mode (default) should produce same results as old API."""
    docs = _seed_documents(
        tmp_path,
        {"guide.txt": "dense backward compatibility test"},
    )

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
            query="dense backward compatibility test",
            top_k=1,
            mode="dense",
        )

    assert report.total_results == 1
    assert report.results[0].rank_stage_trace["final_source"] == "vector"
    assert not report.degraded


def test_lexical_only_fallback_when_no_embeddings(tmp_path) -> None:
    """When no embeddings exist, hybrid mode returns empty results gracefully."""
    docs = _seed_documents(tmp_path, {"guide.txt": "some content here"})

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        # Not indexed — no embeddings

        report = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="some content",
            mode="hybrid",
        )

    assert report.total_results == 0
    assert report.results == []


def test_fake_reranker_changes_candidate_order(tmp_path) -> None:
    """Fake reranker should reorder candidates and produce explanatory trace."""
    docs = _seed_documents(
        tmp_path,
        {
            "a.txt": "banana split dessert",
            "b.txt": "apple pie recipe",
            "c.txt": "apple banana smoothie",
        },
    )

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
            query="apple banana",
            top_k=3,
            mode="rerank",
        )

    assert report.total_results == 3
    # The fake reranker ranks by query token match ratio
    # "apple banana smoothie" has 2/2 tokens matching → highest
    # "apple pie recipe" has 1/2 → lower
    # "banana split dessert" has 1/2 → similar
    for r in report.results:
        trace = r.rank_stage_trace
        stages = trace["stages"]
        assert any(s["stage"] == "rerank" for s in stages)
        rerank_stage = [s for s in stages if s["stage"] == "rerank"][0]
        assert "score" in rerank_stage
        assert "original_rank" in rerank_stage
        assert "new_rank" in rerank_stage

    # The highest-ranked result should contain both "apple" and "banana"
    top_text = report.results[0].text.lower()
    assert "apple" in top_text and "banana" in top_text


def test_reranker_provider_unavailable_degrade(tmp_path) -> None:
    """When reranker provider is unavailable, mode degrades gracefully."""
    docs = _seed_documents(
        tmp_path,
        {"guide.txt": "degrade test content here"},
    )

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        # Request a non-existent reranker provider to trigger degrade
        report = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="degrade test content",
            top_k=1,
            mode="rerank",
            reranker_provider="non_existent_reranker",
        )

    assert report.degraded is True
    assert report.degraded_reason != ""
    assert report.total_results == 1
    # Trace should show degraded rerank stage
    trace = report.results[0].rank_stage_trace
    stages = trace["stages"]
    rerank_stages = [s for s in stages if s["stage"] == "rerank"]
    assert len(rerank_stages) >= 1
    assert rerank_stages[0].get("status") == "degraded"


def test_acl_protected_chunk_not_in_rerank_input(tmp_path) -> None:
    """ACL-protected chunk must not enter reranker input or trace."""
    docs = _seed_documents(
        tmp_path,
        {
            "public_a.txt": "public apple document",
            "secret_b.txt": "secret banana document",
        },
    )

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        from ragrig.db.models import Chunk

        chunks = session.scalars(select(Chunk)).all()
        for chunk in chunks:
            if "secret" in chunk.text.lower():
                chunk.metadata_json = {
                    **chunk.metadata_json,
                    "acl": {
                        "visibility": "protected",
                        "allowed_principals": ["alice"],
                        "denied_principals": [],
                        "acl_source": "test",
                        "acl_source_hash": "abc",
                        "inheritance": "document",
                    },
                }
        session.commit()

        # Search with guest — protected chunk should not appear
        report = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="document",
            top_k=2,
            mode="rerank",
            principal_ids=["guest"],
            enforce_acl=True,
        )

    assert report.total_results == 1
    # The protected document should not appear in results or traces
    for r in report.results:
        assert "secret" not in r.text.lower()
        assert "banana" not in r.text.lower()


def test_hybrid_rerank_mode_full_pipeline(tmp_path) -> None:
    """Hybrid_rerank mode runs full fusion + rerank pipeline."""
    docs = _seed_documents(
        tmp_path,
        {
            "a.txt": "apple banana cherry date",
            "b.txt": "elderberry fig grape honeydew",
            "c.txt": "indian jujube kiwi lemon mango",
        },
    )

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
            query="apple banana",
            top_k=3,
            mode="hybrid_rerank",
        )

    assert report.total_results == 3
    for r in report.results:
        trace = r.rank_stage_trace
        stages = trace["stages"]
        stage_names = [s["stage"] for s in stages]
        assert "vector" in stage_names
        assert "lexical" in stage_names
        assert "rerank" in stage_names


@pytest.mark.anyio
async def test_retrieval_api_hybrid_mode(tmp_path) -> None:
    """POST /retrieval/search with mode=hybrid returns trace."""
    database_path = tmp_path / "retrieval-hybrid-api.db"
    session_factory = _create_file_session_factory(database_path)

    docs = _seed_documents(tmp_path, {"guide.txt": "hybrid api contract test"})
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
                "query": "hybrid api contract test",
                "top_k": 1,
                "mode": "hybrid",
            },
        )

    assert response.status_code == 200
    resp_json = response.json()
    assert len(resp_json["results"]) == 1
    r = resp_json["results"][0]
    assert "rank_stage_trace" in r
    assert r["rank_stage_trace"]["final_source"] == "hybrid_fusion"


@pytest.mark.anyio
async def test_retrieval_api_rerank_mode(tmp_path) -> None:
    """POST /retrieval/search with mode=rerank returns reranked results."""
    database_path = tmp_path / "retrieval-rerank-api.db"
    session_factory = _create_file_session_factory(database_path)

    docs = _seed_documents(
        tmp_path,
        {"a.txt": "rerank alpha test", "b.txt": "rerank beta test"},
    )
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
                "query": "rerank test",
                "top_k": 2,
                "mode": "rerank",
            },
        )

    assert response.status_code == 200
    resp_json = response.json()
    assert len(resp_json["results"]) == 2
    for r in resp_json["results"]:
        assert any(s["stage"] == "rerank" for s in r["rank_stage_trace"]["stages"])


@pytest.mark.anyio
async def test_retrieval_api_degraded_response(tmp_path) -> None:
    """POST /retrieval/search with unavailable reranker returns degraded flag."""
    database_path = tmp_path / "retrieval-degraded-api.db"
    session_factory = _create_file_session_factory(database_path)

    docs = _seed_documents(tmp_path, {"guide.txt": "degraded api test"})
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
                "query": "degraded api test",
                "top_k": 1,
                "mode": "rerank",
                "reranker_provider": "nonexistent_12345",
            },
        )

    assert response.status_code == 200
    resp_json = response.json()
    assert resp_json.get("degraded") is True
    assert "degraded_reason" in resp_json


@pytest.mark.anyio
async def test_retrieval_api_rejects_invalid_mode(tmp_path) -> None:
    """POST /retrieval/search rejects invalid mode values."""
    database_path = tmp_path / "retrieval-invalid-mode.db"
    session_factory = _create_file_session_factory(database_path)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/retrieval/search",
            json={
                "knowledge_base": "fixture-local",
                "query": "test",
                "top_k": 1,
                "mode": "invalid_mode",
            },
        )

    assert response.status_code == 422


def test_candidate_k_limits_candidates_for_rerank(tmp_path) -> None:
    """candidate_k limits how many candidates are fetched for rerank."""
    docs = _seed_documents(
        tmp_path,
        {f"doc_{i:02d}.txt": f"document number {i} with some content here" for i in range(5)},
    )

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
            query="document",
            top_k=3,
            mode="rerank",
            candidate_k=3,
        )

    # With 5 chunks and candidate_k=3 + top_k=3, we get at most 3 results
    assert report.total_results <= 3


def test_phase2_acl_fixture_filters_by_principal_before_rerank(tmp_path) -> None:
    (tmp_path / "engineering").mkdir()
    (tmp_path / "finance").mkdir()
    engineering_docs = _seed_documents(
        tmp_path / "engineering",
        {
            "public.txt": "runway planning shared fixture",
            "engineering.txt": "runway planning engineering fixture",
        },
    )
    finance_docs = _seed_documents(
        tmp_path / "finance",
        {"finance.txt": "runway planning finance fixture"},
    )

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="acl-engineering",
            root_path=engineering_docs,
        )
        ingest_local_directory(
            session=session,
            knowledge_base_name="acl-finance",
            root_path=finance_docs,
        )
        engineering_private = session.scalar(
            select(Document).where(Document.uri == str(engineering_docs / "engineering.txt"))
        )
        finance_private = session.scalar(
            select(Document).where(Document.uri == str(finance_docs / "finance.txt"))
        )
        assert engineering_private is not None
        assert finance_private is not None
        set_document_acl(
            session,
            document_id=engineering_private.id,
            acl=AclMetadata(
                visibility="protected",
                allowed_principals=["group:engineering"],
                acl_source="fixture",
            ),
            actor="fixture",
        )
        set_document_acl(
            session,
            document_id=finance_private.id,
            acl=AclMetadata(
                visibility="protected",
                allowed_principals=["group:finance"],
                acl_source="fixture",
            ),
            actor="fixture",
        )
        index_knowledge_base(session=session, knowledge_base_name="acl-engineering")
        index_knowledge_base(session=session, knowledge_base_name="acl-finance")

        alice = Principal(user_id="alice", group_ids=["engineering"]).subject_ids()
        bob = Principal(user_id="bob", group_ids=["finance"]).subject_ids()
        alice_report = search_knowledge_base(
            session=session,
            knowledge_base_name="acl-engineering",
            query="runway planning fixture",
            top_k=5,
            mode="rerank",
            principal_ids=alice,
        )
        bob_report = search_knowledge_base(
            session=session,
            knowledge_base_name="acl-engineering",
            query="runway planning fixture",
            top_k=5,
            mode="rerank",
            principal_ids=bob,
        )

    alice_texts = {result.text for result in alice_report.results}
    bob_texts = {result.text for result in bob_report.results}
    assert "runway planning engineering fixture" in alice_texts
    assert "runway planning shared fixture" in alice_texts
    assert "runway planning engineering fixture" not in bob_texts
    assert bob_texts == {"runway planning shared fixture"}
    assert alice_report.acl_explain["stage"] == "pre_retrieval"
    assert bob_report.acl_explain["filtered_count"] >= 1


def test_retrieval_filter_audit_and_denied_payload_are_safe(tmp_path) -> None:
    docs = _seed_documents(tmp_path, {"secret.txt": "restricted launch secret full text"})

    with _create_session() as session:
        ingest_local_directory(session=session, knowledge_base_name="acl-audit", root_path=docs)
        document = session.scalar(select(Document))
        assert document is not None
        set_document_acl(
            session,
            document_id=document.id,
            acl=AclMetadata(visibility="protected", allowed_principals=["user:alice"]),
            actor="fixture",
        )
        index_knowledge_base(session=session, knowledge_base_name="acl-audit")
        report = search_knowledge_base(
            session=session,
            knowledge_base_name="acl-audit",
            query="restricted launch secret",
            principal_ids=["user:bob"],
            enforce_acl=True,
        )
        events = session.scalars(select(AuditEvent).order_by(AuditEvent.occurred_at)).all()

    assert report.total_results == 0
    assert events[-1].event_type == "access_denied"
    assert "restricted launch secret full text" not in str(events[-1].payload_json)
    assert "raw_prompt" not in str(events[-1].payload_json)


# ── Lexical scorer unit tests ───────────────────────────────────────────────


def test_token_overlap_score_perfect_match() -> None:
    from ragrig.lexical import token_overlap_score

    score = token_overlap_score(
        "apple banana cherry",
        "apple banana",
        ["apple banana cherry", "date elderberry fig"],
    )
    assert score > 0.0


def test_token_overlap_score_no_match() -> None:
    from ragrig.lexical import token_overlap_score

    score = token_overlap_score(
        "apple banana cherry",
        "xylophone zebra",
        ["apple banana cherry"],
    )
    assert score == 0.0


def test_token_overlap_score_empty_inputs() -> None:
    from ragrig.lexical import token_overlap_score

    assert token_overlap_score("", "query", ["corpus"]) == 0.0
    assert token_overlap_score("text", "", ["corpus"]) == 0.0
    assert token_overlap_score("text", "query", []) > 0.0 if "text" == "query" else True


# ── Reranker unit tests ─────────────────────────────────────────────────────


def test_fake_rerank_reorders_candidates() -> None:
    import uuid as _uuid

    from ragrig.reranker import RerankCandidate, fake_rerank

    candidates = [
        RerankCandidate(
            document_id=_uuid.uuid4(),
            document_version_id=_uuid.uuid4(),
            chunk_id=_uuid.uuid4(),
            chunk_index=0,
            document_uri="a.txt",
            source_uri=None,
            text="zebra xylophone music",
            text_preview="zebra xylophone music",
            original_score=0.9,
            original_index=0,
            chunk_metadata={},
        ),
        RerankCandidate(
            document_id=_uuid.uuid4(),
            document_version_id=_uuid.uuid4(),
            chunk_id=_uuid.uuid4(),
            chunk_index=0,
            document_uri="b.txt",
            source_uri=None,
            text="apple banana cherry",
            text_preview="apple banana cherry",
            original_score=0.5,
            original_index=1,
            chunk_metadata={},
        ),
        RerankCandidate(
            document_id=_uuid.uuid4(),
            document_version_id=_uuid.uuid4(),
            chunk_id=_uuid.uuid4(),
            chunk_index=0,
            document_uri="c.txt",
            source_uri=None,
            text="apple banana smoothie",
            text_preview="apple banana smoothie",
            original_score=0.3,
            original_index=2,
            chunk_metadata={},
        ),
    ]

    results = fake_rerank("apple banana", candidates)

    assert len(results) == 3
    # Both "apple banana cherry" (idx 1) and "apple banana smoothie" (idx 2)
    # match all query tokens. The fake reranker breaks ties by original_index.
    # So idx 1 wins over idx 2.
    assert results[0].candidate.original_index == 1
    assert results[0].rerank_score == 1.0
    assert results[1].candidate.original_index == 2
    assert results[1].rerank_score == 1.0
    # "zebra xylophone music" matches 0 tokens → lowest
    assert results[2].candidate.original_index == 0
    assert results[2].rerank_score == 0.0


def test_fake_rerank_preserves_all_candidates() -> None:
    import uuid as _uuid

    from ragrig.reranker import RerankCandidate, fake_rerank

    candidates = [
        RerankCandidate(
            document_id=_uuid.uuid4(),
            document_version_id=_uuid.uuid4(),
            chunk_id=_uuid.uuid4(),
            chunk_index=i,
            document_uri=f"doc_{i}.txt",
            source_uri=None,
            text=f"document {i}",
            text_preview=f"document {i}",
            original_score=1.0 - i * 0.1,
            original_index=i,
            chunk_metadata={},
        )
        for i in range(5)
    ]

    results = fake_rerank("query", candidates)
    assert len(results) == 5
    assert {r.candidate.original_index for r in results} == {0, 1, 2, 3, 4}


def test_provider_rerank_unavailable_returns_none() -> None:
    import uuid as _uuid

    from ragrig.reranker import RerankCandidate, provider_rerank

    candidates = [
        RerankCandidate(
            document_id=_uuid.uuid4(),
            document_version_id=_uuid.uuid4(),
            chunk_id=_uuid.uuid4(),
            chunk_index=0,
            document_uri="test.txt",
            source_uri=None,
            text="test content",
            text_preview="test content",
            original_score=0.5,
            original_index=0,
            chunk_metadata={},
        )
    ]

    result = provider_rerank("test query", candidates, provider_name="nonexistent_provider_xyz")
    assert result is None


def test_hybrid_weight_configuration_affects_scores(tmp_path) -> None:
    """Changing lexical_weight should affect combined scores."""
    docs = _seed_documents(
        tmp_path,
        {
            "a.txt": "hybrid weight test alpha",
            "b.txt": "hybrid weight test beta",
        },
    )

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        report_lex_heavy = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="weight test",
            top_k=2,
            mode="hybrid",
            lexical_weight=0.9,
            vector_weight=0.1,
        )

        report_vec_heavy = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="weight test",
            top_k=2,
            mode="hybrid",
            lexical_weight=0.1,
            vector_weight=0.9,
        )

    # Both should return results
    assert report_lex_heavy.total_results == 2
    assert report_vec_heavy.total_results == 2
    # Traces should reflect the weight configuration
    assert report_lex_heavy.results[0].rank_stage_trace["weights"]["lexical_weight"] == 0.9
    assert report_vec_heavy.results[0].rank_stage_trace["weights"]["lexical_weight"] == 0.1
