from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ragrig.db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Multi-turn answer session.

    A conversation groups a series of question/answer turns. Subsequent turns
    can use earlier ones as context. Bound to a workspace; optionally to a KB
    and a user.
    """

    __tablename__ = "conversations"
    __table_args__ = (
        Index("ix_conversations_workspace_id", "workspace_id"),
        Index("ix_conversations_user_id", "user_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    knowledge_base_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="SET NULL"),
        nullable=True,
    )
    title: Mapped[str | None] = mapped_column(String(255))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    turns: Mapped[list["ConversationTurn"]] = relationship(
        back_populates="conversation",
        order_by="ConversationTurn.turn_index",
        cascade="all, delete-orphan",
    )


class ConversationTurn(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A single Q→A turn inside a conversation."""

    __tablename__ = "conversation_turns"
    __table_args__ = (
        UniqueConstraint("conversation_id", "turn_index", name="uq_conversation_turns_conv_index"),
        Index("ix_conversation_turns_conversation_id", "conversation_id"),
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    grounding_status: Mapped[str | None] = mapped_column(String(32))
    citations_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, nullable=False
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    conversation: Mapped[Conversation] = relationship(back_populates="turns")


class AnswerFeedback(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """User feedback on a single answer turn.

    Rating is -1 (👎), 0 (neutral), or 1 (👍). Optionally carries a reason
    string and the original query for quick triage. Workspace-scoped so admins
    can pull all negatives for a workspace.
    """

    __tablename__ = "answer_feedback"
    __table_args__ = (
        CheckConstraint("rating IN (-1, 0, 1)", name="ck_answer_feedback_rating"),
        Index("ix_answer_feedback_workspace_id", "workspace_id"),
        Index("ix_answer_feedback_turn_id", "turn_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    turn_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation_turns.id", ondelete="CASCADE"),
        nullable=True,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    query: Mapped[str | None] = mapped_column(Text)
    answer_excerpt: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class UsageEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One billable model invocation.

    Captured by the answer/retrieval pipeline so that admins can roll up cost
    per workspace / user / model / operation and trigger budget alerts.
    """

    __tablename__ = "usage_events"
    __table_args__ = (
        Index("ix_usage_events_workspace_id", "workspace_id"),
        Index("ix_usage_events_user_id", "user_id"),
        Index("ix_usage_events_operation", "operation"),
        Index("ix_usage_events_created_at", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Numeric(14, 8), default=0, nullable=False)
    latency_ms: Mapped[float] = mapped_column(Float(), default=0, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class Budget(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Per-workspace monthly spend limit + alert thresholds.

    ``period`` is currently always ``"monthly"`` — left as a string so future
    periods (weekly, daily) can be added without a migration. When
    ``alert_threshold_pct`` of ``limit_usd`` is reached, an email + webhook
    alert is sent (at most once per period). When ``hard_cap`` is true, calls
    beyond the limit are rejected with HTTP 402 Payment Required.
    """

    __tablename__ = "budgets"
    __table_args__ = (
        UniqueConstraint("workspace_id", "period", name="uq_budgets_workspace_period"),
        Index("ix_budgets_workspace_id", "workspace_id"),
        CheckConstraint("period IN ('monthly')", name="ck_budgets_period"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    period: Mapped[str] = mapped_column(String(16), default="monthly", nullable=False)
    limit_usd: Mapped[float] = mapped_column(Numeric(14, 4), nullable=False)
    alert_threshold_pct: Mapped[int] = mapped_column(Integer, default=80, nullable=False)
    hard_cap: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=False)
    last_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
