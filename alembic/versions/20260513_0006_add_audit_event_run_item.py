"""Add run_id and item_id columns to audit_events.

Revision ID: 20260513_0006
Revises: 20260512_0005
Create Date: 2026-05-13 09:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260513_0006"
down_revision = "20260512_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_events",
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "audit_events",
        sa.Column(
            "item_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_audit_events_run_id",
        "audit_events",
        "pipeline_runs",
        ["run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_audit_events_item_id",
        "audit_events",
        "pipeline_run_items",
        ["item_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_audit_events_run_id", "audit_events", ["run_id"])
    op.create_index("ix_audit_events_item_id", "audit_events", ["item_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_item_id", table_name="audit_events")
    op.drop_index("ix_audit_events_run_id", table_name="audit_events")
    op.drop_constraint("fk_audit_events_item_id", "audit_events", type_="foreignkey")
    op.drop_constraint("fk_audit_events_run_id", "audit_events", type_="foreignkey")
    op.drop_column("audit_events", "item_id")
    op.drop_column("audit_events", "run_id")
