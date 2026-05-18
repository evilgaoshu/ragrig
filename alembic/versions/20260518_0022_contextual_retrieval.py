"""Contextual retrieval: add context_prefix column to chunks.

Revision ID: 20260518_0022
Revises: 20260518_0021
Create Date: 2026-05-18

Adds:
  - ``chunks.context_prefix``  nullable text column that stores the AI-generated
    context prepended to a chunk's text before embedding.  NULL for chunks indexed
    without contextual retrieval enabled.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260518_0022"
down_revision = "20260518_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chunks", sa.Column("context_prefix", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("chunks", "context_prefix")
