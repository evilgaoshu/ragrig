"""Semantic cache: add semantic_cache table for query-answer caching.

Revision ID: 20260518_0021
Revises: 20260518_0020
Create Date: 2026-05-18

Adds:
  - ``semantic_cache``  stores (query_embedding, answer) pairs per KB.
    Cache hits are returned when an incoming query's embedding is within
    ``similarity_threshold`` of a stored entry.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "20260518_0021"
down_revision = "20260518_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "semantic_cache",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("knowledge_base_name", sa.Text(), nullable=False),
        sa.Column(
            "workspace_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("citations_json", JSONB(), nullable=False, server_default="[]"),
        sa.Column("metadata_json", JSONB(), nullable=False, server_default="{}"),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_semantic_cache_kb_name", "semantic_cache", ["knowledge_base_name"])
    op.create_index("ix_semantic_cache_workspace_id", "semantic_cache", ["workspace_id"])
    op.create_index("ix_semantic_cache_expires_at", "semantic_cache", ["expires_at"])
    # pgvector column — added via raw DDL for non-pgvector backend compatibility
    op.execute("ALTER TABLE semantic_cache ADD COLUMN IF NOT EXISTS embedding vector")


def downgrade() -> None:
    op.drop_index("ix_semantic_cache_expires_at", table_name="semantic_cache")
    op.drop_index("ix_semantic_cache_workspace_id", table_name="semantic_cache")
    op.drop_index("ix_semantic_cache_kb_name", table_name="semantic_cache")
    op.drop_table("semantic_cache")
