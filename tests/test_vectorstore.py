from __future__ import annotations

import sys
import types
from uuid import uuid4

import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.config import Settings
from ragrig.db.models import (
    Base,
    Chunk,
    Document,
    DocumentVersion,
    Embedding,
    KnowledgeBase,
    Source,
)
from ragrig.vectorstore import (
    MissingVectorBackendDependencyError,
    VectorBackendConfigurationError,
    VectorCollection,
    VectorEmbeddingRecord,
    build_vector_collection,
    get_vector_backend,
    get_vector_backend_health,
)
from ragrig.vectorstore.pgvector import PgVectorBackend
from ragrig.vectorstore.qdrant import QdrantBackend, QdrantCollectionConfigError


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


def test_build_vector_collection_is_deterministic_and_bounded() -> None:
    first = build_vector_collection(
        knowledge_base_name="Finance / Ops / North America",
        provider="deterministic-local",
        model="hash-8d",
        dimensions=8,
    )
    second = build_vector_collection(
        knowledge_base_name="Finance / Ops / North America",
        provider="deterministic-local",
        model="hash-8d",
        dimensions=8,
    )

    assert first == second
    assert first.name.startswith("ragrig_")
    assert len(first.name) <= 63
    assert first.dimensions == 8
    assert first.provider == "deterministic-local"


def test_get_vector_backend_defaults_to_pgvector() -> None:
    backend = get_vector_backend(Settings())

    assert backend.backend_name == "pgvector"
    assert backend.distance_metric == "cosine"


def test_get_vector_backend_raises_clear_error_when_qdrant_dependency_missing(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "qdrant_client", None)

    with pytest.raises(MissingVectorBackendDependencyError, match="qdrant-client"):
        get_vector_backend(Settings(vector_backend="qdrant"))


def test_get_vector_backend_rejects_unknown_backend() -> None:
    with pytest.raises(VectorBackendConfigurationError, match="Unsupported"):
        get_vector_backend(Settings(vector_backend="unknown"))


def test_get_vector_backend_health_reports_degraded_when_qdrant_dependency_missing(
    monkeypatch,
) -> None:
    monkeypatch.setitem(sys.modules, "qdrant_client.http.models", None)
    monkeypatch.setitem(sys.modules, "qdrant_client", None)

    with _create_session() as session:
        health = get_vector_backend_health(session, Settings(vector_backend="qdrant"))

    assert health.backend == "qdrant"
    assert health.healthy is False
    assert health.status == "degraded"


def test_pgvector_backend_collection_and_health_cover_empty_session() -> None:
    backend = PgVectorBackend()
    collection = VectorCollection(
        name="ragrig_fixture_local_deterministic_local_hash_8d_8d_abcd1234",
        knowledge_base="fixture-local",
        provider="deterministic-local",
        model="hash-8d",
        dimensions=8,
    )

    with _create_session() as session:
        status = backend.ensure_collection(session, collection)
        assert backend.search(session, collection, query_vector=[0.0] * 8, top_k=3) == []
        assert backend.upsert_embeddings(session, collection, []) == []
        assert backend.delete_embeddings(session, collection, embedding_ids=[]) == 0
        health = backend.health(session)

    assert status.vector_count == 0
    assert health.backend == "pgvector"
    assert health.details["storage"] == "postgresql"


