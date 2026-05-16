"""P3c: usage events + budgets.

Revision ID: 20260516_0017
Revises: 20260516_0016
Create Date: 2026-05-16

Adds:
  - ``usage_events``  per-call cost/latency/tokens, scoped to workspace+user
  - ``budgets``       per-workspace monthly spend limits + alert thresholds
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "20260516_0017"
down_revision = "20260516_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("operation", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(128), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(14, 8), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Float(), nullable=False, server_default="0"),
        sa.Column("metadata_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_usage_events_workspace_id", "usage_events", ["workspace_id"])
    op.create_index("ix_usage_events_user_id", "usage_events", ["user_id"])
    op.create_index("ix_usage_events_operation", "usage_events", ["operation"])
    op.create_index("ix_usage_events_created_at", "usage_events", ["created_at"])

    op.create_table(
        "budgets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period", sa.String(16), nullable=False, server_default="monthly"),
        sa.Column("limit_usd", sa.Numeric(14, 4), nullable=False),
        sa.Column("alert_threshold_pct", sa.Integer, nullable=False, server_default="80"),
        sa.Column("hard_cap", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_alert_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("workspace_id", "period", name="uq_budgets_workspace_period"),
        sa.CheckConstraint("period IN ('monthly')", name="ck_budgets_period"),
    )
    op.create_index("ix_budgets_workspace_id", "budgets", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_budgets_workspace_id", table_name="budgets")
    op.drop_table("budgets")

    op.drop_index("ix_usage_events_created_at", table_name="usage_events")
    op.drop_index("ix_usage_events_operation", table_name="usage_events")
    op.drop_index("ix_usage_events_user_id", table_name="usage_events")
    op.drop_index("ix_usage_events_workspace_id", table_name="usage_events")
    op.drop_table("usage_events")
