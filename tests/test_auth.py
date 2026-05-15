from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ragrig.auth import (
    create_api_key,
    create_user_session,
    ensure_default_workspace,
    principal_group_subjects,
    principal_user_subject,
    verify_api_key,
    verify_session_token,
)
from ragrig.db.models import User

pytestmark = pytest.mark.unit


def test_default_workspace_bootstrap_is_idempotent(sqlite_session) -> None:
    first = ensure_default_workspace(sqlite_session)
    second = ensure_default_workspace(sqlite_session)

    assert first.id == second.id
    assert second.slug == "default"
    assert second.display_name == "Default Workspace"


def test_api_key_create_and_verify_stores_hash_only(sqlite_session) -> None:
    workspace = ensure_default_workspace(sqlite_session)
    user = User(email="dev@example.com", display_name="Dev", status="active")
    sqlite_session.add(user)
    sqlite_session.flush()

    created = create_api_key(
        sqlite_session,
        workspace_id=workspace.id,
        created_by_user_id=user.id,
        name="local dev",
        scopes=["kb:read"],
        pepper="test-pepper",
    )
    sqlite_session.commit()

    assert created.token.startswith(f"rag_live_{created.api_key.prefix}_")
    assert created.token not in created.api_key.secret_hash
    assert created.api_key.secret_hash.startswith("hmac-sha256:")
    assert created.api_key.prefix

    verified = verify_api_key(
        sqlite_session,
        created.token,
        workspace_id=workspace.id,
        required_scope="kb:read",
        pepper="test-pepper",
    )

    assert verified is not None
    assert verified.id == created.api_key.id


def test_api_key_verify_rejects_wrong_scope_and_revoked_keys(sqlite_session) -> None:
    workspace = ensure_default_workspace(sqlite_session)
    created = create_api_key(
        sqlite_session,
        workspace_id=workspace.id,
        name="limited",
        scopes=["kb:read"],
        pepper="test-pepper",
    )

    assert (
        verify_api_key(
            sqlite_session,
            created.token,
            required_scope="document:write",
            pepper="test-pepper",
        )
        is None
    )

    created.api_key.revoked_at = datetime.now(UTC)
    sqlite_session.flush()

    assert verify_api_key(sqlite_session, created.token, pepper="test-pepper") is None


def test_user_session_create_and_verify_stores_hash_only(sqlite_session) -> None:
    workspace = ensure_default_workspace(sqlite_session)
    user = User(email="session@example.com", display_name="Session User", status="active")
    sqlite_session.add(user)
    sqlite_session.flush()
    expires_at = datetime.now(UTC) + timedelta(hours=1)

    created = create_user_session(
        sqlite_session,
        workspace_id=workspace.id,
        user_id=user.id,
        scopes=["retrieval:search"],
        expires_at=expires_at,
        ip="127.0.0.1",
        user_agent="pytest",
        pepper="test-pepper",
    )
    sqlite_session.commit()

    assert created.token.startswith("rag_session_")
    assert created.token not in created.session.token_hash
    assert created.session.token_hash.startswith("hmac-sha256:")
    assert created.session.ip_hash is not None
    assert created.session.user_agent_hash is not None

    verified = verify_session_token(
        sqlite_session,
        created.token,
        workspace_id=workspace.id,
        required_scope="retrieval:search",
        pepper="test-pepper",
    )

    assert verified is not None
    assert verified.id == created.session.id


def test_expired_session_token_verification_fails(sqlite_session) -> None:
    workspace = ensure_default_workspace(sqlite_session)
    user = User(email="expired@example.com", display_name="Expired User", status="active")
    sqlite_session.add(user)
    sqlite_session.flush()
    now = datetime.now(UTC)

    created = create_user_session(
        sqlite_session,
        workspace_id=workspace.id,
        user_id=user.id,
        expires_at=now - timedelta(seconds=1),
        pepper="test-pepper",
    )

    assert (
        verify_session_token(
            sqlite_session,
            created.token,
            now=now,
            pepper="test-pepper",
        )
        is None
    )


def test_principal_subject_helpers_reserve_acl_mapping() -> None:
    assert principal_user_subject("42") == "user:42"
    assert principal_group_subjects(["engineering", "finance"]) == [
        "group:engineering",
        "group:finance",
    ]
