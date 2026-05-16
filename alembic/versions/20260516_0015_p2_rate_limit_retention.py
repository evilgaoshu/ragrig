"""P2: data retention — add retention_days to knowledge_bases.

Revision ID: 20260516_0015
Revises: 20260516_0014
Create Date: 2026-05-16

Adds:
  - knowledge_bases.retention_days  (nullable integer, days to keep old versions)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260516_0015"
down_revision = "20260516_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_bases",
        sa.Column("retention_days", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("knowledge_bases", "retention_days")
