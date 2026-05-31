from __future__ import annotations

import uuid

import pytest
from conftest import _create_session
from fastapi import HTTPException

from ragrig.auth import API_KEY_TOKEN_PREFIX
from ragrig.config import Settings
from ragrig.deps import AuthContext
from ragrig.services import auth as auth_service

pytestmark = pytest.mark.unit


def test_register_account_and_current_user_round_trip() -> None:
    settings = Settings(ragrig_auth_enabled=True)
    with _create_session() as session:
        payload = auth_service.register_account(
            session,
            email="service-user@example.com",
            password="hunter2hunter2",
            display_name="Service User",
            invitation_token=None,
            settings=settings,
        )

        assert payload["token"].startswith("rag_session_")
        assert payload["email"] == "service-user@example.com"
        assert payload["display_name"] == "Service User"
        assert payload["role"] == "owner"

        current = auth_service.current_user(
            session,
            authorization=f"Bearer {payload['token']}",
            settings=settings,
        )

    assert current["user_id"] == payload["user_id"]
    assert current["email"] == "service-user@example.com"
    assert current["role"] == "owner"


def test_register_account_requires_invitation_when_registration_closed() -> None:
    settings = Settings(ragrig_auth_enabled=True, ragrig_open_registration=False)
    with _create_session() as session:
        with pytest.raises(HTTPException) as exc_info:
            auth_service.register_account(
                session,
                email="blocked@example.com",
                password="hunter2hunter2",
                display_name=None,
                invitation_token=None,
                settings=settings,
            )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "registration requires an invitation token"


def test_workspace_api_key_lifecycle_filters_revoked_keys() -> None:
    settings = Settings(ragrig_auth_enabled=True)
    with _create_session() as session:
        payload = auth_service.register_account(
            session,
            email="key-owner@example.com",
            password="hunter2hunter2",
            display_name=None,
            invitation_token=None,
            settings=settings,
        )
        auth = AuthContext(
            workspace_id=uuid.UUID(payload["workspace_id"]),
            user_id=uuid.UUID(payload["user_id"]),
            is_anonymous=False,
            scopes=["*"],
            role="owner",
        )

        created = auth_service.create_workspace_api_key(
            session,
            auth,
            name="service-key",
            scopes=["kb:read"],
            expires_days=7,
        )
        active = auth_service.list_workspace_api_keys(session, auth, include_revoked=False)
        auth_service.revoke_workspace_api_key(session, auth, key_id=uuid.UUID(created["id"]))
        visible = auth_service.list_workspace_api_keys(session, auth, include_revoked=True)
        hidden = auth_service.list_workspace_api_keys(session, auth, include_revoked=False)

    assert created["token"].startswith(API_KEY_TOKEN_PREFIX)
    assert [item["id"] for item in active] == [created["id"]]
    assert [item["id"] for item in visible] == [created["id"]]
    assert visible[0]["revoked_at"] is not None
    assert hidden == []
