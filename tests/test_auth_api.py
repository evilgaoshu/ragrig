"""Tests for /auth endpoints (register, login, logout, me)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ragrig.config import Settings
from ragrig.db.models import Base
from ragrig.main import create_app

pytestmark = pytest.mark.unit


def _make_client(*, auth_enabled: bool) -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        ragrig_auth_enabled=auth_enabled,
    )
    app = create_app(
        check_database=lambda: None,
        session_factory=factory,
        settings=settings,
    )
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def auth_client():
    """TestClient with auth enabled and an in-memory SQLite DB."""
    with _make_client(auth_enabled=True) as c:
        yield c


@pytest.fixture
def noauth_client():
    """TestClient with auth disabled."""
    with _make_client(auth_enabled=False) as c:
        yield c


def test_register_creates_user_and_returns_token(auth_client):
    resp = auth_client.post(
        "/auth/register",
        json={"email": "alice@example.com", "password": "hunter2hunter2"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["token"].startswith("rag_session_")
    assert data["email"] == "alice@example.com"
    assert data["role"] == "owner"
    assert "workspace_id" in data


def test_register_duplicate_email_returns_409(auth_client):
    payload = {"email": "bob@example.com", "password": "hunter2hunter2"}
    auth_client.post("/auth/register", json=payload)
    resp = auth_client.post("/auth/register", json=payload)
    assert resp.status_code == 409


def test_register_short_password_rejected(auth_client):
    resp = auth_client.post(
        "/auth/register",
        json={"email": "carol@example.com", "password": "short"},
    )
    assert resp.status_code == 422


def test_login_valid_credentials(auth_client):
    auth_client.post(
        "/auth/register",
        json={"email": "dave@example.com", "password": "correcthorsebatterystaple"},
    )
    resp = auth_client.post(
        "/auth/login",
        json={"email": "dave@example.com", "password": "correcthorsebatterystaple"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["token"].startswith("rag_session_")
    assert data["email"] == "dave@example.com"


def test_login_wrong_password_returns_401(auth_client):
    auth_client.post(
        "/auth/register",
        json={"email": "eve@example.com", "password": "correcthorsebatterystaple"},
    )
    resp = auth_client.post(
        "/auth/login",
        json={"email": "eve@example.com", "password": "wrongpassword"},
    )
    assert resp.status_code == 401


def test_login_unknown_email_returns_401(auth_client):
    resp = auth_client.post(
        "/auth/login",
        json={"email": "nobody@example.com", "password": "doesnotmatter"},
    )
    assert resp.status_code == 401


def test_me_with_valid_token(auth_client):
    reg = auth_client.post(
        "/auth/register",
        json={"email": "frank@example.com", "password": "hunter2hunter2"},
    )
    token = reg.json()["token"]
    resp = auth_client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "frank@example.com"
    assert data["role"] == "owner"


def test_me_without_token_returns_401_when_auth_enabled(auth_client):
    resp = auth_client.get("/auth/me")
    assert resp.status_code == 401


def test_me_without_token_returns_anonymous_when_auth_disabled(noauth_client):
    resp = noauth_client.get("/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == "anonymous"


def test_logout_revokes_token(auth_client):
    reg = auth_client.post(
        "/auth/register",
        json={"email": "grace@example.com", "password": "hunter2hunter2"},
    )
    token = reg.json()["token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    assert auth_client.get("/auth/me", headers=auth_headers).status_code == 200

    logout = auth_client.post("/auth/logout", headers=auth_headers)
    assert logout.status_code == 204

    resp = auth_client.get("/auth/me", headers=auth_headers)
    assert resp.status_code == 401


def test_second_registered_user_gets_viewer_role(auth_client):
    auth_client.post(
        "/auth/register",
        json={"email": "user1@example.com", "password": "hunter2hunter2"},
    )
    resp = auth_client.post(
        "/auth/register",
        json={"email": "user2@example.com", "password": "hunter2hunter2"},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "viewer"


# ── Role guard tests ──────────────────────────────────────────────────────────


def _register(client: TestClient, email: str) -> str:
    resp = client.post(
        "/auth/register",
        json={"email": email, "password": "hunter2hunter2"},
    )
    assert resp.status_code in (201, 409)
    if resp.status_code == 201:
        return resp.json()["token"]
    # already registered — log in
    resp = client.post(
        "/auth/login",
        json={"email": email, "password": "hunter2hunter2"},
    )
    return resp.json()["token"]


def test_viewer_cannot_create_knowledge_base(auth_client):
    """Viewer role must be blocked on POST /knowledge-bases (403)."""
    # first user is owner
    _register(auth_client, "owner@example.com")
    viewer_token = _register(auth_client, "viewer@example.com")

    resp = auth_client.post(
        "/knowledge-bases",
        json={"name": "test-kb"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 403


def test_anonymous_cannot_create_knowledge_base(auth_client):
    """Anonymous (no token) must receive 401 on write routes."""
    resp = auth_client.post("/knowledge-bases", json={"name": "test-kb"})
    assert resp.status_code == 401


def test_owner_can_create_knowledge_base(auth_client):
    """Owner role must be allowed on POST /knowledge-bases."""
    owner_token = _register(auth_client, "owner2@example.com")
    resp = auth_client.post(
        "/knowledge-bases",
        json={"name": "owner-kb"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code in (200, 201)


def test_auth_disabled_allows_write_without_token(noauth_client):
    """When auth is disabled, write routes are open to all."""
    resp = noauth_client.post("/knowledge-bases", json={"name": "open-kb"})
    assert resp.status_code in (200, 201)


# ── User management tests ─────────────────────────────────────────────────────


def test_list_members_requires_auth(auth_client):
    """GET /auth/workspace/members requires authentication."""
    resp = auth_client.get("/auth/workspace/members")
    assert resp.status_code == 401


def test_list_members_returns_all_active_members(auth_client):
    owner_token = _register(auth_client, "owner_mgmt@example.com")
    _register(auth_client, "member_mgmt@example.com")

    resp = auth_client.get(
        "/auth/workspace/members",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 2
    roles = {m["role"] for m in members}
    assert "owner" in roles
    assert "viewer" in roles


def test_patch_member_role_requires_admin(auth_client):
    """PATCH /auth/workspace/members/{id} requires admin or owner."""
    _register(auth_client, "owner_patch@example.com")
    viewer_token = _register(auth_client, "viewer_patch@example.com")

    # Get the owner's user_id to try patching it
    owner_token = auth_client.post(
        "/auth/login",
        json={"email": "owner_patch@example.com", "password": "hunter2hunter2"},
    ).json()["token"]
    owner_id = auth_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {owner_token}"}
    ).json()["user_id"]

    resp = auth_client.patch(
        f"/auth/workspace/members/{owner_id}",
        json={"role": "editor"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 403


def test_owner_can_change_member_role(auth_client):
    """Owner can promote a viewer to editor."""
    owner_token = _register(auth_client, "owner_role@example.com")
    _register(auth_client, "member_role@example.com")

    members = auth_client.get(
        "/auth/workspace/members",
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()
    viewer = next(m for m in members if m["role"] == "viewer")
    viewer_id = viewer["user_id"]

    resp = auth_client.patch(
        f"/auth/workspace/members/{viewer_id}",
        json={"role": "editor"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "editor"


def test_remove_member_requires_admin(auth_client):
    """DELETE /auth/workspace/members/{id} requires admin or owner."""
    _register(auth_client, "owner_del@example.com")
    viewer_token = _register(auth_client, "viewer_del@example.com")

    # Viewer tries to remove someone — gets 403
    owner_token = auth_client.post(
        "/auth/login",
        json={"email": "owner_del@example.com", "password": "hunter2hunter2"},
    ).json()["token"]
    owner_id = auth_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {owner_token}"}
    ).json()["user_id"]

    resp = auth_client.delete(
        f"/auth/workspace/members/{owner_id}",
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 403


def test_owner_can_remove_member(auth_client):
    """Owner can remove a member; they disappear from the member list."""
    owner_token = _register(auth_client, "owner_remove@example.com")
    _register(auth_client, "removee@example.com")

    members = auth_client.get(
        "/auth/workspace/members",
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()
    removee = next(m for m in members if m["role"] == "viewer")
    removee_id = removee["user_id"]

    resp = auth_client.delete(
        f"/auth/workspace/members/{removee_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 204

    members_after = auth_client.get(
        "/auth/workspace/members",
        headers={"Authorization": f"Bearer {owner_token}"},
    ).json()
    ids_after = {m["user_id"] for m in members_after}
    assert removee_id not in ids_after


def test_cannot_remove_self(auth_client):
    """A member cannot remove themselves from the workspace."""
    owner_token = _register(auth_client, "owner_self@example.com")
    owner_id = auth_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {owner_token}"}
    ).json()["user_id"]

    resp = auth_client.delete(
        f"/auth/workspace/members/{owner_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 400


def test_non_owner_cannot_assign_owner_role(auth_client):
    """Admins cannot promote a member to owner."""
    owner_token = _register(auth_client, "owner_noassign@example.com")
    admin_token = _register(auth_client, "admin_noassign@example.com")

    # Promote admin first
    admin_id = auth_client.get(
        "/auth/me", headers={"Authorization": f"Bearer {admin_token}"}
    ).json()["user_id"]
    auth_client.patch(
        f"/auth/workspace/members/{admin_id}",
        json={"role": "admin"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )

    # Admin registers a third user (viewer)
    _register(auth_client, "target_noassign@example.com")
    members = auth_client.get(
        "/auth/workspace/members",
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()
    viewer = next(m for m in members if m["role"] == "viewer")

    resp = auth_client.patch(
        f"/auth/workspace/members/{viewer['user_id']}",
        json={"role": "owner"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 403


# ── Invitation tests ──────────────────────────────────────────────────────────


def _make_closed_client() -> TestClient:
    """Auth enabled + open registration disabled."""
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    settings = Settings(
        database_url="sqlite+pysqlite:///:memory:",
        ragrig_auth_enabled=True,
        ragrig_open_registration=False,
    )
    app = create_app(
        check_database=lambda: None,
        session_factory=factory,
        settings=settings,
    )
    return TestClient(app, raise_server_exceptions=True)


def test_owner_can_create_invitation(auth_client):
    """Owner can create an invitation and receive a token."""
    owner_token = _register(auth_client, "owner_inv@example.com")
    resp = auth_client.post(
        "/auth/workspace/invitations",
        json={"role": "editor", "days": 3},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["token"].startswith("rag_invite_")
    assert data["role"] == "editor"
    assert data["status"] == "pending"


def test_viewer_cannot_create_invitation(auth_client):
    """Viewer is forbidden from creating invitations."""
    _register(auth_client, "owner_inv2@example.com")
    viewer_token = _register(auth_client, "viewer_inv@example.com")
    resp = auth_client.post(
        "/auth/workspace/invitations",
        json={"role": "editor"},
        headers={"Authorization": f"Bearer {viewer_token}"},
    )
    assert resp.status_code == 403


def test_register_with_valid_invitation_token(auth_client):
    """A user can register using a valid invitation token and gets the invited role."""
    owner_token = _register(auth_client, "owner_inv3@example.com")
    inv_resp = auth_client.post(
        "/auth/workspace/invitations",
        json={"role": "editor"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    token = inv_resp.json()["token"]

    resp = auth_client.post(
        "/auth/register",
        json={
            "email": "invited@example.com",
            "password": "hunter2hunter2",
            "invitation_token": token,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "editor"


def test_invitation_token_cannot_be_reused(auth_client):
    """An accepted invitation token is rejected on a second use."""
    owner_token = _register(auth_client, "owner_inv4@example.com")
    inv_resp = auth_client.post(
        "/auth/workspace/invitations",
        json={"role": "viewer"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    token = inv_resp.json()["token"]

    auth_client.post(
        "/auth/register",
        json={
            "email": "used_inv@example.com",
            "password": "hunter2hunter2",
            "invitation_token": token,
        },
    )
    resp = auth_client.post(
        "/auth/register",
        json={
            "email": "second_inv@example.com",
            "password": "hunter2hunter2",
            "invitation_token": token,
        },
    )
    assert resp.status_code == 400


def test_registration_blocked_without_token_when_closed(tmp_path):
    """Registration fails with 403 when open_registration=False and no token."""
    with _make_closed_client() as client:
        # First user (owner) must be seeded via direct DB — but in closed mode,
        # even the first POST /auth/register is blocked without a token.
        resp = client.post(
            "/auth/register",
            json={"email": "blocked@example.com", "password": "hunter2hunter2"},
        )
        assert resp.status_code == 403


def test_owner_can_revoke_invitation(auth_client):
    """Owner can revoke a pending invitation."""
    owner_token = _register(auth_client, "owner_rev@example.com")
    inv_resp = auth_client.post(
        "/auth/workspace/invitations",
        json={"role": "editor"},
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    inv_id = inv_resp.json()["id"]

    resp = auth_client.delete(
        f"/auth/workspace/invitations/{inv_id}",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 204

    # Revoked token should be rejected on register
    token = inv_resp.json()["token"]
    resp2 = auth_client.post(
        "/auth/register",
        json={
            "email": "revoked_inv@example.com",
            "password": "hunter2hunter2",
            "invitation_token": token,
        },
    )
    assert resp2.status_code == 400


def test_list_invitations_shows_pending_only(auth_client):
    """GET /auth/workspace/invitations returns only pending invitations."""
    owner_token = _register(auth_client, "owner_list_inv@example.com")
    # Create two invitations
    for _i in range(2):
        auth_client.post(
            "/auth/workspace/invitations",
            json={"role": "viewer"},
            headers={"Authorization": f"Bearer {owner_token}"},
        )
    resp = auth_client.get(
        "/auth/workspace/invitations",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 2
