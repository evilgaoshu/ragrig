from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.orm import Session


class MissingVectorBackendDependencyError(RuntimeError):
    pass


class VectorBackendConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class VectorCollection:
    name: str
    knowledge_base: str
    provider: str
    model: str
    dimensions: int
    knowledge_base_id: uuid.UUID | None = None


@dataclass(frozen=True)
class VectorEmbeddingRecord:
    embedding_id: uuid.UUID
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_index: int
    vector: list[float]
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class VectorSearchResult:
    embedding_id: uuid.UUID
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_index: int
    text: str
    score: float
    distance: float
    metadata: dict[str, Any]


@dataclass(frozen=True)
class VectorCollectionStatus:
    name: str
    exists: bool
    dimensions: int
    distance_metric: str
    vector_count: int
    backend: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorBackendHealth:
    backend: str
    healthy: bool
    status: str
    distance_metric: str
    collections: list[VectorCollectionStatus] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


class VectorBackend(Protocol):
    backend_name: str
    distance_metric: str

    def ensure_collection(
        self, session: Session, collection: VectorCollection
    ) -> VectorCollectionStatus: ...

    def upsert_embeddings(
        self,
        session: Session,
        collection: VectorCollection,
        records: list[VectorEmbeddingRecord],
    ) -> list[uuid.UUID]: ...

    def delete_embeddings(
        self,
        session: Session,
        collection: VectorCollection,
        *,
        embedding_ids: list[uuid.UUID],
    ) -> int: ...

    def search(
        self,
        session: Session,
        collection: VectorCollection,
        *,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]: ...

    def health(self, session: Session) -> VectorBackendHealth: ...


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized or "na"


def build_vector_collection(
    *,
    knowledge_base_name: str,
    provider: str,
    model: str,
    dimensions: int,
) -> VectorCollection:
    raw = "|".join([knowledge_base_name, provider, model, str(dimensions)])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    prefix = "_".join(
        [
            "ragrig",
            _slug(knowledge_base_name)[:16],
            _slug(provider)[:16],
            _slug(model)[:16],
            f"{dimensions}d",
        ]
    )
    name = f"{prefix}_{digest}"[:63]
    return VectorCollection(
        name=name,
        knowledge_base=knowledge_base_name,
        provider=provider,
        model=model,
        dimensions=dimensions,
    )


__all__ = [
    "MissingVectorBackendDependencyError",
    "VectorBackend",
    "VectorBackendConfigurationError",
    "VectorBackendHealth",
    "VectorCollection",
    "VectorCollectionStatus",
    "VectorEmbeddingRecord",
    "VectorSearchResult",
    "build_vector_collection",
]