def test_pgvector_backend_search_and_delete_cover_non_empty_collection(tmp_path) -> None:
    backend = PgVectorBackend()
    with _create_session() as session:
        knowledge_base = KnowledgeBase(name="fixture-local", description=None, metadata_json={})
        source = Source(
            knowledge_base=knowledge_base,
            kind="local_directory",
            uri=str(tmp_path),
            config_json={},
        )
        document = Document(
            knowledge_base=knowledge_base,
            source=source,
            uri=str(tmp_path / "guide.txt"),
            content_hash="hash",
            mime_type="text/plain",
            metadata_json={},
        )
        version = DocumentVersion(
            document=document,
            version_number=1,
            content_hash="hash",
            parser_name="plaintext",
            parser_config_json={},
            extracted_text="guide text",
            metadata_json={},
        )
        chunk = Chunk(
            document_version=version,
            chunk_index=0,
            text="guide text",
            char_start=0,
            char_end=10,
            metadata_json={},
        )
        embedding = Embedding(
            chunk=chunk,
            provider="deterministic-local",
            model="hash-8d",
            dimensions=8,
            embedding=[0.25] * 8,
            metadata_json={},
        )
        session.add_all([knowledge_base, source, document, version, chunk, embedding])
        session.commit()
        collection = VectorCollection(
            name="ragrig_fixture_local_deterministic_local_hash_8d_8d_abcd1234",
            knowledge_base="fixture-local",
            provider="deterministic-local",
            model="hash-8d",
            dimensions=8,
            knowledge_base_id=document.knowledge_base_id,
        )

        status = backend.ensure_collection(session, collection)
        hits = backend.search(session, collection, query_vector=[0.25] * 8, top_k=1)
        deleted = backend.delete_embeddings(
            session,
            collection,
            embedding_ids=[embedding.id],
        )

    assert status.vector_count == 1
    assert hits[0].embedding_id == embedding.id
    assert hits[0].score == 1.0
    assert deleted == 1


def test_qdrant_backend_create_path_requires_optional_dependency_when_no_client() -> None:
    with pytest.raises(MissingVectorBackendDependencyError, match="qdrant-client"):
        QdrantBackend(url="http://localhost:6333", api_key=None)


def test_qdrant_backend_constructor_and_operations_cover_sdk_path(monkeypatch) -> None:
    class FakeQdrantClient:
        def __init__(self, *, url: str, api_key: str | None) -> None:
            self.url = url
            self.api_key = api_key
            self.collections: dict[str, dict[str, object]] = {}
            self.deleted: list[str] = []

        def get_collections(self):
            return types.SimpleNamespace(
                collections=[types.SimpleNamespace(name=name) for name in self.collections]
            )

        def create_collection(self, collection_name: str, vectors_config) -> None:
            self.collections[collection_name] = {
                "size": vectors_config.size,
                "distance": vectors_config.distance,
            }

        def get_collection(self, collection_name: str):
            item = self.collections[collection_name]
            return types.SimpleNamespace(
                config=types.SimpleNamespace(
                    params=types.SimpleNamespace(
                        vectors=types.SimpleNamespace(
                            size=item["size"],
                            distance=item["distance"],
                        )
                    )
                ),
                points_count=0,
            )

        def upsert(self, collection_name: str, points) -> None:
            self.collections[collection_name]["points"] = list(points)

        def delete(self, collection_name: str, points_selector) -> None:
            del collection_name
            self.deleted.extend(points_selector.points)

        def search(self, collection_name: str, query_vector, limit: int, query_filter=None):
            del collection_name, query_vector, limit, query_filter
            return []

    class FakeDistance:
        COSINE = "Cosine"

    class FakePointIdsList:
        def __init__(self, *, points: list[str]) -> None:
            self.points = points

    class FakePointStruct:
        def __init__(self, *, id: str, vector: list[float], payload: dict[str, object]) -> None:
            self.id = id
            self.vector = vector
            self.payload = payload

    class FakeVectorParams:
        def __init__(self, *, size: int, distance: str) -> None:
            self.size = size
            self.distance = distance

    fake_qdrant_module = types.SimpleNamespace(QdrantClient=FakeQdrantClient)
    fake_models_module = types.SimpleNamespace(
        Distance=FakeDistance,
        PointIdsList=FakePointIdsList,
        PointStruct=FakePointStruct,
        VectorParams=FakeVectorParams,
    )
    monkeypatch.setitem(sys.modules, "qdrant_client", fake_qdrant_module)
    monkeypatch.setitem(sys.modules, "qdrant_client.http.models", fake_models_module)

    backend = QdrantBackend(url="http://localhost:6333", api_key="token")
    collection = VectorCollection(
        name="ragrig_fixture_local_deterministic_local_hash_8d_8d_abcd1234",
        knowledge_base="fixture-local",
        provider="deterministic-local",
        model="hash-8d",
        dimensions=8,
    )
    record = VectorEmbeddingRecord(
        embedding_id=uuid4(),
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        chunk_index=0,
        vector=[0.1] * 8,
        text="fixture text",
        metadata={},
    )

    with _create_session() as session:
        backend.ensure_collection(session, collection)
        backend.upsert_embeddings(session, collection, [record])
        deleted = backend.delete_embeddings(
            session,
            collection,
            embedding_ids=[record.embedding_id],
        )

    assert backend.client.api_key == "token"
    assert deleted == 1


