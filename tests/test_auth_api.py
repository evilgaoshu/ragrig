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
