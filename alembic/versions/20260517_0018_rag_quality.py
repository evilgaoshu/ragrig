"""RAG quality: LLM descriptions, conflict detection, time-decay ranking.

Revision ID: 20260517_0018
Revises: 20260516_0017
Create Date: 2026-05-17

Adds:
  - ``chunks.llm_description``          LLM-generated semantic description (nullable)
  - ``knowledge_bases.doc_weight``       per-KB document weight for multi-factor ranking
  - ``conflict_reviews``                 near-duplicate conflict queue for human review
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "20260517_0018"
down_revision = "20260516_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # chunks: add LLM description column
    op.add_column("chunks", sa.Column("llm_description", sa.Text(), nullable=True))

    # knowledge_bases: per-KB document weight for ranking (default 0.5)
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "doc_weight",
            sa.Float(),
            nullable=False,
            server_default="0.5",
        ),
    )

    # conflict_reviews: human review queue for near-duplicate chunks
    op.create_table(
        "conflict_reviews",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "knowledge_base_id",
            UUID(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "new_chunk_id",
            UUID(as_uuid=True),
            sa.ForeignKey("chunks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "existing_chunk_id",
            UUID(as_uuid=True),
            sa.ForeignKey("chunks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("resolution", sa.String(64), nullable=True),
        sa.Column("resolved_by", sa.String(255), nullable=True),
        sa.Column("metadata_json", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'resolved_keep_new', 'resolved_keep_old', 'resolved_keep_both', 'resolved_auto_recency')",
            name="ck_conflict_reviews_status",
        ),
    )
    op.create_index(
        "ix_conflict_reviews_kb_status", "conflict_reviews", ["knowledge_base_id", "status"]
    )
    op.create_index("ix_conflict_reviews_new_chunk", "conflict_reviews", ["new_chunk_id"])


def downgrade() -> None:
    op.drop_index("ix_conflict_reviews_new_chunk", table_name="conflict_reviews")
    op.drop_index("ix_conflict_reviews_kb_status", table_name="conflict_reviews")
    op.drop_table("conflict_reviews")
    op.drop_column("knowledge_bases", "doc_weight")
    op.drop_column("chunks", "llm_description")