def test_qdrant_backend_upsert_and_search_use_fake_client() -> None:
    class FakeCollectionsResponse:
        def __init__(self, names: list[str]) -> None:
            self.collections = [types.SimpleNamespace(name=name) for name in names]

    class FakeCollectionInfo:
        def __init__(self, size: int, distance: str, count: int) -> None:
            self.config = types.SimpleNamespace(
                params=types.SimpleNamespace(
                    vectors=types.SimpleNamespace(size=size, distance=distance)
                )
            )
            self.points_count = count

    class FakeHit:
        def __init__(self, point_id: str, score: float, payload: dict[str, object]) -> None:
            self.id = point_id
            self.score = score
            self.payload = payload

    class FakeClient:
        def __init__(self) -> None:
            self.collections: dict[str, dict[str, object]] = {}
            self.points: dict[str, dict[str, object]] = {}

        def get_collections(self):
            return FakeCollectionsResponse(list(self.collections))

        def create_collection(self, collection_name: str, vectors_config) -> None:
            self.collections[collection_name] = {
                "size": vectors_config.size,
                "distance": vectors_config.distance,
            }

        def get_collection(self, collection_name: str):
            metadata = self.collections[collection_name]
            count = len(
                [point for point in self.points.values() if point["collection"] == collection_name]
            )
            return FakeCollectionInfo(metadata["size"], metadata["distance"], count)

        def upsert(self, collection_name: str, points) -> None:
            for point in points:
                self.points[str(point.id)] = {
                    "collection": collection_name,
                    "vector": list(point.vector),
                    "payload": dict(point.payload),
                }

        def delete(self, collection_name: str, points_selector) -> None:
            for point_id in list(points_selector.points):
                point = self.points.get(str(point_id))
                if point and point["collection"] == collection_name:
                    del self.points[str(point_id)]

        def search(self, collection_name: str, query_vector, limit: int, query_filter=None):
            del query_filter
            hits: list[FakeHit] = []
            for point_id, point in self.points.items():
                if point["collection"] != collection_name:
                    continue
                score = 1.0 if point["vector"] == list(query_vector) else 0.5
                hits.append(FakeHit(point_id, score, point["payload"]))
            hits.sort(key=lambda item: item.score, reverse=True)
            return hits[:limit]

    backend = QdrantBackend(
        url="http://localhost:6333",
        api_key=None,
        client=FakeClient(),
    )
    collection = VectorCollection(
        name="ragrig_fixture_local_deterministic_local_hash_8d_8d_abcd1234",
        knowledge_base="fixture-local",
        provider="deterministic-local",
        model="hash-8d",
        dimensions=8,
    )
    embedding_id = uuid4()
    record = VectorEmbeddingRecord(
        embedding_id=embedding_id,
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        chunk_index=0,
        vector=[0.1] * 8,
        text="fixture text",
        metadata={"document_uri": "/tmp/guide.txt"},
    )

    with _create_session() as session:
        status = backend.ensure_collection(session, collection)
        inserted = backend.upsert_embeddings(session, collection, [record])
        hits = backend.search(session, collection, query_vector=[0.1] * 8, top_k=1)
        assert backend.delete_embeddings(session, collection, embedding_ids=[]) == 0
        deleted = backend.delete_embeddings(session, collection, embedding_ids=[embedding_id])
        health = backend.health(session)

    assert status.dimensions == 8
    assert inserted == [embedding_id]
    assert hits[0].embedding_id == embedding_id
    assert hits[0].score == 1.0
    assert hits[0].distance == 0.0
    assert deleted == 1
    assert health.backend == "qdrant"
    assert health.healthy is True


