"""Add workspace_id to knowledge_bases.

Revision ID: 20260516_0009
Revises: 20260515_0008
Create Date: 2026-05-16 10:00:00.000000

Strategy:
  1. Add workspace_id as nullable with FK to workspaces.
  2. Backfill all existing rows to DEFAULT_WORKSPACE_ID, ensuring the default
     workspace row exists first.
  3. Set NOT NULL.
  4. Drop the old global UNIQUE(name) constraint.
  5. Add UNIQUE(workspace_id, name) and index on workspace_id.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260516_0009"
down_revision = "20260515_0008"
branch_labels = None
depends_on = None

DEFAULT_WORKSPACE_ID = "00000000-0000-0000-0000-00000000defa"


def upgrade() -> None:
    conn = op.get_bind()

    # Ensure default workspace exists before backfill.
    conn.execute(
        sa.text("""
            INSERT INTO workspaces (id, slug, display_name, status, metadata_json,
                                    created_at, updated_at)
            VALUES (:id, 'default', 'Default Workspace', 'active', '{}',
                    now(), now())
            ON CONFLICT (id) DO NOTHING
        """),
        {"id": DEFAULT_WORKSPACE_ID},
    )

    # Add workspace_id nullable first to allow backfill.
    op.add_column(
        "knowledge_bases",
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )

    # Backfill existing rows.
    conn.execute(
        sa.text(
            "UPDATE knowledge_bases SET workspace_id = :wid WHERE workspace_id IS NULL"
        ),
        {"wid": DEFAULT_WORKSPACE_ID},
    )

    # Set NOT NULL.
    op.alter_column("knowledge_bases", "workspace_id", nullable=False)

    # Add FK constraint.
    op.create_foreign_key(
        "fk_knowledge_bases_workspace_id",
        "knowledge_bases",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Drop old global unique constraint on name.
    op.drop_constraint("knowledge_bases_name_key", "knowledge_bases", type_="unique")

    # Add composite unique and index.
    op.create_unique_constraint(
        "uq_knowledge_bases_workspace_name",
        "knowledge_bases",
        ["workspace_id", "name"],
    )
    op.create_index(
        "ix_knowledge_bases_workspace_id",
        "knowledge_bases",
        ["workspace_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_bases_workspace_id", table_name="knowledge_bases")
    op.drop_constraint(
        "uq_knowledge_bases_workspace_name", "knowledge_bases", type_="unique"
    )
    op.create_unique_constraint(
        "knowledge_bases_name_key", "knowledge_bases", ["name"]
    )
    op.drop_constraint(
        "fk_knowledge_bases_workspace_id", "knowledge_bases", type_="foreignkey"
    )
    op.drop_column("knowledge_bases", "workspace_id")
