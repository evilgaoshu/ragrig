"""Conflict review API — list pending near-duplicate conflicts and resolve them."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.db.models import Chunk, ConflictReview
from ragrig.db.session import get_session
from ragrig.indexing.conflict_detection import resolve_conflict

router = APIRouter(prefix="/conflicts", tags=["conflicts"])

DbSession = Annotated[Session, Depends(get_session)]


class ConflictReviewOut(BaseModel):
    id: str
    knowledge_base_id: str
    new_chunk_id: str
    existing_chunk_id: str
    similarity: float
    status: str
    resolution: str | None
    resolved_by: str | None
    new_chunk_preview: str | None
    existing_chunk_preview: str | None
    created_at: str
    resolved_at: str | None
    metadata: dict[str, Any]

    model_config = {"from_attributes": True}


class ResolveRequest(BaseModel):
    resolution: str = Field(
        ...,
        description=(
            "One of: keep_new, keep_old, keep_both, auto_recency. "
            "keep_new: discard existing chunk embeddings. "
            "keep_old: discard new chunk embeddings. "
            "keep_both: retain both (no deletion). "
            "auto_recency: keep whichever chunk is newer."
        ),
    )
    resolved_by: str | None = None


def _review_to_out(review: ConflictReview, session: Session) -> ConflictReviewOut:
    new_chunk = session.get(Chunk, review.new_chunk_id)
    old_chunk = session.get(Chunk, review.existing_chunk_id)
    return ConflictReviewOut(
        id=str(review.id),
        knowledge_base_id=str(review.knowledge_base_id),
        new_chunk_id=str(review.new_chunk_id),
        existing_chunk_id=str(review.existing_chunk_id),
        similarity=review.similarity,
        status=review.status,
        resolution=review.resolution,
        resolved_by=review.resolved_by,
        new_chunk_preview=new_chunk.text[:300] if new_chunk else None,
        existing_chunk_preview=old_chunk.text[:300] if old_chunk else None,
        created_at=review.created_at.isoformat(),
        resolved_at=review.resolved_at.isoformat() if review.resolved_at else None,
        metadata=review.metadata_json or {},
    )


@router.get("", response_model=list[ConflictReviewOut])
def list_conflicts(
    session: DbSession,
    kb_name: str | None = Query(None, description="Filter by knowledge base name"),
    status: str = Query("pending", description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
) -> list[ConflictReviewOut]:
    """List conflict reviews, optionally filtered by knowledge base and status."""
    stmt = select(ConflictReview)
    if status:
        stmt = stmt.where(ConflictReview.status == status)
    stmt = stmt.order_by(ConflictReview.created_at.desc()).limit(limit)
    reviews = session.execute(stmt).scalars().all()
    return [_review_to_out(r, session) for r in reviews]


@router.post("/{conflict_id}/resolve", response_model=ConflictReviewOut)
def resolve_conflict_endpoint(
    conflict_id: str,
    body: ResolveRequest,
    session: DbSession,
) -> ConflictReviewOut:
    """Resolve a pending conflict review."""
    try:
        conflict_uuid = uuid.UUID(conflict_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid conflict_id format") from exc

    try:
        review = resolve_conflict(
            session,
            conflict_id=conflict_uuid,
            resolution=body.resolution,
            resolved_by=body.resolved_by,
        )
        session.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _review_to_out(review, session)
