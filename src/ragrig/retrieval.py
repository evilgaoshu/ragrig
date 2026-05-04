from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from ragrig.db.models import Chunk, Document, DocumentVersion, Embedding, KnowledgeBase, Source
from ragrig.providers import get_provider_registry
from ragrig.repositories import get_knowledge_base_by_name


class RetrievalError(ValueError):
    code = "retrieval_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class KnowledgeBaseNotFoundError(RetrievalError):
    code = "knowledge_base_not_found"


class EmptyQueryError(RetrievalError):
    code = "empty_query"


class EmbeddingProfileMismatchError(RetrievalError):
    code = "embedding_profile_mismatch"


class InvalidTopKError(RetrievalError):
    code = "invalid_top_k"


@dataclass(frozen=True)
class RetrievalResult:
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_id: uuid.UUID
    chunk_index: int
    document_uri: str
    source_uri: str | None
    text: str
    text_preview: str
    distance: float
    score: float
    chunk_metadata: dict[str, Any]


@dataclass(frozen=True)
class RetrievalReport:
    knowledge_base: str
    query: str
    top_k: int
    provider: str
    model: str
    dimensions: int
    distance_metric: str
    total_results: int
    results: list[RetrievalResult]


def _build_latest_version_subquery(knowledge_base_id) -> Any:
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


def _available_profiles(session: Session, *, knowledge_base_id) -> list[dict[str, Any]]:
    latest_versions = _build_latest_version_subquery(knowledge_base_id)
    rows = session.execute(
        select(Embedding.provider, Embedding.model, Embedding.dimensions)
        .join(Chunk, Chunk.id == Embedding.chunk_id)
        .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .join(latest_versions, DocumentVersion.id == latest_versions.c.document_version_id)
        .where(Document.knowledge_base_id == knowledge_base_id)
        .distinct()
        .order_by(Embedding.provider, Embedding.model, Embedding.dimensions)
    ).all()
    return [
        {"provider": row.provider, "model": row.model, "dimensions": row.dimensions} for row in rows
    ]


def _resolve_profile(
    session: Session,
    *,
    knowledge_base: KnowledgeBase,
    provider: str | None,
    model: str | None,
    dimensions: int | None,
) -> tuple[str, str, int]:
    available_profiles = _available_profiles(session, knowledge_base_id=knowledge_base.id)
    if not available_profiles:
        resolved_dimensions = dimensions or 8
        return (
            provider or "deterministic-local",
            model or f"hash-{resolved_dimensions}d",
            resolved_dimensions,
        )

    expected_provider = provider or available_profiles[0]["provider"]
    expected_dimensions = dimensions or available_profiles[0]["dimensions"]
    expected_model = model or available_profiles[0]["model"]

    for profile in available_profiles:
        if (
            profile["provider"] == expected_provider
            and profile["model"] == expected_model
            and profile["dimensions"] == expected_dimensions
        ):
            return expected_provider, expected_model, expected_dimensions

    raise EmbeddingProfileMismatchError(
        "Requested embedding profile does not match indexed embeddings",
        details={
            "requested": {
                "provider": expected_provider,
                "model": expected_model,
                "dimensions": expected_dimensions,
            },
            "available_profiles": available_profiles,
        },
    )


def _normalize_vector(raw: Any) -> list[float]:
    return [float(value) for value in raw]


def _cosine_distance(left: list[float], right: list[float]) -> float:
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


