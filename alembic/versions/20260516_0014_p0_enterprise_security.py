"""P0 enterprise security: MFA, LDAP/OIDC user fields, audit workspace_id.

Revision ID: 20260516_0014
Revises: 20260516_0013
Create Date: 2026-05-16 14:00:00.000000
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260516_0014"
down_revision = "20260516_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # users: external IdP fields and TOTP MFA
    op.add_column("users", sa.Column("external_auth_provider", sa.String(64), nullable=True))
    op.add_column("users", sa.Column("external_auth_uid", sa.String(512), nullable=True))
    op.add_column(
        "users",
        sa.Column("mfa_enabled", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("users", sa.Column("totp_secret", sa.String(128), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "totp_backup_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )
    op.create_index(
        "ix_users_external_auth_uid", "users", ["external_auth_provider", "external_auth_uid"]
    )

    # audit_events: add workspace_id for scoped queries
    op.add_column(
        "audit_events",
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("ix_audit_events_workspace_id", "audit_events", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_events_workspace_id", table_name="audit_events")
    op.drop_column("audit_events", "workspace_id")

    op.drop_index("ix_users_external_auth_uid", table_name="users")
    op.drop_column("users", "totp_backup_codes")
    op.drop_column("users", "totp_secret")
    op.drop_column("users", "mfa_enabled")
    op.drop_column("users", "external_auth_uid")
    op.drop_column("users", "external_auth_provider")
