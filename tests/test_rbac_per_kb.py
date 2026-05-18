"""Unit tests for fine-grained per-KB RBAC (EVI-XXX).

These tests exercise the repository layer only, using the shared SQLite
``sqlite_session`` fixture from conftest.py (same pattern used throughout the
test suite).  No PostgreSQL-specific features are involved.
"""

from __future__ import annotations

import uuid

import pytest

from ragrig.auth import DEFAULT_WORKSPACE_ID, ensure_default_workspace
from ragrig.db.models import KnowledgeBase, User
from ragrig.repositories import (
    delete_kb_permission,
    get_kb_permission,
    get_or_create_knowledge_base,
    list_kb_permissions,
    set_kb_permission,
)
from ragrig.repositories.kb_permission import resolve_effective_kb_role

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(session) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        status="active",
    )
    session.add(user)
    session.flush()
    return user


def _make_kb(session, name: str | None = None) -> KnowledgeBase:
    ensure_default_workspace(session)
    session.flush()
    return get_or_create_knowledge_base(
        session,
        name or f"kb-{uuid.uuid4().hex[:8]}",
        workspace_id=DEFAULT_WORKSPACE_ID,
    )


# ---------------------------------------------------------------------------
# get / set
# ---------------------------------------------------------------------------


def test_set_and_get_kb_permission(sqlite_session) -> None:
    kb = _make_kb(sqlite_session)
    user = _make_user(sqlite_session)

    assert get_kb_permission(sqlite_session, knowledge_base_id=kb.id, user_id=user.id) is None

    set_kb_permission(sqlite_session, knowledge_base_id=kb.id, user_id=user.id, role="editor")
    sqlite_session.flush()

    result = get_kb_permission(sqlite_session, knowledge_base_id=kb.id, user_id=user.id)
    assert result == "editor"


def test_set_kb_permission_upsert_updates_role(sqlite_session) -> None:
    kb = _make_kb(sqlite_session)
    user = _make_user(sqlite_session)

    set_kb_permission(sqlite_session, knowledge_base_id=kb.id, user_id=user.id, role="viewer")
    sqlite_session.flush()

    # Upsert — change role
    set_kb_permission(sqlite_session, knowledge_base_id=kb.id, user_id=user.id, role="admin")
    sqlite_session.flush()

    result = get_kb_permission(sqlite_session, knowledge_base_id=kb.id, user_id=user.id)
    assert result == "admin"


def test_set_kb_permission_role_none(sqlite_session) -> None:
    kb = _make_kb(sqlite_session)
    user = _make_user(sqlite_session)

    set_kb_permission(sqlite_session, knowledge_base_id=kb.id, user_id=user.id, role="none")
    sqlite_session.flush()

    result = get_kb_permission(sqlite_session, knowledge_base_id=kb.id, user_id=user.id)
    assert result == "none"


def test_set_kb_permission_invalid_role_raises(sqlite_session) -> None:
    kb = _make_kb(sqlite_session)
    user = _make_user(sqlite_session)

    with pytest.raises(ValueError, match="invalid KB role"):
        set_kb_permission(
            sqlite_session, knowledge_base_id=kb.id, user_id=user.id, role="superuser"
        )


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_delete_kb_permission_returns_true_when_existed(sqlite_session) -> None:
    kb = _make_kb(sqlite_session)
    user = _make_user(sqlite_session)

    set_kb_permission(sqlite_session, knowledge_base_id=kb.id, user_id=user.id, role="viewer")
    sqlite_session.flush()

    deleted = delete_kb_permission(sqlite_session, knowledge_base_id=kb.id, user_id=user.id)
    sqlite_session.flush()

    assert deleted is True
    assert get_kb_permission(sqlite_session, knowledge_base_id=kb.id, user_id=user.id) is None


def test_delete_kb_permission_returns_false_when_not_existed(sqlite_session) -> None:
    kb = _make_kb(sqlite_session)
    user = _make_user(sqlite_session)

    deleted = delete_kb_permission(sqlite_session, knowledge_base_id=kb.id, user_id=user.id)
    assert deleted is False


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


