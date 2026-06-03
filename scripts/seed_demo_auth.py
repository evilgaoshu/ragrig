"""Seed read-only demo auth users for hosted preview deployments.

The script is idempotent and safe to run after migrations:

    uv run python -m scripts.seed_demo_auth

It creates a hidden owner account to keep the default workspace administrable,
then creates a public demo viewer account.  The viewer credentials are intended
for read-only hosted demos; write routes still require editor-or-above access.
"""

from __future__ import annotations

import json
import os
import secrets
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ragrig.auth import (
    DEFAULT_WORKSPACE_ID,
    DEFAULT_WORKSPACE_SLUG,
    ensure_default_workspace,
    hash_password,
    verify_password,
)
from ragrig.config import get_settings
from ragrig.db.models import User, WorkspaceMembership

DEMO_OWNER_EMAIL = "demo-owner@ragrig.local"
DEMO_VIEWER_EMAIL = "demo@ragrig.dev"
DEMO_VIEWER_PASSWORD = "ragrig-demo-readonly"


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _env(name: str, default: str) -> str:
    value = os.environ.get(name, default).strip()
    return value or default


def _ensure_user(
    session: Session,
    *,
    email: str,
    password: str,
    display_name: str,
    role: str,
    reset_password: bool,
) -> tuple[User, str]:
    normalized_email = email.strip().lower()
    user = session.scalar(select(User).where(User.email == normalized_email).limit(1))
    status = "created"
    if user is None:
        user = User(
            email=normalized_email,
            display_name=display_name,
            password_hash=hash_password(password),
            status="active",
        )
        session.add(user)
        session.flush()
    else:
        user.status = "active"
        user.display_name = user.display_name or display_name
        if reset_password and not verify_password(password, user.password_hash or ""):
            user.password_hash = hash_password(password)
            status = "updated_password"
        else:
            status = "exists"
        session.add(user)
        session.flush()

    membership = session.scalar(
        select(WorkspaceMembership)
        .where(WorkspaceMembership.workspace_id == DEFAULT_WORKSPACE_ID)
        .where(WorkspaceMembership.user_id == user.id)
        .limit(1)
    )
    if membership is None:
        membership = WorkspaceMembership(
            workspace_id=DEFAULT_WORKSPACE_ID,
            user_id=user.id,
            role=role,
            status="active",
        )
        session.add(membership)
        session.flush()
    else:
        if membership.role != role or membership.status != "active":
            status = "updated_role" if status == "exists" else status
        membership.role = role
        membership.status = "active"
        session.add(membership)
        session.flush()

    return user, status


def main() -> int:
    settings = get_settings()
    engine = create_engine(settings.sqlalchemy_runtime_database_url, pool_pre_ping=True)
    owner_email = _env("RAGRIG_DEMO_OWNER_EMAIL", DEMO_OWNER_EMAIL)
    owner_password = os.environ.get("RAGRIG_DEMO_OWNER_PASSWORD") or secrets.token_urlsafe(32)
    viewer_email = _env("RAGRIG_DEMO_USER_EMAIL", DEMO_VIEWER_EMAIL)
    viewer_password = _env("RAGRIG_DEMO_USER_PASSWORD", DEMO_VIEWER_PASSWORD)

    try:
        with Session(engine, expire_on_commit=False) as session:
            workspace = ensure_default_workspace(session)
            owner, owner_status = _ensure_user(
                session,
                email=owner_email,
                password=owner_password,
                display_name="RAGRig Demo Owner",
                role="owner",
                reset_password=bool(os.environ.get("RAGRIG_DEMO_OWNER_PASSWORD")),
            )
            viewer, viewer_status = _ensure_user(
                session,
                email=viewer_email,
                password=viewer_password,
                display_name="RAGRig Read-only Demo",
                role="viewer",
                reset_password=True,
            )
            session.commit()
    finally:
        engine.dispose()

    _emit(
        {
            "status": "ready",
            "workspace": {
                "id": str(workspace.id),
                "slug": DEFAULT_WORKSPACE_SLUG,
            },
            "owner": {
                "id": str(owner.id),
                "email": owner.email,
                "role": "owner",
                "state": owner_status,
                "password_source": (
                    "env" if os.environ.get("RAGRIG_DEMO_OWNER_PASSWORD") else "generated"
                ),
            },
            "viewer": {
                "id": str(viewer.id),
                "email": viewer.email,
                "role": "viewer",
                "state": viewer_status,
                "password_source": "env"
                if os.environ.get("RAGRIG_DEMO_USER_PASSWORD")
                else "default-demo",
            },
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
