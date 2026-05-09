"""Add understanding_runs table.

Revision ID: 20260509_0003
Revises: 20260508_0002
Create Date: 2026-05-09 12:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260509_0003"
down_revision = "20260508_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "understanding_runs",
        # Primary key
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        # Foreign key
        sa.Column("knowledge_base_id", postgresql.UUID(as_uuid=True), nullable=False),
        # Run parameters
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("profile_id", sa.String(length=255), nullable=False),
        # Audit
        sa.Column("trigger_source", sa.String(length=128), nullable=False),
        sa.Column("operator", sa.String(length=255), nullable=True),
        # Status & counts
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("skipped", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # Error summary (safe, no secrets/prompts)
        sa.Column("error_summary", sa.Text(), nullable=True),
        # Timestamps
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        # Standard timestamps from TimestampMixin
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Constraints
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("understanding_runs")
