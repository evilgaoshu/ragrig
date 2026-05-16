"""Add workspace_id to chunks and embeddings for direct filtering without joins.

Revision ID: 20260516_0012
Revises: 20260516_0011
Create Date: 2026-05-16 14:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "20260516_0012"
down_revision = "20260516_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add nullable workspace_id columns first
    op.add_column(
        "chunks",
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "embeddings",
        sa.Column("workspace_id", UUID(as_uuid=True), nullable=True),
    )

    # Backfill chunks via document_versions -> documents -> knowledge_bases
    op.execute(
        """
        UPDATE chunks
        SET workspace_id = kb.workspace_id
        FROM document_versions dv
        JOIN documents d ON d.id = dv.document_id
        JOIN knowledge_bases kb ON kb.id = d.knowledge_base_id
        WHERE chunks.document_version_id = dv.id
        """
    )

    # Backfill embeddings via chunks -> document_versions -> documents -> knowledge_bases
    op.execute(
        """
        UPDATE embeddings
        SET workspace_id = kb.workspace_id
        FROM chunks c
        JOIN document_versions dv ON dv.id = c.document_version_id
        JOIN documents d ON d.id = dv.document_id
        JOIN knowledge_bases kb ON kb.id = d.knowledge_base_id
        WHERE embeddings.chunk_id = c.id
        """
    )

    # Add indexes for retrieval performance
    op.create_index("ix_chunks_workspace_id", "chunks", ["workspace_id"])
    op.create_index("ix_embeddings_workspace_id", "embeddings", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_embeddings_workspace_id", table_name="embeddings")
    op.drop_index("ix_chunks_workspace_id", table_name="chunks")
    op.drop_column("embeddings", "workspace_id")
    op.drop_column("chunks", "workspace_id")
