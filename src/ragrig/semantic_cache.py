"""Semantic cache — return cached answers for semantically similar queries.

When ``cache_config`` is passed to ``generate_answer()``, the pipeline:
1. Embeds the incoming query.
2. Looks up ``semantic_cache`` for an entry whose stored embedding has cosine
   similarity ≥ ``similarity_threshold`` (default 0.95).
3. On a **hit**: returns the cached answer immediately (no LLM call, no
   retrieval) and increments the hit counter.
4. On a **miss**: runs the full pipeline, then stores the result.

All functions degrade gracefully — a failure never blocks answer generation.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.db.models import SemanticCacheEntry

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SemanticCacheConfig:
    """Configuration for semantic query caching.

    Attributes:
        similarity_threshold: Minimum cosine similarity (0-1) for a cache hit.
            Higher values mean only near-identical queries are served from cache.
        ttl_seconds: Time-to-live in seconds.  None means entries never expire.
        max_entries_per_kb: Upper bound on stored entries per knowledge base.
            When exceeded, the oldest entries are evicted at store time.
    """

    similarity_threshold: float = 0.95
    ttl_seconds: int | None = 3600
    max_entries_per_kb: int = 500

    def __post_init__(self) -> None:
        if not (0.0 < self.similarity_threshold <= 1.0):
            raise ValueError(
                f"similarity_threshold must be in (0, 1], got {self.similarity_threshold}"
            )
        if self.ttl_seconds is not None and self.ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")


@dataclass(frozen=True)
class CacheHit:
    """A successful semantic cache lookup."""

    entry_id: uuid.UUID
    query_text: str
    answer_text: str
    citations_json: list[Any]
    similarity: float
    hit_count: int


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


def lookup_cache(
    session: Session,
    *,
    query_vector: list[float],
    knowledge_base_name: str,
    provider: str,
    model: str,
    dimensions: int,
    config: SemanticCacheConfig,
    workspace_id: object = None,
) -> CacheHit | None:
    """Find the best matching cache entry for *query_vector*.

    Returns None when no entry meets the similarity threshold, when the table
    is empty, or on any error.
    """
    now = datetime.now(timezone.utc)
    stmt = select(SemanticCacheEntry).where(
        SemanticCacheEntry.knowledge_base_name == knowledge_base_name,
        SemanticCacheEntry.provider == provider,
        SemanticCacheEntry.model == model,
        SemanticCacheEntry.dimensions == dimensions,
    )
    if workspace_id is not None:
        stmt = stmt.where(SemanticCacheEntry.workspace_id == workspace_id)

    try:
        entries = session.execute(stmt).scalars().all()
    except Exception:
        logger.debug("Semantic cache lookup query failed (non-fatal)", exc_info=True)
        return None

    best: CacheHit | None = None
    best_sim = -1.0

    for entry in entries:
        # Skip expired entries
        if entry.expires_at is not None:
            expires = entry.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires < now:
                continue

        if entry.embedding is None:
            continue

        stored = list(entry.embedding)
        sim = _cosine_similarity(query_vector, stored)
        if sim >= config.similarity_threshold and sim > best_sim:
            best_sim = sim
            best = CacheHit(
                entry_id=entry.id,
                query_text=entry.query_text,
                answer_text=entry.answer_text,
                citations_json=list(entry.citations_json or []),
                similarity=round(sim, 6),
                hit_count=entry.hit_count,
            )

    return best


def increment_hit_count(
    session: Session,
    entry_id: uuid.UUID,
) -> None:
    """Increment hit_count for a cache entry (best-effort, non-fatal)."""
    try:
        entry = session.get(SemanticCacheEntry, entry_id)
        if entry is not None:
            entry.hit_count += 1
            session.flush()
    except Exception:
        logger.debug("Failed to increment cache hit count (non-fatal)", exc_info=True)


def store_cache(
    session: Session,
    *,
    knowledge_base_name: str,
    query_text: str,
    query_vector: list[float],
    provider: str,
    model: str,
    dimensions: int,
    answer_text: str,
    citations_json: list[Any],
    config: SemanticCacheConfig,
    workspace_id: object = None,
    extra_metadata: dict[str, Any] | None = None,
) -> None:
    """Persist a (query, answer) pair to the semantic cache.

    Evicts the oldest entries when ``max_entries_per_kb`` is exceeded.
    Failures are logged and swallowed — caching must never break generation.
    """
    try:
        # Evict oldest entries if at capacity
        count_stmt = select(SemanticCacheEntry).where(
            SemanticCacheEntry.knowledge_base_name == knowledge_base_name,
        )
        if workspace_id is not None:
            count_stmt = count_stmt.where(SemanticCacheEntry.workspace_id == workspace_id)

        existing = session.execute(count_stmt).scalars().all()
        if len(existing) >= config.max_entries_per_kb:
            to_evict = sorted(existing, key=lambda e: e.created_at)[
                : len(existing) - config.max_entries_per_kb + 1
            ]
            for e in to_evict:
                session.delete(e)
            session.flush()

        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=config.ttl_seconds)
            if config.ttl_seconds is not None
            else None
        )

        entry = SemanticCacheEntry(
            knowledge_base_name=knowledge_base_name,
            workspace_id=workspace_id,
            query_text=query_text,
            provider=provider,
            model=model,
            dimensions=dimensions,
            embedding=query_vector,
            answer_text=answer_text,
            citations_json=citations_json,
            metadata_json=extra_metadata or {},
            hit_count=0,
            expires_at=expires_at,
        )
        session.add(entry)
        session.flush()
    except Exception:
        logger.debug("Failed to store semantic cache entry (non-fatal)", exc_info=True)


def invalidate_cache(
    session: Session,
    *,
    knowledge_base_name: str,
    workspace_id: object = None,
) -> int:
    """Delete all cache entries for a knowledge base.

    Called when a KB is re-indexed so stale answers are not served.
    Returns the number of deleted entries.
    """
    stmt = select(SemanticCacheEntry).where(
        SemanticCacheEntry.knowledge_base_name == knowledge_base_name,
    )
    if workspace_id is not None:
        stmt = stmt.where(SemanticCacheEntry.workspace_id == workspace_id)

    entries = session.execute(stmt).scalars().all()
    for e in entries:
        session.delete(e)
    session.flush()
    return len(entries)
