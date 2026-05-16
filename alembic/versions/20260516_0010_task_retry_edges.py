"""Add structured task retry edge constraints.

Revision ID: 20260516_0010
Revises: 20260516_0009
Create Date: 2026-05-16 12:30:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260516_0010"
down_revision = "20260516_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_records",
        sa.Column("previous_task_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "task_records",
        sa.Column("next_task_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "task_records",
        sa.Column("retry_idempotency_key", sa.String(length=192), nullable=True),
    )

    conn = op.get_bind()
    conn.execute(
        sa.text("""
            UPDATE task_records
            SET previous_task_id = (payload_json ->> 'previous_task_id')::uuid
            WHERE previous_task_id IS NULL
              AND payload_json ? 'previous_task_id'
              AND payload_json ->> 'previous_task_id' ~*
                '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        """)
    )
    conn.execute(
        sa.text("""
            UPDATE task_records
            SET next_task_id = (payload_json ->> 'next_task_id')::uuid
            WHERE next_task_id IS NULL
              AND payload_json ? 'next_task_id'
              AND payload_json ->> 'next_task_id' ~*
                '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        """)
    )
    conn.execute(
        sa.text("""
            UPDATE task_records
            SET retry_idempotency_key = payload_json ->> 'retry_idempotency_key'
            WHERE retry_idempotency_key IS NULL
              AND payload_json ? 'retry_idempotency_key'
              AND payload_json ->> 'retry_idempotency_key' <> ''
        """)
    )

    op.create_check_constraint(
        "ck_task_records_attempt_count_nonnegative",
        "task_records",
        "attempt_count >= 0",
    )
    op.create_check_constraint(
        "ck_task_records_previous_task_not_self",
        "task_records",
        "previous_task_id IS NULL OR previous_task_id <> id",
    )
    op.create_check_constraint(
        "ck_task_records_next_task_not_self",
        "task_records",
        "next_task_id IS NULL OR next_task_id <> id",
    )
    op.create_foreign_key(
        "fk_task_records_previous_task_id",
        "task_records",
        "task_records",
        ["previous_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_task_records_next_task_id",
        "task_records",
        "task_records",
        ["next_task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_task_records_previous_task_id",
        "task_records",
        ["previous_task_id"],
    )
    op.create_unique_constraint(
        "uq_task_records_next_task_id",
        "task_records",
        ["next_task_id"],
    )
    op.create_unique_constraint(
        "uq_task_records_retry_idempotency_key",
        "task_records",
        ["retry_idempotency_key"],
    )
    op.create_index(
        "ix_task_records_previous_task_id",
        "task_records",
        ["previous_task_id"],
    )
    op.create_index(
        "ix_task_records_next_task_id",
        "task_records",
        ["next_task_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_task_records_next_task_id", table_name="task_records")
    op.drop_index("ix_task_records_previous_task_id", table_name="task_records")
    op.drop_constraint("uq_task_records_retry_idempotency_key", "task_records", type_="unique")
    op.drop_constraint("uq_task_records_next_task_id", "task_records", type_="unique")
    op.drop_constraint("uq_task_records_previous_task_id", "task_records", type_="unique")
    op.drop_constraint("fk_task_records_next_task_id", "task_records", type_="foreignkey")
    op.drop_constraint("fk_task_records_previous_task_id", "task_records", type_="foreignkey")
    op.drop_constraint("ck_task_records_next_task_not_self", "task_records", type_="check")
    op.drop_constraint("ck_task_records_previous_task_not_self", "task_records", type_="check")
    op.drop_constraint("ck_task_records_attempt_count_nonnegative", "task_records", type_="check")
    op.drop_column("task_records", "retry_idempotency_key")
    op.drop_column("task_records", "next_task_id")
    op.drop_column("task_records", "previous_task_id")
