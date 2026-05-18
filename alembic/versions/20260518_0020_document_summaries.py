"""Document-level summary indexing: add document_summaries table.

Revision ID: 20260518_0020
Revises: 20260518_0019
Create Date: 2026-05-18

Adds:
  - ``document_summaries``  LLM-generated summary + embedding per document version.
    Used for document-level retrieval: broad queries that match a document as a
    whole rather than any single chunk.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "20260518_0020"
down_revision = "20260518_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "document_summaries",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "document_version_id",
            UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        # Vector column added via raw DDL — pgvector type is not in core SQLAlchemy
        sa.Column("metadata_json", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("document_version_id", name="uq_document_summaries_doc_version"),
    )
    op.create_index("ix_document_summaries_workspace_id", "document_summaries", ["workspace_id"])
    # Add pgvector column separately so the migration works on non-pgvector backends too
    op.execute("ALTER TABLE document_summaries ADD COLUMN IF NOT EXISTS embedding vector")


def downgrade() -> None:
    op.drop_index("ix_document_summaries_workspace_id", table_name="document_summaries")
    op.drop_table("document_summaries")