def test_qdrant_backend_search_uses_query_points_when_search_api_is_unavailable() -> None:
    class FakeCollectionsResponse:
        def __init__(self, names: list[str]) -> None:
            self.collections = [types.SimpleNamespace(name=name) for name in names]

    class FakeCollectionInfo:
        def __init__(self, size: int, distance: str, count: int) -> None:
            self.config = types.SimpleNamespace(
                params=types.SimpleNamespace(
                    vectors=types.SimpleNamespace(size=size, distance=distance)
                )
            )
            self.points_count = count

    class FakeHit:
        def __init__(self, point_id: str, score: float, payload: dict[str, object]) -> None:
            self.id = point_id
            self.score = score
            self.payload = payload

    class FakeClient:
        def __init__(self) -> None:
            self.collections: dict[str, dict[str, object]] = {}
            self.points: dict[str, dict[str, object]] = {}

        def get_collections(self):
            return FakeCollectionsResponse(list(self.collections))

        def create_collection(self, collection_name: str, vectors_config) -> None:
            self.collections[collection_name] = {
                "size": vectors_config.size,
                "distance": vectors_config.distance,
            }

        def get_collection(self, collection_name: str):
            metadata = self.collections[collection_name]
            count = len(
                [point for point in self.points.values() if point["collection"] == collection_name]
            )
            return FakeCollectionInfo(metadata["size"], metadata["distance"], count)

        def upsert(self, collection_name: str, points) -> None:
            for point in points:
                self.points[str(point.id)] = {
                    "collection": collection_name,
                    "vector": list(point.vector),
                    "payload": dict(point.payload),
                }

        def query_points(
            self,
            *,
            collection_name: str,
            query,
            limit: int,
            query_filter=None,
            with_payload: bool,
            with_vectors: bool,
        ):
            del query_filter, with_payload, with_vectors
            hits: list[FakeHit] = []
            for point_id, point in self.points.items():
                if point["collection"] != collection_name:
                    continue
                score = 1.0 if point["vector"] == list(query) else 0.5
                hits.append(FakeHit(point_id, score, point["payload"]))
            hits.sort(key=lambda item: item.score, reverse=True)
            return types.SimpleNamespace(points=hits[:limit])

    backend = QdrantBackend(
        url="http://localhost:6333",
        api_key=None,
        client=FakeClient(),
    )
    collection = VectorCollection(
        name="ragrig_fixture_local_deterministic_local_hash_8d_8d_abcd1234",
        knowledge_base="fixture-local",
        provider="deterministic-local",
        model="hash-8d",
        dimensions=8,
    )
    embedding_id = uuid4()
    record = VectorEmbeddingRecord(
        embedding_id=embedding_id,
        chunk_id=uuid4(),
        document_id=uuid4(),
        document_version_id=uuid4(),
        chunk_index=0,
        vector=[0.1] * 8,
        text="fixture text",
        metadata={"document_uri": "/tmp/guide.txt"},
    )

    with _create_session() as session:
        backend.ensure_collection(session, collection)
        backend.upsert_embeddings(session, collection, [record])
        hits = backend.search(session, collection, query_vector=[0.1] * 8, top_k=1)

    assert hits[0].embedding_id == embedding_id
    assert hits[0].score == 1.0
    assert hits[0].distance == 0.0


def test_qdrant_backend_rejects_dimension_mismatch() -> None:
    class FakeCollectionsResponse:
        collections = [types.SimpleNamespace(name="existing")]

    class FakeCollectionInfo:
        def __init__(self) -> None:
            self.config = types.SimpleNamespace(
                params=types.SimpleNamespace(
                    vectors=types.SimpleNamespace(size=16, distance="Cosine")
                )
            )
            self.points_count = 0

    class FakeClient:
        def get_collections(self):
            return FakeCollectionsResponse()

        def get_collection(self, _collection_name: str):
            return FakeCollectionInfo()

    backend = QdrantBackend(url="http://localhost:6333", api_key=None, client=FakeClient())
    collection = VectorCollection(
        name="existing",
        knowledge_base="fixture-local",
        provider="deterministic-local",
        model="hash-8d",
        dimensions=8,
    )

    with _create_session() as session:
        with pytest.raises(QdrantCollectionConfigError, match="dimensions"):
            backend.ensure_collection(session, collection)
