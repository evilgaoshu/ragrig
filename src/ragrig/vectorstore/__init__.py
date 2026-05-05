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
    sanitize_url,
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
            collections=[],
            details={
                "dependency_status": "missing dependency",
                "provider": "Unavailable from status API",
                "model": "Unavailable from status API",
                "total_vectors": None,
                "score_semantics": (
                    "Qdrant uses cosine similarity; retrieval distance is 1 - score."
                ),
                "error": "Missing dependency: qdrant-client is not installed.",
                "exception": str(exc),
            },
        )
    try:
        return backend.health(session)
    except VectorBackendConfigurationError as exc:
        return VectorBackendHealth(
            backend=settings.vector_backend,
            healthy=False,
            status="error",
            distance_metric="cosine",
            collections=[],
            details={
                "dependency_status": "not configured",
                "provider": "Unavailable from status API",
                "model": "Unavailable from status API",
                "total_vectors": None,
                "score_semantics": None,
                "error": str(exc),
            },
        )
    except Exception as exc:
        score_semantics = None
        if settings.vector_backend == "qdrant":
            score_semantics = "Qdrant uses cosine similarity; retrieval distance is 1 - score."
        elif settings.vector_backend == "pgvector":
            score_semantics = "pgvector uses cosine distance; retrieval score is 1 - distance."
        return VectorBackendHealth(
            backend=settings.vector_backend,
            healthy=False,
            status="error",
            distance_metric="cosine",
            collections=[],
            details={
                "dependency_status": (
                    "unreachable" if settings.vector_backend == "qdrant" else "error"
                ),
                "provider": "Unavailable from status API",
                "model": "Unavailable from status API",
                "total_vectors": None,
                "score_semantics": score_semantics,
                "error": str(exc),
                "url": sanitize_url(settings.qdrant_url)
                if settings.vector_backend == "qdrant"
                else None,
            },
        )


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
