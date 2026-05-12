from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.acl import acl_decision_reason, acl_permits_chunk_metadata, normalize_principal_ids
from ragrig.db.models import Chunk, Document, DocumentVersion, Embedding, KnowledgeBase
from ragrig.lexical import token_overlap_score
from ragrig.providers import get_provider_registry
from ragrig.repositories import get_knowledge_base_by_name
from ragrig.repositories.audit import create_audit_event
from ragrig.reranker import (
    RerankCandidate,
    RerankResult,
    fake_rerank,
    provider_rerank,
)
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
    rank_stage_trace: dict[str, Any] = field(default_factory=dict)


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
    degraded: bool = False
    degraded_reason: str = ""
    acl_explain: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _AclFilterReport:
    results: list[Any]
    candidate_count: int
    visible_count: int
    filtered_count: int
    reason_counts: dict[str, int]


def _filter_acl_candidates(
    candidates: list[Any],
    *,
    principal_ids: list[str] | None,
    metadata_getter,
) -> _AclFilterReport:
    normalized_principals = normalize_principal_ids(principal_ids)
    visible: list[Any] = []
    reason_counts: dict[str, int] = {}
    effective_principals = normalized_principals if normalized_principals else None
    for candidate in candidates:
        metadata = metadata_getter(candidate)
        reason = acl_decision_reason(metadata, effective_principals)
        permitted = acl_permits_chunk_metadata(metadata, effective_principals)
        if permitted:
            visible.append(candidate)
        else:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    return _AclFilterReport(
        results=visible,
        candidate_count=len(candidates),
        visible_count=len(visible),
        filtered_count=len(candidates) - len(visible),
        reason_counts=reason_counts,
    )


def _build_acl_explain(
    *,
    enforce_acl: bool,
    principal_ids: list[str] | None,
    candidate_count: int,
    visible_count: int,
    filtered_count: int,
    reason_counts: dict[str, int] | None = None,
) -> dict[str, Any]:
    principal_count = len(normalize_principal_ids(principal_ids))
    return {
        "enforced": enforce_acl,
        "principal_context": "present" if principal_count > 0 else "missing",
        "principal_count": principal_count,
        "stage": "pre_retrieval",
        "candidate_count": candidate_count,
        "visible_count": visible_count,
        "filtered_count": filtered_count,
        "reason_counts": reason_counts or {},
    }


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
    if enforce_acl:
        if principal_ids and len(principal_ids) > 0:
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
            rank_stage_trace={
                "stages": [
                    {
                        "stage": "vector",
                        "distance": round(float(row.distance), 6),
                        "score": round(1.0 - float(row.distance), 6),
                        "provider": provider,
                        "model": model,
                        "dimensions": dimensions,
                    }
                ],
                "final_source": "vector",
            },
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
) -> tuple[list[RetrievalResult], _AclFilterReport | None]:
    rows = session.execute(
        _build_base_statement(
            knowledge_base_id=knowledge_base_id,
            provider=provider,
            model=model,
            dimensions=dimensions,
        )
    ).all()

    acl_filter_report: _AclFilterReport | None = None
    if enforce_acl:
        acl_filter_report = _filter_acl_candidates(
            list(rows),
            principal_ids=principal_ids,
            metadata_getter=lambda row: row.chunk_metadata,
        )
        rows = acl_filter_report.results

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
                rank_stage_trace={
                    "stages": [
                        {
                            "stage": "vector",
                            "distance": distance,
                            "score": round(1.0 - distance, 6),
                            "provider": provider,
                            "model": model,
                            "dimensions": dimensions,
                        }
                    ],
                    "final_source": "vector",
                },
            )
        )
    return results, acl_filter_report


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


