"""P0 enterprise-security feature tests.

Covers:
- Audit log query API (GET /audit/events)
- LDAP authentication (unit-level with fake LDAP)
- OIDC authentication (unit-level with mocked IdP)
- MFA / TOTP setup, confirm, disable, challenge
- PII detection and redaction (pii module)
- Hard delete / right to erasure
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine, event, select
from sqlalchemy.orm import Session

from ragrig.auth import (
    DEFAULT_WORKSPACE_ID,
    ensure_default_workspace,
)
from ragrig.auth_mfa import (
    consume_backup_code,
    generate_backup_codes,
    generate_totp_secret,
    totp_provisioning_uri,
    verify_totp,
)
from ragrig.db.models import (
    Base,
    User,
    Workspace,
)
from ragrig.pii import redact, scan
from ragrig.repositories.audit import create_audit_event, list_audit_events


def _make_workspace(session: Session, ws_id: uuid.UUID | None = None) -> Workspace:
    wid = ws_id or uuid.uuid4()
    ws = Workspace(
        id=wid,
        slug=str(wid)[:8],
        display_name="test",
        status="active",
        metadata_json={},
    )
    session.add(ws)
    session.flush()
    return ws


# ── In-memory SQLite fixture ──────────────────────────────────────────────────


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _enable_fk(conn, _):
        conn.execute("PRAGMA foreign_keys = ON")

    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def mem_session(engine):
    with Session(engine) as s:
        yield s


# ── App client fixtures ───────────────────────────────────────────────────────


def _make_test_app(engine):
    from ragrig.config import Settings
    from ragrig.db.session import get_session
    from ragrig.main import create_app

    settings = Settings(
        database_url="sqlite://",
        ragrig_auth_enabled=True,
        ragrig_open_registration=True,
        ragrig_ldap_enabled=False,
        ragrig_oidc_enabled=False,
        ragrig_mfa_backup_code_count=4,
    )

    def override_session():
        with Session(engine) as s:
            yield s

    app = create_app(settings=settings, session_factory=None)
    app.dependency_overrides[get_session] = override_session
    return app, settings


@pytest.fixture
def test_app(engine):
    return _make_test_app(engine)


@pytest.fixture
def client(test_app):
    app, _ = test_app
    return TestClient(app, raise_server_exceptions=True)


def _register(client: TestClient, email: str, password: str = "Password1!") -> str:
    resp = client.post("/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.json()
    return resp.json()["token"]


# ── PII module tests ──────────────────────────────────────────────────────────


@pytest.mark.unit
class TestPii:
    def test_redacts_email(self):
        result = redact("Contact us at support@example.com for help.")
        assert "[PII_EMAIL]" in result.redacted_text
        assert "support@example.com" not in result.redacted_text
        assert result.hit_count >= 1

    def test_redacts_ssn(self):
        result = redact("SSN: 123-45-6789 on file.")
        assert "[PII_SSN]" in result.redacted_text
        assert "123-45-6789" not in result.redacted_text

    def test_redacts_credit_card(self):
        result = redact("Card number 4111111111111111 approved.")
        assert "[PII_CC]" in result.redacted_text

    def test_redacts_ip_address(self):
        result = redact("Request from 192.168.1.100.")
        assert "[PII_IP]" in result.redacted_text

    def test_scan_returns_labels(self):
        labels = scan("Call 555-867-5309 or email foo@bar.com")
        assert "[PII_PHONE]" in labels
        assert "[PII_EMAIL]" in labels

    def test_clean_text_unchanged(self):
        text = "The quick brown fox jumps over the lazy dog."
        result = redact(text)
        assert result.redacted_text == text
        assert result.hit_count == 0

    def test_multiple_instances_all_redacted(self):
        result = redact("a@b.com and c@d.com are both here")
        assert result.redacted_text.count("[PII_EMAIL]") == 2


# ── MFA / TOTP unit tests ─────────────────────────────────────────────────────


@pytest.mark.unit
class TestMfa:
    def test_totp_verify_valid_code(self):
        import pyotp

        secret = generate_totp_secret()
        code = pyotp.TOTP(secret).now()
        assert verify_totp(secret, code)

    def test_totp_verify_wrong_code(self):
        secret = generate_totp_secret()
        assert not verify_totp(secret, "000000")

    def test_backup_codes_generated(self):
        plain, hashed = generate_backup_codes(4)
        assert len(plain) == 4
        assert len(hashed) == 4
        assert all(len(c) == 10 for c in plain)

    def test_consume_backup_code_success(self):
        plain, hashed = generate_backup_codes(3)
        remaining = consume_backup_code(plain[1], hashed)
        assert remaining is not None
        assert len(remaining) == 2

    def test_consume_backup_code_wrong_returns_none(self):
        _, hashed = generate_backup_codes(2)
        assert consume_backup_code("wrongcode!", hashed) is None

    def test_backup_code_single_use(self):
        plain, hashed = generate_backup_codes(2)
        remaining = consume_backup_code(plain[0], hashed)
        assert remaining is not None
        # Code is gone from remaining list — cannot reuse
        assert consume_backup_code(plain[0], remaining) is None

    def test_provisioning_uri_contains_issuer(self):
        from ragrig.config import Settings

        secret = generate_totp_secret()
        settings = Settings(ragrig_mfa_issuer="AcmeCorp")
        uri = totp_provisioning_uri(secret, "user@example.com", settings)
        assert "AcmeCorp" in uri
        assert "user%40example.com" in uri or "user@example.com" in uri


# ── Audit log repository tests ────────────────────────────────────────────────


@pytest.mark.unit
class TestAuditRepo:
    def test_create_and_list_by_workspace(self, mem_session):
        ws = _make_workspace(mem_session)
        other = _make_workspace(mem_session)
        create_audit_event(
            mem_session, event_type="acl_write", actor="user:abc", workspace_id=ws.id
        )
        create_audit_event(
            mem_session, event_type="retrieval_filter", actor="user:xyz", workspace_id=other.id
        )
        events = list_audit_events(mem_session, workspace_id=ws.id)
        assert len(events) == 1
        assert events[0].workspace_id == ws.id

    def test_filter_by_event_type(self, mem_session):
        ws = _make_workspace(mem_session)
        create_audit_event(mem_session, event_type="acl_write", workspace_id=ws.id)
        create_audit_event(mem_session, event_type="access_denied", workspace_id=ws.id)
        events = list_audit_events(mem_session, workspace_id=ws.id, event_type="acl_write")
        assert all(e.event_type == "acl_write" for e in events)

    def test_pagination_offset_limit(self, mem_session):
        ws = _make_workspace(mem_session)
        for _ in range(5):
            create_audit_event(mem_session, event_type="acl_write", workspace_id=ws.id)
        page1 = list_audit_events(mem_session, workspace_id=ws.id, limit=3, offset=0)
        page2 = list_audit_events(mem_session, workspace_id=ws.id, limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 2
        ids1 = {str(e.id) for e in page1}
        ids2 = {str(e.id) for e in page2}
        assert ids1.isdisjoint(ids2)

    def test_filter_by_actor(self, mem_session):
        ws = _make_workspace(mem_session)
        create_audit_event(mem_session, event_type="acl_write", actor="alice", workspace_id=ws.id)
        create_audit_event(mem_session, event_type="acl_write", actor="bob", workspace_id=ws.id)
        events = list_audit_events(mem_session, workspace_id=ws.id, actor="alice")
        assert len(events) == 1
        assert events[0].actor == "alice"


# ── Audit API endpoint tests ──────────────────────────────────────────────────


@pytest.mark.unit
class TestAuditApi:
    def test_requires_admin(self, client):
        _register(client, "viewer_audit@example.com")  # first user becomes owner
        viewer_token = _register(client, "viewer2_audit@example.com")

        resp = client.get(
            "/audit/events",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert resp.status_code == 403

    def test_admin_can_list(self, client):
        token = _register(client, "admin_audit@example.com")
        resp = client.get("/audit/events", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_unauthenticated_rejected(self, client):
        resp = client.get("/audit/events")
        assert resp.status_code == 401

    def test_filter_by_event_type_query_param(self, client, engine):
        token = _register(client, "admin_filter_audit@example.com")
        with Session(engine) as s:
            ensure_default_workspace(s)
            create_audit_event(
                s,
                event_type="acl_write",
                workspace_id=DEFAULT_WORKSPACE_ID,
            )
            create_audit_event(
                s,
                event_type="access_denied",
                workspace_id=DEFAULT_WORKSPACE_ID,
            )
            s.commit()

        resp = client.get(
            "/audit/events?event_type=acl_write",
            headers={"Authorization": f"Bearer {token}"},
        )
        data = resp.json()
        assert resp.status_code == 200
        assert all(e["event_type"] == "acl_write" for e in data)


# ── MFA API endpoint tests ────────────────────────────────────────────────────


@pytest.mark.unit
class TestMfaApi:
    def test_mfa_setup_returns_qr_and_backup_codes(self, client):
        token = _register(client, "mfa_setup@example.com")
        resp = client.post("/auth/mfa/setup", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        data = resp.json()
        assert "qr_png_b64" in data
        assert "provisioning_uri" in data
        assert len(data["backup_codes"]) == 4

    def test_mfa_confirm_with_valid_totp(self, client, engine):
        import pyotp

        token = _register(client, "mfa_confirm@example.com")
        setup_resp = client.post("/auth/mfa/setup", headers={"Authorization": f"Bearer {token}"})
        assert setup_resp.status_code == 200

        # Get the secret directly from DB
        with Session(engine) as s:
            user = s.scalar(select(User).where(User.email == "mfa_confirm@example.com").limit(1))
            secret = user.totp_secret

        code = pyotp.TOTP(secret).now()
        confirm_resp = client.post(
            "/auth/mfa/confirm",
            json={"code": code},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert confirm_resp.status_code == 200
        assert confirm_resp.json()["mfa_enabled"] is True

    def test_mfa_confirm_invalid_code_rejected(self, client):
        token = _register(client, "mfa_bad_confirm@example.com")
        client.post("/auth/mfa/setup", headers={"Authorization": f"Bearer {token}"})
        resp = client.post(
            "/auth/mfa/confirm",
            json={"code": "000000"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    def test_login_returns_mfa_pending_when_mfa_enabled(self, client, engine):
        import pyotp

        email = "mfa_login@example.com"
        token = _register(client, email)
        client.post("/auth/mfa/setup", headers={"Authorization": f"Bearer {token}"})

        with Session(engine) as s:
            user = s.scalar(select(User).where(User.email == email).limit(1))
            secret = user.totp_secret

        code = pyotp.TOTP(secret).now()
        client.post(
            "/auth/mfa/confirm",
            json={"code": code},
            headers={"Authorization": f"Bearer {token}"},
        )

        # Now login should return mfa_required=True
        login_resp = client.post("/auth/login", json={"email": email, "password": "Password1!"})
        assert login_resp.status_code == 200
        data = login_resp.json()
        assert data["mfa_required"] is True

    def test_mfa_challenge_completes_login(self, client, engine):
        import pyotp

        email = "mfa_challenge@example.com"
        token = _register(client, email)
        client.post("/auth/mfa/setup", headers={"Authorization": f"Bearer {token}"})

        with Session(engine) as s:
            user = s.scalar(select(User).where(User.email == email).limit(1))
            secret = user.totp_secret

        code = pyotp.TOTP(secret).now()
        client.post(
            "/auth/mfa/confirm",
            json={"code": code},
            headers={"Authorization": f"Bearer {token}"},
        )

        login_resp = client.post("/auth/login", json={"email": email, "password": "Password1!"})
        pending_token = login_resp.json()["token"]

        code2 = pyotp.TOTP(secret).now()
        challenge_resp = client.post(
            "/auth/mfa/challenge",
            json={"session_token": pending_token, "code": code2},
        )
        assert challenge_resp.status_code == 200
        full_token = challenge_resp.json()["token"]
        assert full_token != pending_token
        assert challenge_resp.json()["mfa_required"] is False

    def test_mfa_challenge_wrong_code_rejected(self, client, engine):
        import pyotp

        email = "mfa_challenge_bad@example.com"
        token = _register(client, email)
        client.post("/auth/mfa/setup", headers={"Authorization": f"Bearer {token}"})

        with Session(engine) as s:
            user = s.scalar(select(User).where(User.email == email).limit(1))
            secret = user.totp_secret

        code = pyotp.TOTP(secret).now()
        client.post(
            "/auth/mfa/confirm",
            json={"code": code},
            headers={"Authorization": f"Bearer {token}"},
        )
        login_resp = client.post("/auth/login", json={"email": email, "password": "Password1!"})
        pending_token = login_resp.json()["token"]

        challenge_resp = client.post(
            "/auth/mfa/challenge",
            json={"session_token": pending_token, "code": "000000"},
        )
        assert challenge_resp.status_code == 401

    def test_mfa_challenge_with_backup_code(self, client, engine):
        import pyotp

        email = "mfa_backup@example.com"
        token = _register(client, email)
        setup_resp = client.post("/auth/mfa/setup", headers={"Authorization": f"Bearer {token}"})
        backup_codes = setup_resp.json()["backup_codes"]

        with Session(engine) as s:
            user = s.scalar(select(User).where(User.email == email).limit(1))
            secret = user.totp_secret

        code = pyotp.TOTP(secret).now()
        client.post(
            "/auth/mfa/confirm",
            json={"code": code},
            headers={"Authorization": f"Bearer {token}"},
        )
        login_resp = client.post("/auth/login", json={"email": email, "password": "Password1!"})
        pending_token = login_resp.json()["token"]

        # Use backup code instead of TOTP
        challenge_resp = client.post(
            "/auth/mfa/challenge",
            json={"session_token": pending_token, "code": backup_codes[0]},
        )
        assert challenge_resp.status_code == 200


# ── Hard-delete / right-to-erasure tests ─────────────────────────────────────


@pytest.mark.unit
class TestErasure:
    def test_delete_own_account(self, client, engine):
        email = "erase_me@example.com"
        token = _register(client, email)

        resp = client.delete("/auth/users/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 204

        with Session(engine) as s:
            # Email is nulled out after erasure — look by status
            all_deleted = s.scalars(select(User).where(User.status == "deleted")).all()
            assert len(all_deleted) >= 1
            # The token should no longer work
        me_resp = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me_resp.status_code == 401

    def test_erase_requires_owner(self, client, engine):
        _register(client, "erase_owner@example.com")  # becomes owner
        viewer_token = _register(client, "erase_target@example.com")

        # Get target user_id
        me = client.get("/auth/me", headers={"Authorization": f"Bearer {viewer_token}"})
        target_id = me.json()["user_id"]

        # Admin (viewer) cannot erase
        resp = client.delete(
            f"/auth/workspace/members/{target_id}/erase",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
        assert resp.status_code == 403

    def test_owner_can_erase_member(self, client, engine):
        owner_token = _register(client, "erase_owner2@example.com")
        victim_token = _register(client, "erase_victim@example.com")

        me = client.get("/auth/me", headers={"Authorization": f"Bearer {victim_token}"})
        target_id = me.json()["user_id"]

        resp = client.delete(
            f"/auth/workspace/members/{target_id}/erase",
            headers={"Authorization": f"Bearer {owner_token}"},
        )
        assert resp.status_code == 204

        # Victim's token is revoked
        me2 = client.get("/auth/me", headers={"Authorization": f"Bearer {victim_token}"})
        assert me2.status_code == 401

    def test_sessions_revoked_after_erasure(self, client, engine):
        email = "erase_sessions@example.com"
        token = _register(client, email)

        # Create a second session
        login = client.post("/auth/login", json={"email": email, "password": "Password1!"})
        token2 = login.json()["token"]

        client.delete("/auth/users/me", headers={"Authorization": f"Bearer {token}"})

        # Both sessions should be dead
        r = client.get("/auth/me", headers={"Authorization": f"Bearer {token2}"})
        assert r.status_code == 401


# ── LDAP unit tests (mocked) ──────────────────────────────────────────────────


@pytest.mark.unit
class TestLdapAuth:
    def test_ldap_disabled_raises(self):
        from ragrig.auth_ldap import LdapAuthError, authenticate_ldap
        from ragrig.config import Settings

        settings = Settings(ragrig_ldap_enabled=False)
        with pytest.raises(LdapAuthError, match="not enabled"):
            authenticate_ldap("user@corp.com", "pass", settings)

    def test_empty_password_raises(self):
        from ragrig.auth_ldap import LdapAuthError, authenticate_ldap
        from ragrig.config import Settings

        settings = Settings(ragrig_ldap_enabled=True)
        with pytest.raises(LdapAuthError, match="empty"):
            authenticate_ldap("user@corp.com", "", settings)

    @patch("ragrig.auth_ldap.ldap3")
    def test_user_not_found_raises(self, mock_ldap):
        from ragrig.auth_ldap import LdapAuthError, authenticate_ldap
        from ragrig.config import Settings

        mock_conn = MagicMock()
        mock_conn.bound = True
        mock_conn.entries = []
        mock_ldap.Connection.return_value = mock_conn
        mock_ldap.AUTO_BIND_NONE = None
        mock_ldap.NONE = None
        mock_ldap.Server.return_value = MagicMock()
        mock_ldap.utils.conv.escape_filter_chars.return_value = "user@corp.com"

        settings = Settings(
            ragrig_ldap_enabled=True,
            ragrig_ldap_use_tls=False,
            ragrig_ldap_url="ldap://localhost:389",
        )
        with pytest.raises(LdapAuthError, match="not found"):
            authenticate_ldap("user@corp.com", "pass", settings)


# ── OIDC unit tests ───────────────────────────────────────────────────────────


@pytest.mark.unit
class TestOidcAuth:
    def test_oidc_disabled_raises_on_authorize(self):
        from ragrig.auth_oidc import OidcAuthError, build_authorization_url
        from ragrig.config import Settings

        settings = Settings(ragrig_oidc_enabled=False)
        with pytest.raises(OidcAuthError, match="not enabled"):
            build_authorization_url(settings, "state123")

    def test_oidc_disabled_raises_on_exchange(self):
        from ragrig.auth_oidc import OidcAuthError, exchange_code
        from ragrig.config import Settings

        settings = Settings(ragrig_oidc_enabled=False)
        with pytest.raises(OidcAuthError, match="not enabled"):
            exchange_code(settings, "some_code")

    def test_authorize_url_contains_client_id(self):
        from unittest.mock import patch

        from ragrig.auth_oidc import build_authorization_url
        from ragrig.config import Settings

        settings = Settings(
            ragrig_oidc_enabled=True,
            ragrig_oidc_client_id="my-client-id",
            ragrig_oidc_issuer="https://idp.example.com",
        )
        discovery_doc = {
            "authorization_endpoint": "https://idp.example.com/authorize",
            "token_endpoint": "https://idp.example.com/token",
            "jwks_uri": "https://idp.example.com/keys",
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = discovery_doc
        mock_resp.raise_for_status.return_value = None

        with patch("ragrig.auth_oidc.httpx.get", return_value=mock_resp):
            url = build_authorization_url(settings, "mystate")

        assert "my-client-id" in url
        assert "mystate" in url
