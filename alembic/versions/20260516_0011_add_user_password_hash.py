"""Add password_hash to users.

Revision ID: 20260516_0011
Revises: 20260516_0010
Create Date: 2026-05-16 12:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "20260516_0011"
down_revision = "20260516_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "password_hash")
