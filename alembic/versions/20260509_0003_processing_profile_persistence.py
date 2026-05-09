"""Add processing_profile_overrides and processing_profile_audit_log tables.

Revision ID: 20260509_0003
Revises: 20260508_0002
Create Date: 2026-05-09 00:00:00.000000
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
        "processing_profile_overrides",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", sa.String(length=255), nullable=False),
        sa.Column("extension", sa.String(length=32), nullable=False),
        sa.Column("task_type", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "kind",
            sa.String(length=32),
            nullable=False,
            server_default="deterministic",
        ),
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", name="uq_override_profile_id"),
    )
    # Partial unique index: only enforce uniqueness for active, non-deleted overrides
    op.execute(
        "CREATE UNIQUE INDEX uq_override_extension_task_type_active "
        "ON processing_profile_overrides (extension, task_type) "
        "WHERE deleted_at IS NULL AND status != 'disabled'"
    )

    op.create_table(
        "processing_profile_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", sa.String(length=255), nullable=False, index=True),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "old_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "new_state",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_log_profile_id", "processing_profile_audit_log", ["profile_id"]
    )


def downgrade() -> None:
    op.drop_table("processing_profile_audit_log")
    op.drop_table("processing_profile_overrides")
