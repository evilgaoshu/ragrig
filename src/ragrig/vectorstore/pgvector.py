from __future__ import annotations

import math
import uuid
from typing import Any

from sqlalchemy import Select, delete, func, select
from sqlalchemy.orm import Session

from ragrig.db.models import Chunk, Document, DocumentVersion, Embedding, Source
from ragrig.vectorstore.base import (
    VectorBackendHealth,
    VectorCollection,
    VectorCollectionStatus,
    VectorEmbeddingRecord,
    VectorSearchResult,
    build_vector_collection,
    list_embedding_profiles,
    summarize_vector_profile_value,
)


def normalize_vector(raw: Any) -> list[float]:
    return [float(value) for value in raw]


def cosine_distance(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 1.0
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 1.0
    similarity = numerator / (left_norm * right_norm)
    similarity = max(min(similarity, 1.0), -1.0)
    return round(1.0 - similarity, 6)


def latest_version_subquery(knowledge_base_id) -> Any:
    latest_version_numbers = (
        select(
            DocumentVersion.document_id.label("document_id"),
            func.max(DocumentVersion.version_number).label("version_number"),
        )
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.knowledge_base_id == knowledge_base_id)
        .group_by(DocumentVersion.document_id)
        .subquery()
    )
    return (
        select(
            DocumentVersion.document_id.label("document_id"),
            DocumentVersion.id.label("document_version_id"),
            DocumentVersion.version_number.label("version_number"),
        )
        .join(Document, Document.id == DocumentVersion.document_id)
        .join(
            latest_version_numbers,
            (DocumentVersion.document_id == latest_version_numbers.c.document_id)
            & (DocumentVersion.version_number == latest_version_numbers.c.version_number),
        )
        .subquery()
    )


def build_embedding_base_statement(
    *,
    knowledge_base_id,
    provider: str,
    model: str,
    dimensions: int,
    workspace_id=None,
) -> Select[Any]:
    latest_versions = latest_version_subquery(knowledge_base_id)
    stmt = (
        select(
            Embedding.id.label("embedding_id"),
            Document.id.label("document_id"),
            DocumentVersion.id.label("document_version_id"),
            Chunk.id.label("chunk_id"),
            Chunk.chunk_index.label("chunk_index"),
            Document.uri.label("document_uri"),
            Source.uri.label("source_uri"),
            Chunk.text.label("text"),
            Chunk.metadata_json.label("chunk_metadata"),
            Embedding.embedding.label("embedding"),
        )
        .join(Chunk, Chunk.id == Embedding.chunk_id)
        .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .join(Source, Source.id == Document.source_id)
        .join(latest_versions, latest_versions.c.document_version_id == DocumentVersion.id)
        .where(
            Document.knowledge_base_id == knowledge_base_id,
            Embedding.provider == provider,
            Embedding.model == model,
            Embedding.dimensions == dimensions,
        )
    )
    if workspace_id is not None:
        stmt = stmt.where(Chunk.workspace_id == workspace_id)
    return stmt


class PgVectorBackend:
    backend_name = "pgvector"
    distance_metric = "cosine"

    def ensure_collection(
        self, session: Session, collection: VectorCollection
    ) -> VectorCollectionStatus:
        if collection.knowledge_base_id is None:
            vector_count = 0
        else:
            vector_count = session.scalar(
                select(func.count(Embedding.id))
                .join(Chunk, Chunk.id == Embedding.chunk_id)
                .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(
                    Document.knowledge_base_id == collection.knowledge_base_id,
                    Embedding.provider == collection.provider,
                    Embedding.model == collection.model,
                    Embedding.dimensions == collection.dimensions,
                )
            )
        return VectorCollectionStatus(
            name=collection.name,
            exists=True,
            dimensions=collection.dimensions,
            distance_metric=self.distance_metric,
            vector_count=int(vector_count or 0),
            backend=self.backend_name,
            metadata={"storage": "postgresql"},
        )

    def upsert_embeddings(
        self,
        session: Session,
        collection: VectorCollection,
        records: list[VectorEmbeddingRecord],
    ) -> list[uuid.UUID]:
        del session, collection
        return [record.embedding_id for record in records]

    def delete_embeddings(
        self,
        session: Session,
        collection: VectorCollection,
        *,
        embedding_ids: list[uuid.UUID],
    ) -> int:
        del collection
        if not embedding_ids:
            return 0
        result = session.execute(delete(Embedding).where(Embedding.id.in_(embedding_ids)))
        return int(result.rowcount or 0)

    def search(
        self,
        session: Session,
        collection: VectorCollection,
        *,
        query_vector: list[float],
        top_k: int,
        filters: dict[str, Any] | None = None,
    ) -> list[VectorSearchResult]:
        del filters
        if collection.knowledge_base_id is None:
            return []
        statement = build_embedding_base_statement(
            knowledge_base_id=collection.knowledge_base_id,
            provider=collection.provider,
            model=collection.model,
            dimensions=collection.dimensions,
        )
        rows = session.execute(statement).all()
        ranked = sorted(
            rows,
            key=lambda row: (
                cosine_distance(normalize_vector(row.embedding), query_vector),
                row.chunk_index,
            ),
        )[:top_k]
        return [
            VectorSearchResult(
                embedding_id=row.embedding_id,
                chunk_id=row.chunk_id,
                document_id=row.document_id,
                document_version_id=row.document_version_id,
                chunk_index=row.chunk_index,
                text=row.text,
                score=round(
                    1.0 - cosine_distance(normalize_vector(row.embedding), query_vector), 6
                ),
                distance=cosine_distance(normalize_vector(row.embedding), query_vector),
                metadata={
                    "document_uri": row.document_uri,
                    "source_uri": row.source_uri,
                    "chunk_metadata": row.chunk_metadata,
                },
            )
            for row in ranked
        ]

    def health(self, session: Session) -> VectorBackendHealth:
        dialect = session.bind.dialect.name if session.bind is not None else "unknown"
        profiles = list_embedding_profiles(session)
        collections = []
        for profile in profiles:
            collection = build_vector_collection(
                knowledge_base_name=profile["knowledge_base_name"],
                provider=profile["provider"],
                model=profile["model"],
                dimensions=profile["dimensions"],
            )
            collections.append(
                VectorCollectionStatus(
                    name=collection.name,
                    exists=True,
                    dimensions=profile["dimensions"],
                    distance_metric=self.distance_metric,
                    vector_count=profile["vector_count"],
                    backend=self.backend_name,
                    metadata={
                        "storage": "postgresql",
                        "provider": profile["provider"],
                        "model": profile["model"],
                        "knowledge_base": profile["knowledge_base_name"],
                        "table": "embeddings",
                        "index_type": "sql_cosine_distance",
                    },
                )
            )
        provider = summarize_vector_profile_value([profile["provider"] for profile in profiles])
        model = summarize_vector_profile_value([profile["model"] for profile in profiles])
        total_vectors = sum(profile["vector_count"] for profile in profiles)
        return VectorBackendHealth(
            backend=self.backend_name,
            healthy=True,
            status="healthy",
            distance_metric=self.distance_metric,
            collections=collections,
            details={
                "dialect": dialect,
                "storage": "postgresql",
                "dependency_status": "ready",
                "provider": provider,
                "model": model,
                "total_vectors": total_vectors if collections else None,
                "score_semantics": (
                    "pgvector uses cosine distance; retrieval score is 1 - distance."
                ),
                "error": None,
            },
        )


__all__ = [
    "PgVectorBackend",
    "build_embedding_base_statement",
    "cosine_distance",
    "latest_version_subquery",
    "normalize_vector",
]
