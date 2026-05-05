from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from ragrig.vectorstore.base import (
    MissingVectorBackendDependencyError,
    VectorBackendHealth,
    VectorCollection,
    VectorCollectionStatus,
    VectorEmbeddingRecord,
    VectorSearchResult,
    build_vector_collection,
    list_embedding_profiles,
    sanitize_url,
    summarize_vector_profile_value,
)


class QdrantCollectionConfigError(RuntimeError):
    pass


def _load_qdrant_models() -> tuple[Any, Any, Any, Any]:
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.http.models import Distance, PointIdsList, PointStruct, VectorParams
    except ImportError as exc:  # pragma: no cover - exercised by import guard tests
        raise MissingVectorBackendDependencyError(
            "qdrant-client is required for VECTOR_BACKEND=qdrant"
        ) from exc
    return QdrantClient, Distance, PointIdsList, PointStruct, VectorParams


class _FallbackDistance:
    COSINE = "Cosine"


class _FallbackPointIdsList:
    def __init__(self, *, points: list[str]) -> None:
        self.points = points


class _FallbackPointStruct:
    def __init__(self, *, id: str, vector: list[float], payload: dict[str, Any]) -> None:
        self.id = id
        self.vector = vector
        self.payload = payload


class _FallbackVectorParams:
    def __init__(self, *, size: int, distance: str) -> None:
        self.size = size
        self.distance = distance


