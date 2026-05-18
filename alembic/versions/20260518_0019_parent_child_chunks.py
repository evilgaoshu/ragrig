"""Parent-child chunking: add parent_chunk_id self-reference on chunks.

Revision ID: 20260518_0019
Revises: 20260517_0018
Create Date: 2026-05-18

Adds:
  - ``chunks.parent_chunk_id``  nullable self-FK; non-null on child chunks,
    null on both regular chunks and parent chunks.

Parent chunks use negative chunk_index values (-(i+1)) so that the
existing unique constraint ``uq_chunks_doc_version_index`` remains valid
without schema changes.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20260518_0019"
down_revision = "20260517_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chunks",
        sa.Column(
            "parent_chunk_id",
            UUID(as_uuid=True),
            sa.ForeignKey("chunks.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_chunks_parent_chunk_id", "chunks", ["parent_chunk_id"])


def downgrade() -> None:
    op.drop_index("ix_chunks_parent_chunk_id", table_name="chunks")
    op.drop_column("chunks", "parent_chunk_id")