def _apply_hybrid_fusion(
    dense_results: list[RetrievalResult],
    query: str,
    corpus_texts: list[str],
    *,
    lexical_weight: float = 0.3,
    vector_weight: float = 0.7,
) -> list[RetrievalResult]:
    """Score dense results with lexical scores and fuse.

    For each dense result, compute a lexical score via token_overlap_score
    and combine with the vector score using the weights.  Results are
    re-ranked by combined_score descending.
    """
    if not dense_results:
        return []

    # Normalize vector scores to [0, 1] for fair fusion
    scores = [r.score for r in dense_results]
    max_score = max(scores) if scores else 1.0
    min_score = min(scores) if scores else 0.0
    score_range = max_score - min_score if max_score != min_score else 1.0

    fused: list[tuple[float, RetrievalResult]] = []
    for r in dense_results:
        norm_vector = (r.score - min_score) / score_range if score_range > 0 else 0.5
        lexical = min(token_overlap_score(r.text, query, corpus_texts), 1.0)
        combined = vector_weight * norm_vector + lexical_weight * lexical

        trace = {
            "stages": [
                {
                    "stage": "vector",
                    "distance": r.distance,
                    "score": r.score,
                    "normalized_score": round(norm_vector, 6),
                    "provider": r.rank_stage_trace.get("stages", [{}])[0].get("provider", ""),
                    "model": "",
                    "dimensions": 0,
                },
                {
                    "stage": "lexical",
                    "score": round(lexical, 6),
                    "method": "token_overlap_bm25_lite",
                },
            ],
            "final_source": "hybrid_fusion",
            "weights": {
                "lexical_weight": lexical_weight,
                "vector_weight": vector_weight,
            },
        }
        fused.append(
            (
                combined,
                RetrievalResult(
                    document_id=r.document_id,
                    document_version_id=r.document_version_id,
                    chunk_id=r.chunk_id,
                    chunk_index=r.chunk_index,
                    document_uri=r.document_uri,
                    source_uri=r.source_uri,
                    text=r.text,
                    text_preview=r.text_preview,
                    distance=r.distance,
                    score=round(combined, 6),
                    chunk_metadata=r.chunk_metadata,
                    rank_stage_trace=trace,
                ),
            )
        )

    fused.sort(key=lambda x: -x[0])
    return [r for _, r in fused]


def _apply_rerank(
    candidates: list[RetrievalResult],
    query: str,
    *,
    reranker_provider: str | None = None,
    reranker_model: str | None = None,
) -> tuple[list[RetrievalResult], bool, str]:
    """Apply reranking to a list of candidate results.

    Returns (results, degraded, degraded_reason).  When the reranker is
    unavailable, the original candidates are returned unchanged with
    degraded=True.
    """
    if not candidates:
        return [], False, ""

    rerank_candidates = [
        RerankCandidate(
            document_id=r.document_id,
            document_version_id=r.document_version_id,
            chunk_id=r.chunk_id,
            chunk_index=r.chunk_index,
            document_uri=r.document_uri,
            source_uri=r.source_uri,
            text=r.text,
            text_preview=r.text_preview,
            original_score=r.score,
            original_index=i,
            chunk_metadata=r.chunk_metadata,
        )
        for i, r in enumerate(candidates)
    ]

    # Try provider reranker first, fall back to fake reranker for testing
    rerank_results: list[RerankResult] | None = None
    degraded = False
    degraded_reason = ""

    if reranker_provider is not None or reranker_model is not None:
        # Explicit reranker requested — try provider, degrade on failure
        rr = provider_rerank(
            query,
            rerank_candidates,
            provider_name=reranker_provider,
            model_name=reranker_model,
        )
        if rr is None:
            # Provider unavailable; degrade to original order
            degraded = True
            degraded_reason = (
                f"Reranker provider '{reranker_provider or 'reranker.bge'}' "
                "is unavailable; results returned in original order."
            )
            rerank_results = None
        else:
            rerank_results = rr
    else:
        # No explicit reranker; use fake reranker for testing/demonstration
        rerank_results = fake_rerank(query, rerank_candidates)

    if rerank_results is None:
        # Degradation path: keep original order, add trace
        results: list[RetrievalResult] = []
        for r in candidates:
            trace = dict(r.rank_stage_trace)
            trace["stages"] = trace.get("stages", []) + [
                {
                    "stage": "rerank",
                    "status": "degraded",
                    "reason": degraded_reason or "reranker unavailable",
                }
            ]
            results.append(
                RetrievalResult(
                    document_id=r.document_id,
                    document_version_id=r.document_version_id,
                    chunk_id=r.chunk_id,
                    chunk_index=r.chunk_index,
                    document_uri=r.document_uri,
                    source_uri=r.source_uri,
                    text=r.text,
                    text_preview=r.text_preview,
                    distance=r.distance,
                    score=r.score,
                    chunk_metadata=r.chunk_metadata,
                    rank_stage_trace=trace,
                )
            )
        return results, degraded, degraded_reason

    # Successful rerank
    results = []
    for rr_item in rerank_results:
        cand = rr_item.candidate
        original_trace = candidates[rr_item.candidate.original_index].rank_stage_trace
        trace = {
            "stages": original_trace.get("stages", [])
            + [
                {
                    "stage": "rerank",
                    "score": rr_item.rerank_score,
                    "original_rank": rr_item.candidate.original_index + 1,
                    "new_rank": rr_item.new_rank + 1,
                    "reranker": reranker_provider or "fake",
                    "model": reranker_model or "",
                }
            ],
            "final_source": "rerank",
        }
        results.append(
            RetrievalResult(
                document_id=cand.document_id,
                document_version_id=cand.document_version_id,
                chunk_id=cand.chunk_id,
                chunk_index=cand.chunk_index,
                document_uri=cand.document_uri,
                source_uri=cand.source_uri,
                text=cand.text,
                text_preview=cand.text_preview,
                distance=candidates[rr_item.candidate.original_index].distance,
                score=rr_item.rerank_score,
                chunk_metadata=cand.chunk_metadata,
                rank_stage_trace=trace,
            )
        )

    return results, degraded, degraded_reason


