"""Near-duplicate chunk conflict detection using pgvector cosine similarity."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ragrig.db.models import Chunk, ConflictReview, Embedding

logger = logging.getLogger(__name__)


def find_conflicting_chunk(
    session: Session,
    *,
    new_vector: list[float],
    knowledge_base_id: uuid.UUID,
    new_chunk_id: uuid.UUID,
    threshold: float = 0.92,
) -> tuple[uuid.UUID, float] | None:
    """Find the most similar existing chunk in the KB above the conflict threshold.

    Uses pgvector's ``<=>`` (cosine distance) operator for efficient search.
    Returns (existing_chunk_id, similarity) or None when no conflict is found.
    Only runs on PostgreSQL — silently returns None for other backends.
    """
    try:
        bind = session.get_bind()
        if not hasattr(bind, "dialect") or bind.dialect.name != "postgresql":
            return None
    except Exception:
        return None

    try:
        # Cosine distance = 1 - cosine_similarity; threshold similarity → max distance
        max_distance = 1.0 - threshold
        vec_literal = "[" + ",".join(str(v) for v in new_vector) + "]"

        stmt = text(
            """
            SELECT e.chunk_id, (1.0 - (e.embedding <=> CAST(:vec AS vector))) AS similarity
            FROM embeddings e
            JOIN chunks c ON c.id = e.chunk_id
            JOIN document_versions dv ON dv.id = c.document_version_id
            JOIN documents d ON d.id = dv.document_id
            WHERE d.knowledge_base_id = :kb_id
              AND e.chunk_id != :exclude_id
              AND (e.embedding <=> CAST(:vec AS vector)) <= :max_dist
            ORDER BY e.embedding <=> CAST(:vec AS vector) ASC
            LIMIT 1
            """
        )
        row = session.execute(
            stmt,
            {
                "vec": vec_literal,
                "kb_id": str(knowledge_base_id),
                "exclude_id": str(new_chunk_id),
                "max_dist": max_distance,
            },
        ).fetchone()

        if row is None:
            return None
        existing_chunk_id, similarity = row
        return uuid.UUID(str(existing_chunk_id)), float(similarity)

    except Exception:
        logger.debug("Conflict detection query failed (non-fatal)", exc_info=True)
        return None


def record_conflict(
    session: Session,
    *,
    knowledge_base_id: uuid.UUID,
    new_chunk_id: uuid.UUID,
    existing_chunk_id: uuid.UUID,
    similarity: float,
    extra_metadata: dict[str, Any] | None = None,
) -> ConflictReview:
    """Insert a ConflictReview row for human (or automated) resolution."""
    review = ConflictReview(
        id=uuid.uuid4(),
        knowledge_base_id=knowledge_base_id,
        new_chunk_id=new_chunk_id,
        existing_chunk_id=existing_chunk_id,
        similarity=round(similarity, 6),
        status="pending",
        metadata_json=extra_metadata or {},
        created_at=datetime.now(timezone.utc),
    )
    session.add(review)
    return review


def resolve_conflict(
    session: Session,
    *,
    conflict_id: uuid.UUID,
    resolution: str,
    resolved_by: str | None = None,
) -> ConflictReview:
    """Apply a resolution to a ConflictReview and act on it.

    resolution options:
      keep_new          — soft-delete existing chunk's embeddings
      keep_old          — soft-delete new chunk's embeddings
      keep_both         — no embedding deletion, mark resolved
      auto_recency      — keep whichever chunk was created more recently
    """
    valid = {"keep_new", "keep_old", "keep_both", "auto_recency"}
    if resolution not in valid:
        raise ValueError(f"Invalid resolution '{resolution}'. Valid: {sorted(valid)}")

    review = session.get(ConflictReview, conflict_id)
    if review is None:
        raise ValueError(f"ConflictReview {conflict_id} not found")
    if review.status != "pending":
        raise ValueError(f"ConflictReview {conflict_id} is already resolved")

    actual_resolution = resolution
    if resolution == "auto_recency":
        new_chunk = session.get(Chunk, review.new_chunk_id)
        old_chunk = session.get(Chunk, review.existing_chunk_id)
        if new_chunk and old_chunk:
            new_ts = getattr(new_chunk, "created_at", None)
            old_ts = getattr(old_chunk, "created_at", None)
            if new_ts and old_ts and new_ts >= old_ts:
                actual_resolution = "keep_new"
            else:
                actual_resolution = "keep_old"
        else:
            actual_resolution = "keep_new"

    if actual_resolution == "keep_new":
        _soft_delete_chunk_embeddings(session, review.existing_chunk_id)
    elif actual_resolution == "keep_old":
        _soft_delete_chunk_embeddings(session, review.new_chunk_id)
    # keep_both → no deletion

    review.status = f"resolved_{resolution}"
    review.resolution = actual_resolution
    review.resolved_by = resolved_by
    review.resolved_at = datetime.now(timezone.utc)
    session.flush()
    return review


def _soft_delete_chunk_embeddings(session: Session, chunk_id: uuid.UUID) -> None:
    """Mark all embeddings for a chunk as conflict-resolved (metadata flag)."""
    embeddings = (
        session.execute(select(Embedding).where(Embedding.chunk_id == chunk_id)).scalars().all()
    )
    for emb in embeddings:
        meta = dict(emb.metadata_json)
        meta["conflict_resolved"] = True
        emb.metadata_json = meta
    session.flush()
