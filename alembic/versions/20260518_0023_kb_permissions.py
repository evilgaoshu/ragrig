"""add knowledge_base_permissions table

Revision ID: 20260518_0023
Revises: 20260518_0022
Create Date: 2026-05-18

Adds a ``knowledge_base_permissions`` table that stores per-KB role overrides
for individual users.  When a row exists for a (knowledge_base_id, user_id)
pair the role stored here takes precedence over the user's workspace-level
role.  A role value of ``'none'`` explicitly denies access.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260518_0023"
down_revision = "20260518_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_base_permissions",
        sa.Column(
            "knowledge_base_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("knowledge_base_id", "user_id"),
        sa.CheckConstraint(
            "role IN ('admin', 'editor', 'viewer', 'none')",
            name="ck_kb_permissions_role",
        ),
        sa.UniqueConstraint(
            "knowledge_base_id",
            "user_id",
            name="uq_kb_permissions_kb_user",
        ),
    )
    op.create_index(
        "ix_kb_permissions_kb_id",
        "knowledge_base_permissions",
        ["knowledge_base_id"],
    )
    op.create_index(
        "ix_kb_permissions_user_id",
        "knowledge_base_permissions",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_kb_permissions_user_id",
        table_name="knowledge_base_permissions",
    )
    op.drop_index(
        "ix_kb_permissions_kb_id",
        table_name="knowledge_base_permissions",
    )
    op.drop_table("knowledge_base_permissions")
