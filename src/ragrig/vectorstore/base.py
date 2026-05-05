from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import func, select
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


def summarize_vector_profile_value(values: list[str]) -> str:
    unique_values = sorted({value for value in values if value})
    if not unique_values:
        return "Unavailable from status API"
    if len(unique_values) == 1:
        return unique_values[0]
    return "Multiple profiles"


def sanitize_url(value: str | None) -> str | None:
    if not value:
        return value
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        return value
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def list_embedding_profiles(session: Session) -> list[dict[str, Any]]:
    from ragrig.db.models import Chunk, Document, DocumentVersion, Embedding, KnowledgeBase

    latest_version_numbers = (
        select(
            DocumentVersion.document_id.label("document_id"),
            func.max(DocumentVersion.version_number).label("version_number"),
        )
        .group_by(DocumentVersion.document_id)
        .subquery()
    )
    latest_versions = (
        select(
            DocumentVersion.id.label("document_version_id"),
            DocumentVersion.document_id.label("document_id"),
        )
        .join(
            latest_version_numbers,
            (DocumentVersion.document_id == latest_version_numbers.c.document_id)
            & (DocumentVersion.version_number == latest_version_numbers.c.version_number),
        )
        .subquery()
    )
    rows = session.execute(
        select(
            KnowledgeBase.id.label("knowledge_base_id"),
            KnowledgeBase.name.label("knowledge_base_name"),
            Embedding.provider.label("provider"),
            Embedding.model.label("model"),
            Embedding.dimensions.label("dimensions"),
            func.count(Embedding.id).label("vector_count"),
        )
        .join(Document, Document.knowledge_base_id == KnowledgeBase.id)
        .join(latest_versions, latest_versions.c.document_id == Document.id)
        .join(Chunk, Chunk.document_version_id == latest_versions.c.document_version_id)
        .join(Embedding, Embedding.chunk_id == Chunk.id)
        .group_by(
            KnowledgeBase.id,
            KnowledgeBase.name,
            Embedding.provider,
            Embedding.model,
            Embedding.dimensions,
        )
        .order_by(KnowledgeBase.name, Embedding.provider, Embedding.model, Embedding.dimensions)
    ).all()
    return [
        {
            "knowledge_base_id": row.knowledge_base_id,
            "knowledge_base_name": row.knowledge_base_name,
            "provider": row.provider,
            "model": row.model,
            "dimensions": int(row.dimensions),
            "vector_count": int(row.vector_count or 0),
        }
        for row in rows
    ]


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
    "list_embedding_profiles",
    "sanitize_url",
    "summarize_vector_profile_value",
]