def _build_base_statement(
    *,
    knowledge_base_id,
    provider: str,
    model: str,
    dimensions: int,
) -> Select[Any]:
    latest_versions = _build_latest_version_subquery(knowledge_base_id)
    return (
        select(
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
        .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .join(Embedding, Embedding.chunk_id == Chunk.id)
        .join(Source, Source.id == Document.source_id)
        .join(latest_versions, latest_versions.c.document_version_id == DocumentVersion.id)
        .where(
            Document.knowledge_base_id == knowledge_base_id,
            Embedding.provider == provider,
            Embedding.model == model,
            Embedding.dimensions == dimensions,
        )
    )


def _search_with_sql_distance(
    session: Session,
    *,
    knowledge_base_id,
    provider: str,
    model: str,
    dimensions: int,
    query_vector: list[float],
    top_k: int,
) -> list[RetrievalResult]:
    distance_expr = Embedding.embedding.cosine_distance(query_vector)
    rows = session.execute(
        _build_base_statement(
            knowledge_base_id=knowledge_base_id,
            provider=provider,
            model=model,
            dimensions=dimensions,
        )
        .add_columns(distance_expr.label("distance"))
        .order_by(distance_expr.asc(), Chunk.chunk_index.asc())
        .limit(top_k)
    ).all()
    return [
        RetrievalResult(
            document_id=row.document_id,
            document_version_id=row.document_version_id,
            chunk_id=row.chunk_id,
            chunk_index=row.chunk_index,
            document_uri=row.document_uri,
            source_uri=row.source_uri,
            text=row.text,
            text_preview=row.text[:160],
            distance=round(float(row.distance), 6),
            score=round(1.0 - float(row.distance), 6),
            chunk_metadata=row.chunk_metadata,
        )
        for row in rows
    ]


def _search_with_python_distance(
    session: Session,
    *,
    knowledge_base_id,
    provider: str,
    model: str,
    dimensions: int,
    query_vector: list[float],
    top_k: int,
) -> list[RetrievalResult]:
    rows = session.execute(
        _build_base_statement(
            knowledge_base_id=knowledge_base_id,
            provider=provider,
            model=model,
            dimensions=dimensions,
        )
    ).all()
    ranked = sorted(
        rows,
        key=lambda row: (
            _cosine_distance(_normalize_vector(row.embedding), query_vector),
            row.chunk_index,
        ),
    )[:top_k]
    results: list[RetrievalResult] = []
    for row in ranked:
        distance = _cosine_distance(_normalize_vector(row.embedding), query_vector)
        results.append(
            RetrievalResult(
                document_id=row.document_id,
                document_version_id=row.document_version_id,
                chunk_id=row.chunk_id,
                chunk_index=row.chunk_index,
                document_uri=row.document_uri,
                source_uri=row.source_uri,
                text=row.text,
                text_preview=row.text[:160],
                distance=distance,
                score=round(1.0 - distance, 6),
                chunk_metadata=row.chunk_metadata,
            )
        )
    return results


def search_knowledge_base(
    session: Session,
    *,
    knowledge_base_name: str,
    query: str,
    top_k: int = 5,
    provider: str | None = None,
    model: str | None = None,
    dimensions: int | None = None,
) -> RetrievalReport:
    if top_k <= 0:
        raise InvalidTopKError(
            "top_k must be greater than zero",
            details={"top_k": top_k},
        )

    normalized_query = query.strip()
    if not normalized_query:
        raise EmptyQueryError(
            "Query must not be empty",
            details={"query": query},
        )

    knowledge_base = get_knowledge_base_by_name(session, knowledge_base_name)
    if knowledge_base is None:
        raise KnowledgeBaseNotFoundError(
            f"Knowledge base '{knowledge_base_name}' was not found",
            details={"knowledge_base": knowledge_base_name},
        )

    resolved_provider, resolved_model, resolved_dimensions = _resolve_profile(
        session,
        knowledge_base=knowledge_base,
        provider=provider,
        model=model,
        dimensions=dimensions,
    )
    embedding_provider = get_provider_registry().get(
        resolved_provider, dimensions=resolved_dimensions
    )
    query_embedding = embedding_provider.embed_text(normalized_query)

    if session.bind is not None and session.bind.dialect.name == "postgresql":
        results = _search_with_sql_distance(
            session,
            knowledge_base_id=knowledge_base.id,
            provider=resolved_provider,
            model=resolved_model,
            dimensions=resolved_dimensions,
            query_vector=query_embedding.vector,
            top_k=top_k,
        )
    else:
        results = _search_with_python_distance(
            session,
            knowledge_base_id=knowledge_base.id,
            provider=resolved_provider,
            model=resolved_model,
            dimensions=resolved_dimensions,
            query_vector=query_embedding.vector,
            top_k=top_k,
        )

    return RetrievalReport(
        knowledge_base=knowledge_base_name,
        query=normalized_query,
        top_k=top_k,
        provider=resolved_provider,
        model=resolved_model,
        dimensions=resolved_dimensions,
        distance_metric="cosine_distance",
        total_results=len(results),
        results=results,
    )


__all__ = [
    "EmbeddingProfileMismatchError",
    "EmptyQueryError",
    "InvalidTopKError",
    "KnowledgeBaseNotFoundError",
    "RetrievalError",
    "RetrievalReport",
    "RetrievalResult",
    "search_knowledge_base",
]