def _fetch_all_texts(
    session: Session,
    *,
    knowledge_base_id,
    provider: str,
    model: str,
    dimensions: int,
) -> list[str]:
    """Fetch all chunk texts for lexical corpus building."""
    rows = session.execute(
        _build_base_statement(
            knowledge_base_id=knowledge_base_id,
            provider=provider,
            model=model,
            dimensions=dimensions,
        )
    ).all()
    return [row.text for row in rows]


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
    mode: str = "dense",
    lexical_weight: float = 0.3,
    vector_weight: float = 0.7,
    candidate_k: int = 20,
    reranker_provider: str | None = None,
    reranker_model: str | None = None,
) -> RetrievalReport:
    """Search a knowledge base with optional hybrid/rerank modes.

    Supported modes:
    - ``dense``: vector-only retrieval (default, backward-compatible)
    - ``hybrid``: vector + lexical fusion with configurable weights
    - ``rerank``: dense candidates reranked by a reranker provider or fake
    - ``hybrid_rerank``: hybrid fusion candidates reranked
    """
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

    # ── Phase 1: Dense vector retrieval ────────────────────────
    degraded = False
    degraded_reason = ""
    acl_filter_report: _AclFilterReport | None = None

    if vector_backend is not None:
        vector_backend.ensure_collection(session, collection)
        fetch_k = candidate_k if mode != "dense" else top_k
        if enforce_acl and principal_ids is not None:
            fetch_k = fetch_k * 3
        vector_results = vector_backend.search(
            session,
            collection,
            query_vector=query_embedding.vector,
            top_k=fetch_k,
        )
        if enforce_acl:
            acl_filter_report = _filter_acl_candidates(
                vector_results,
                principal_ids=principal_ids,
                metadata_getter=lambda row: row.metadata.get("chunk_metadata"),
            )
            vector_results = acl_filter_report.results
        dense_results: list[RetrievalResult] = []
        for result in vector_results[:candidate_k]:
            dense_results.append(
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
                    rank_stage_trace={
                        "stages": [
                            {
                                "stage": "vector",
                                "distance": result.distance,
                                "score": result.score,
                                "provider": resolved_provider,
                                "model": resolved_model,
                                "dimensions": resolved_dimensions,
                            }
                        ],
                        "final_source": "vector",
                    },
                )
            )
    elif session.bind is not None and session.bind.dialect.name == "postgresql":
        dense_results = _search_with_sql_distance(
            session,
            knowledge_base_id=knowledge_base.id,
            provider=resolved_provider,
            model=resolved_model,
            dimensions=resolved_dimensions,
            query_vector=query_embedding.vector,
            top_k=candidate_k if mode != "dense" else top_k,
            principal_ids=principal_ids,
            enforce_acl=enforce_acl,
        )
        acl_filter_report = _AclFilterReport(
            results=dense_results,
            candidate_count=len(dense_results),
            visible_count=len(dense_results),
            filtered_count=0,
            reason_counts={},
        )
    else:
        dense_results, acl_filter_report = _search_with_python_distance(
            session,
            knowledge_base_id=knowledge_base.id,
            provider=resolved_provider,
            model=resolved_model,
            dimensions=resolved_dimensions,
            query_vector=query_embedding.vector,
            top_k=candidate_k if mode != "dense" else top_k,
            principal_ids=principal_ids,
            enforce_acl=enforce_acl,
        )

    # ── Phase 2: Lexical fusion (hybrid / hybrid_rerank) ──────
    if mode in ("hybrid", "hybrid_rerank"):
        if dense_results:
            corpus_texts = [r.text for r in dense_results]
            dense_results = _apply_hybrid_fusion(
                dense_results,
                normalized_query,
                corpus_texts,
                lexical_weight=lexical_weight,
                vector_weight=vector_weight,
            )
        # else: no results, skip fusion

    # ── Phase 3: Rerank (rerank / hybrid_rerank) ───────────────
    if mode in ("rerank", "hybrid_rerank"):
        if dense_results:
            # ACL filtering is already applied in Phase 1 — only authorized
            # candidates reach here, so reranker input is ACL-safe.
            reranked, rerank_degraded, rerank_reason = _apply_rerank(
                dense_results,
                normalized_query,
                reranker_provider=reranker_provider,
                reranker_model=reranker_model,
            )
            dense_results = reranked
            degraded = rerank_degraded
            degraded_reason = rerank_reason

    # ── Final: Trim to top_k ──────────────────────────────────
    final_results = dense_results[:top_k]
    if acl_filter_report is None:
        acl_explain = _build_acl_explain(
            enforce_acl=enforce_acl,
            principal_ids=principal_ids,
            candidate_count=len(dense_results),
            visible_count=len(dense_results),
            filtered_count=0,
        )
    else:
        acl_explain = _build_acl_explain(
            enforce_acl=enforce_acl,
            principal_ids=principal_ids,
            candidate_count=acl_filter_report.candidate_count,
            visible_count=acl_filter_report.visible_count,
            filtered_count=acl_filter_report.filtered_count,
            reason_counts=acl_filter_report.reason_counts,
        )

    if enforce_acl:
        event_type = (
            "access_denied"
            if acl_explain["candidate_count"] > 0 and not final_results
            else "retrieval_filter"
        )
        create_audit_event(
            session,
            event_type=event_type,
            actor="retrieval",
            knowledge_base_id=knowledge_base.id,
            payload_json={
                "knowledge_base": knowledge_base_name,
                "query_hash": str(uuid.uuid5(uuid.NAMESPACE_URL, normalized_query)),
                "top_k": top_k,
                "mode": mode,
                "acl_explain": acl_explain,
            },
        )

    # Build backend metadata
    if vector_backend is not None:
        backend_name = vector_backend.backend_name
        backend_meta = {
            "distance_metric": vector_backend.distance_metric,
            "status": "ready",
        }
        distance_metric = "cosine_similarity"
    else:
        backend_name = "pgvector"
        backend_meta = {
            "distance_metric": "cosine",
            "status": "ready",
        }
        distance_metric = "cosine_distance"

    return RetrievalReport(
        knowledge_base=knowledge_base_name,
        query=normalized_query,
        top_k=top_k,
        provider=resolved_provider,
        model=resolved_model,
        dimensions=resolved_dimensions,
        distance_metric=distance_metric,
        backend=backend_name,
        backend_metadata=backend_meta,
        total_results=len(final_results),
        results=final_results,
        degraded=degraded,
        degraded_reason=degraded_reason,
        acl_explain=acl_explain,
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