class QdrantBackend:
    backend_name = "qdrant"
    distance_metric = "cosine"

    def __init__(self, *, url: str, api_key: str | None, client: Any | None = None) -> None:
        self.url = url
        self.api_key = api_key
        self._use_fallback_models = client is not None
        if client is None:
            qdrant_client, _, _, _, _ = _load_qdrant_models()
            client = qdrant_client(url=url, api_key=api_key)
        self.client = client

    def _collections(self) -> set[str]:
        return {collection.name for collection in self.client.get_collections().collections}

    def ensure_collection(
        self, session: Session, collection: VectorCollection
    ) -> VectorCollectionStatus:
        del session
        if self._use_fallback_models:
            distance_enum = _FallbackDistance
            vector_params = _FallbackVectorParams
        else:
            _, distance_enum, _, _, vector_params = _load_qdrant_models()
        exists = collection.name in self._collections()
        if not exists:
            self.client.create_collection(
                collection_name=collection.name,
                vectors_config=vector_params(
                    size=collection.dimensions, distance=distance_enum.COSINE
                ),
            )
        info = self.client.get_collection(collection.name)
        size = info.config.params.vectors.size
        distance = str(info.config.params.vectors.distance)
        if int(size) != collection.dimensions:
            raise QdrantCollectionConfigError(
                "Qdrant collection dimensions mismatch: "
                f"expected {collection.dimensions}, got {size}"
            )
        return VectorCollectionStatus(
            name=collection.name,
            exists=True,
            dimensions=int(size),
            distance_metric=self.distance_metric,
            vector_count=int(getattr(info, "points_count", 0) or 0),
            backend=self.backend_name,
            metadata={"distance": distance},
        )

    def upsert_embeddings(
        self,
        session: Session,
        collection: VectorCollection,
        records: list[VectorEmbeddingRecord],
    ) -> list[uuid.UUID]:
        del session
        if self._use_fallback_models:
            point_struct = _FallbackPointStruct
        else:
            _, _, _, point_struct, _ = _load_qdrant_models()
        self.client.upsert(
            collection_name=collection.name,
            points=[
                point_struct(
                    id=str(record.embedding_id),
                    vector=record.vector,
                    payload={
                        **record.metadata,
                        "chunk_id": str(record.chunk_id),
                        "document_id": str(record.document_id),
                        "document_version_id": str(record.document_version_id),
                        "chunk_index": record.chunk_index,
                        "text": record.text,
                    },
                )
                for record in records
            ],
        )
        return [record.embedding_id for record in records]

    def delete_embeddings(
        self,
        session: Session,
        collection: VectorCollection,
        *,
        embedding_ids: list[uuid.UUID],
    ) -> int:
        del session
        if not embedding_ids:
            return 0
        if self._use_fallback_models:
            point_ids_list = _FallbackPointIdsList
        else:
            _, _, point_ids_list, _, _ = _load_qdrant_models()
        self.client.delete(
            collection_name=collection.name,
            points_selector=point_ids_list(
                points=[str(embedding_id) for embedding_id in embedding_ids]
            ),
        )
        return len(embedding_ids)

    def search(
        self,
        session: Session,
        collection: VectorCollection,
        *,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        del session
        if hasattr(self.client, "search"):
            hits = self.client.search(
                collection_name=collection.name,
                query_vector=query_vector,
                limit=top_k,
                query_filter=filters,
            )
        else:
            response = self.client.query_points(
                collection_name=collection.name,
                query=query_vector,
                limit=top_k,
                query_filter=filters,
                with_payload=True,
                with_vectors=False,
            )
            hits = response.points
        return [
            VectorSearchResult(
                embedding_id=uuid.UUID(str(hit.id)),
                chunk_id=uuid.UUID(hit.payload["chunk_id"]),
                document_id=uuid.UUID(hit.payload["document_id"]),
                document_version_id=uuid.UUID(hit.payload["document_version_id"]),
                chunk_index=int(hit.payload["chunk_index"]),
                text=str(hit.payload["text"]),
                score=round(float(hit.score), 6),
                distance=round(1.0 - float(hit.score), 6),
                metadata={
                    key: value
                    for key, value in hit.payload.items()
                    if key
                    not in {
                        "chunk_id",
                        "document_id",
                        "document_version_id",
                        "chunk_index",
                        "text",
                    }
                },
            )
            for hit in hits
        ]

    def health(self, session: Session) -> VectorBackendHealth:
        profiles = list_embedding_profiles(session)
        live_collections = {
            collection.name: self.client.get_collection(collection.name)
            for collection in self.client.get_collections().collections
        }
        collections: list[VectorCollectionStatus] = []
        for profile in profiles:
            collection = build_vector_collection(
                knowledge_base_name=profile["knowledge_base_name"],
                provider=profile["provider"],
                model=profile["model"],
                dimensions=profile["dimensions"],
            )
            info = live_collections.get(collection.name)
            if info is None:
                collections.append(
                    VectorCollectionStatus(
                        name=collection.name,
                        exists=False,
                        dimensions=profile["dimensions"],
                        distance_metric=self.distance_metric,
                        vector_count=0,
                        backend=self.backend_name,
                        metadata={
                            "provider": profile["provider"],
                            "model": profile["model"],
                            "knowledge_base": profile["knowledge_base_name"],
                            "unavailable_reason": f"Collection not found: {collection.name}.",
                        },
                    )
                )
                continue
            size = int(info.config.params.vectors.size)
            distance = str(info.config.params.vectors.distance)
            metadata = {
                "provider": profile["provider"],
                "model": profile["model"],
                "knowledge_base": profile["knowledge_base_name"],
                "expected_dimensions": profile["dimensions"],
                "actual_dimensions": size,
                "collection_url": sanitize_url(
                    f"{self.url.rstrip('/')}/collections/{collection.name}"
                ),
            }
            if size != int(profile["dimensions"]):
                metadata["unavailable_reason"] = (
                    f"Dimension mismatch: expected {profile['dimensions']}, got {size}."
                )
            collections.append(
                VectorCollectionStatus(
                    name=collection.name,
                    exists=True,
                    dimensions=size,
                    distance_metric=self.distance_metric,
                    vector_count=int(getattr(info, "points_count", 0) or 0),
                    backend=self.backend_name,
                    metadata=metadata | {"distance": distance},
                )
            )
        provider = summarize_vector_profile_value([profile["provider"] for profile in profiles])
        model = summarize_vector_profile_value([profile["model"] for profile in profiles])
        total_vectors = sum(item.vector_count for item in collections) if collections else None
        errors = [
            item.metadata.get("unavailable_reason")
            for item in collections
            if item.metadata.get("unavailable_reason")
        ]
        healthy = not errors
        return VectorBackendHealth(
            backend=self.backend_name,
            healthy=healthy,
            status="healthy" if healthy else "degraded",
            distance_metric=self.distance_metric,
            collections=collections,
            details={
                "url": sanitize_url(self.url),
                "dependency_status": "ready",
                "provider": provider,
                "model": model,
                "total_vectors": total_vectors,
                "score_semantics": (
                    "Qdrant uses cosine similarity; retrieval distance is 1 - score."
                ),
                "error": errors[0] if errors else None,
            },
        )


__all__ = ["QdrantBackend", "QdrantCollectionConfigError"]
