"""Add task runtime observability fields.

Revision ID: 20260515_0007
Revises: 20260515_0005
Create Date: 2026-05-15 15:20:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260515_0007"
down_revision = "20260515_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_records",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "task_records",
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "task_records",
        sa.Column("progress", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "task_records",
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.alter_column("task_records", "attempt_count", server_default=None)


def downgrade() -> None:
    op.drop_column("task_records", "attempt_count")
    op.drop_column("task_records", "progress")
    op.drop_column("task_records", "finished_at")
    op.drop_column("task_records", "started_at")
