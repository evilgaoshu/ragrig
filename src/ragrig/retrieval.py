from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.acl import acl_permits_chunk_metadata
from ragrig.db.models import Chunk, Document, DocumentVersion, Embedding, KnowledgeBase
from ragrig.providers import get_provider_registry
from ragrig.repositories import get_knowledge_base_by_name
from ragrig.vectorstore import build_vector_collection
from ragrig.vectorstore.base import VectorBackend
from ragrig.vectorstore.pgvector import (
    build_embedding_base_statement as _build_base_statement,
)
from ragrig.vectorstore.pgvector import (
    cosine_distance as _cosine_distance,
)
from ragrig.vectorstore.pgvector import (
    latest_version_subquery as _build_latest_version_subquery,
)
from ragrig.vectorstore.pgvector import (
    normalize_vector as _normalize_vector,
)


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
    backend: str
    backend_metadata: dict[str, Any]
    total_results: int
    results: list[RetrievalResult]


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


def _search_with_sql_distance(
    session: Session,
    *,
    knowledge_base_id,
    provider: str,
    model: str,
    dimensions: int,
    query_vector: list[float],
    top_k: int,
    principal_ids: list[str] | None = None,
    enforce_acl: bool = True,
) -> list[RetrievalResult]:
    distance_expr = Embedding.embedding.cosine_distance(query_vector)
    statement = _build_base_statement(
        knowledge_base_id=knowledge_base_id,
        provider=provider,
        model=model,
        dimensions=dimensions,
    ).add_columns(distance_expr.label("distance"))
    if enforce_acl and principal_ids is not None:
        if len(principal_ids) > 0:
            statement = statement.where(_build_acl_where_clause(principal_ids))
        else:
            statement = statement.where(_build_acl_public_only_clause())
    statement = statement.order_by(distance_expr.asc(), Chunk.chunk_index.asc()).limit(top_k)
    rows = session.execute(statement).all()
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
    principal_ids: list[str] | None = None,
    enforce_acl: bool = True,
) -> list[RetrievalResult]:
    rows = session.execute(
        _build_base_statement(
            knowledge_base_id=knowledge_base_id,
            provider=provider,
            model=model,
            dimensions=dimensions,
        )
    ).all()

    if enforce_acl and principal_ids is not None:
        rows = [
            row
            for row in rows
            if acl_permits_chunk_metadata(
                row.chunk_metadata,
                principal_ids if len(principal_ids) > 0 else None,
            )
        ]

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


def _build_acl_where_clause(principal_ids: list[str]) -> Any:
    """Build a SQLAlchemy WHERE clause for chunk ACL filtering on JSONB metadata."""
    from sqlalchemy import Text as _Text
    from sqlalchemy import or_
    from sqlalchemy import type_coerce as _tc
    from sqlalchemy.dialects.postgresql import JSONB

    principals_json = [pid.lower() for pid in principal_ids]
    not_public = (
        Chunk.metadata_json["acl", "visibility"].astext.cast(_Text).in_(["protected", "unknown"])
    )
    is_public = Chunk.metadata_json["acl", "visibility"].astext == "public"
    allowed = Chunk.metadata_json["acl", "allowed_principals"].has_any(_tc(principals_json, JSONB))
    denied = Chunk.metadata_json["acl", "denied_principals"].has_any(_tc(principals_json, JSONB))
    no_acl = ~Chunk.metadata_json.has_key("acl")
    return or_(
        is_public,
        no_acl,
        (not_public & allowed & ~denied),
    )


def _build_acl_public_only_clause() -> Any:
    """Build WHERE clause that only returns public/no-ACL chunks."""
    from sqlalchemy import or_

    is_public = Chunk.metadata_json["acl", "visibility"].astext == "public"
    no_acl = ~Chunk.metadata_json.has_key("acl")
    return or_(is_public, no_acl)


def search_knowledge_base(
    session: Session,
    *,
    knowledge_base_name: str,
    query: str,
    top_k: int = 5,
    provider: str | None = None,
    model: str | None = None,
    dimensions: int | None = None,
    vector_backend: VectorBackend | None = None,
    principal_ids: list[str] | None = None,
    enforce_acl: bool = True,
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
    collection = build_vector_collection(
        knowledge_base_name=knowledge_base_name,
        provider=resolved_provider,
        model=resolved_model,
        dimensions=resolved_dimensions,
    )
    if vector_backend is not None:
        vector_backend.ensure_collection(session, collection)
        fetch_k = top_k * 3 if (enforce_acl and principal_ids is not None) else top_k
        vector_results = vector_backend.search(
            session,
            collection,
            query_vector=query_embedding.vector,
            top_k=fetch_k,
        )
        if enforce_acl and principal_ids is not None:
            vector_results = [
                r
                for r in vector_results
                if acl_permits_chunk_metadata(
                    r.metadata.get("chunk_metadata"),
                    principal_ids if len(principal_ids) > 0 else None,
                )
            ][:top_k]
        results = [
            RetrievalResult(
                document_id=result.document_id,
                document_version_id=result.document_version_id,
                chunk_id=result.chunk_id,
                chunk_index=result.chunk_index,
                document_uri=str(result.metadata["document_uri"]),
                source_uri=result.metadata.get("source_uri"),
                text=result.text,
                text_preview=result.text[:160],
                distance=result.distance,
                score=result.score,
                chunk_metadata=result.metadata.get("chunk_metadata", {}),
            )
            for result in vector_results
        ]
        return RetrievalReport(
            knowledge_base=knowledge_base_name,
            query=normalized_query,
            top_k=top_k,
            provider=resolved_provider,
            model=resolved_model,
            dimensions=resolved_dimensions,
            distance_metric="cosine_similarity",
            backend=vector_backend.backend_name,
            backend_metadata={
                "distance_metric": vector_backend.distance_metric,
                "status": "ready",
            },
            total_results=len(results),
            results=results,
        )

    if session.bind is not None and session.bind.dialect.name == "postgresql":
        results = _search_with_sql_distance(
            session,
            knowledge_base_id=knowledge_base.id,
            provider=resolved_provider,
            model=resolved_model,
            dimensions=resolved_dimensions,
            query_vector=query_embedding.vector,
            top_k=top_k,
            principal_ids=principal_ids,
            enforce_acl=enforce_acl,
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
            principal_ids=principal_ids,
            enforce_acl=enforce_acl,
        )

    return RetrievalReport(
        knowledge_base=knowledge_base_name,
        query=normalized_query,
        top_k=top_k,
        provider=resolved_provider,
        model=resolved_model,
        dimensions=resolved_dimensions,
        distance_metric="cosine_distance",
        backend="pgvector",
        backend_metadata={
            "distance_metric": "cosine",
            "status": "ready",
        },
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
    "_build_base_statement",
    "_build_latest_version_subquery",
    "_cosine_distance",
    "_normalize_vector",
    "search_knowledge_base",
]