def test_list_kb_permissions_empty(sqlite_session) -> None:
    kb = _make_kb(sqlite_session)
    assert list_kb_permissions(sqlite_session, knowledge_base_id=kb.id) == []


def test_list_kb_permissions_multiple_users(sqlite_session) -> None:
    kb = _make_kb(sqlite_session)
    alice = _make_user(sqlite_session)
    bob = _make_user(sqlite_session)

    set_kb_permission(sqlite_session, knowledge_base_id=kb.id, user_id=alice.id, role="admin")
    set_kb_permission(sqlite_session, knowledge_base_id=kb.id, user_id=bob.id, role="none")
    sqlite_session.flush()

    perms = list_kb_permissions(sqlite_session, knowledge_base_id=kb.id)
    assert len(perms) == 2

    roles_by_user = {p["user_id"]: p["role"] for p in perms}
    assert roles_by_user[str(alice.id)] == "admin"
    assert roles_by_user[str(bob.id)] == "none"


def test_list_kb_permissions_scoped_to_kb(sqlite_session) -> None:
    """Permissions for one KB must not appear in another KB's listing."""
    kb_a = _make_kb(sqlite_session, "kb-alpha")
    kb_b = _make_kb(sqlite_session, "kb-beta")
    user = _make_user(sqlite_session)

    set_kb_permission(sqlite_session, knowledge_base_id=kb_a.id, user_id=user.id, role="editor")
    sqlite_session.flush()

    assert list_kb_permissions(sqlite_session, knowledge_base_id=kb_b.id) == []
    assert len(list_kb_permissions(sqlite_session, knowledge_base_id=kb_a.id)) == 1


# ---------------------------------------------------------------------------
# resolve_effective_kb_role
# ---------------------------------------------------------------------------


def test_resolve_effective_kb_role_returns_workspace_role_when_no_override(
    sqlite_session,
) -> None:
    kb = _make_kb(sqlite_session)
    user = _make_user(sqlite_session)

    effective = resolve_effective_kb_role(
        sqlite_session,
        user_id=user.id,
        knowledge_base_id=kb.id,
        workspace_role="editor",
    )
    assert effective == "editor"


def test_resolve_effective_kb_role_kb_override_takes_precedence(sqlite_session) -> None:
    kb = _make_kb(sqlite_session)
    user = _make_user(sqlite_session)

    set_kb_permission(sqlite_session, knowledge_base_id=kb.id, user_id=user.id, role="viewer")
    sqlite_session.flush()

    effective = resolve_effective_kb_role(
        sqlite_session,
        user_id=user.id,
        knowledge_base_id=kb.id,
        workspace_role="admin",  # would normally give admin access
    )
    assert effective == "viewer"  # per-KB override wins


def test_resolve_effective_kb_role_none_denies_access(sqlite_session) -> None:
    kb = _make_kb(sqlite_session)
    user = _make_user(sqlite_session)

    set_kb_permission(sqlite_session, knowledge_base_id=kb.id, user_id=user.id, role="none")
    sqlite_session.flush()

    effective = resolve_effective_kb_role(
        sqlite_session,
        user_id=user.id,
        knowledge_base_id=kb.id,
        workspace_role="owner",  # strongest workspace role
    )
    assert effective == "none"  # per-KB 'none' explicitly denies


def test_resolve_effective_kb_role_after_delete_falls_back_to_workspace(
    sqlite_session,
) -> None:
    kb = _make_kb(sqlite_session)
    user = _make_user(sqlite_session)

    set_kb_permission(sqlite_session, knowledge_base_id=kb.id, user_id=user.id, role="none")
    sqlite_session.flush()
    delete_kb_permission(sqlite_session, knowledge_base_id=kb.id, user_id=user.id)
    sqlite_session.flush()

    effective = resolve_effective_kb_role(
        sqlite_session,
        user_id=user.id,
        knowledge_base_id=kb.id,
        workspace_role="editor",
    )
    assert effective == "editor"
