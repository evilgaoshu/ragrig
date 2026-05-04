from __future__ import annotations

from sqlalchemy.orm import Session

from ragrig.config import Settings
from ragrig.vectorstore.base import (
    MissingVectorBackendDependencyError,
    VectorBackend,
    VectorBackendConfigurationError,
    VectorBackendHealth,
    VectorCollection,
    VectorCollectionStatus,
    VectorEmbeddingRecord,
    VectorSearchResult,
    build_vector_collection,
)
from ragrig.vectorstore.pgvector import PgVectorBackend, cosine_distance, normalize_vector
from ragrig.vectorstore.qdrant import QdrantBackend


def get_vector_backend(settings: Settings) -> VectorBackend:
    if settings.vector_backend == "pgvector":
        return PgVectorBackend()
    if settings.vector_backend == "qdrant":
        return QdrantBackend(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    raise VectorBackendConfigurationError(f"Unsupported vector backend: {settings.vector_backend}")


def get_vector_backend_health(session: Session, settings: Settings) -> VectorBackendHealth:
    try:
        backend = get_vector_backend(settings)
    except MissingVectorBackendDependencyError as exc:
        return VectorBackendHealth(
            backend=settings.vector_backend,
            healthy=False,
            status="degraded",
            distance_metric="cosine",
            details={"error": str(exc)},
        )
    return backend.health(session)


__all__ = [
    "MissingVectorBackendDependencyError",
    "PgVectorBackend",
    "QdrantBackend",
    "VectorBackend",
    "VectorBackendConfigurationError",
    "VectorBackendHealth",
    "VectorCollection",
    "VectorCollectionStatus",
    "VectorEmbeddingRecord",
    "VectorSearchResult",
    "build_vector_collection",
    "cosine_distance",
    "get_vector_backend",
    "get_vector_backend_health",
    "normalize_vector",
]
