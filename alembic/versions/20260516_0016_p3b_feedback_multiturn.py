"""P3b: feedback + multi-turn conversation tables.

Revision ID: 20260516_0016
Revises: 20260516_0015
Create Date: 2026-05-16

Adds:
  - ``conversations``                 grouping multi-turn answer sessions
  - ``conversation_turns``            individual Q/A turns
  - ``answer_feedback``               👍/👎 feedback rows
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "20260516_0016"
down_revision = "20260516_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
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
        sa.Column(
            "knowledge_base_id",
            UUID(as_uuid=True),
            sa.ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("metadata_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_conversations_workspace_id", "conversations", ["workspace_id"])
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])

    op.create_table(
        "conversation_turns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("turn_index", sa.Integer, nullable=False),
        sa.Column("query", sa.Text, nullable=False),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("grounding_status", sa.String(32), nullable=True),
        sa.Column("citations_json", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("metadata_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "conversation_id", "turn_index", name="uq_conversation_turns_conv_index"
        ),
    )
    op.create_index(
        "ix_conversation_turns_conversation_id", "conversation_turns", ["conversation_id"]
    )

    op.create_table(
        "answer_feedback",
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
        sa.Column(
            "turn_id",
            UUID(as_uuid=True),
            sa.ForeignKey("conversation_turns.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("rating", sa.Integer, nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("query", sa.Text, nullable=True),
        sa.Column("answer_excerpt", sa.Text, nullable=True),
        sa.Column("metadata_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("rating IN (-1, 0, 1)", name="ck_answer_feedback_rating"),
    )
    op.create_index("ix_answer_feedback_workspace_id", "answer_feedback", ["workspace_id"])
    op.create_index("ix_answer_feedback_turn_id", "answer_feedback", ["turn_id"])


def downgrade() -> None:
    op.drop_index("ix_answer_feedback_turn_id", table_name="answer_feedback")
    op.drop_index("ix_answer_feedback_workspace_id", table_name="answer_feedback")
    op.drop_table("answer_feedback")

    op.drop_index(
        "ix_conversation_turns_conversation_id", table_name="conversation_turns"
    )
    op.drop_table("conversation_turns")

    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_index("ix_conversations_workspace_id", table_name="conversations")
    op.drop_table("conversations")
