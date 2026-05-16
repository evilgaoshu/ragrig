"""OIDC / OAuth2 authentication helpers.

Implements the authorization-code flow:
  1. build_authorization_url() → redirect the browser to the IdP.
  2. exchange_code() → exchange the code for tokens and validate the ID token.

Uses joserfc for JWT validation and httpx for token endpoint requests.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

from ragrig.config import Settings


@dataclass(frozen=True)
class OidcUserInfo:
    provider: str  # e.g. "oidc:google"
    uid: str  # subject claim
    email: str
    display_name: str


class OidcAuthError(Exception):
    """Raised when OIDC auth fails."""


def generate_state() -> str:
    return secrets.token_urlsafe(24)


def build_authorization_url(settings: Settings, state: str) -> str:
    """Return the IdP authorization URL to redirect the browser to."""
    if not settings.ragrig_oidc_enabled:
        raise OidcAuthError("OIDC authentication is not enabled")
    params = {
        "response_type": "code",
        "client_id": settings.ragrig_oidc_client_id,
        "redirect_uri": settings.ragrig_oidc_redirect_uri,
        "scope": settings.ragrig_oidc_scopes,
        "state": state,
    }
    auth_endpoint = _discover_endpoint(settings, "authorization_endpoint")
    return f"{auth_endpoint}?{urlencode(params)}"


def exchange_code(settings: Settings, code: str) -> OidcUserInfo:
    """Exchange authorization code for tokens, validate ID token, return user info."""
    if not settings.ragrig_oidc_enabled:
        raise OidcAuthError("OIDC authentication is not enabled")

    token_endpoint = _discover_endpoint(settings, "token_endpoint")
    jwks_uri = _discover_endpoint(settings, "jwks_uri")

    # Exchange code for tokens
    resp = httpx.post(
        token_endpoint,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.ragrig_oidc_redirect_uri,
            "client_id": settings.ragrig_oidc_client_id,
            "client_secret": settings.ragrig_oidc_client_secret,
        },
        timeout=10,
    )
    if resp.status_code != 200:
        raise OidcAuthError(f"token endpoint returned {resp.status_code}")
    token_data = resp.json()
    id_token = token_data.get("id_token")
    if not id_token:
        raise OidcAuthError("no id_token in token response")

    # Fetch JWKS and validate the ID token
    jwks_resp = httpx.get(jwks_uri, timeout=10)
    if jwks_resp.status_code != 200:
        raise OidcAuthError(f"jwks_uri returned {jwks_resp.status_code}")

    try:
        key_set = KeySet.import_key_set(jwks_resp.json())
        token = jwt.decode(id_token, key_set)
        token.validate()
        claims = token.claims
    except JoseError as exc:
        raise OidcAuthError(f"ID token validation failed: {exc}") from exc

    sub = claims.get("sub", "")
    email = claims.get("email", "")
    name = claims.get("name") or claims.get("given_name") or email.split("@")[0]
    provider_label = f"oidc:{settings.ragrig_oidc_provider_name}"

    if not sub or not email:
        raise OidcAuthError("ID token missing required claims (sub, email)")

    return OidcUserInfo(provider=provider_label, uid=sub, email=email, display_name=name)


def _discover_endpoint(settings: Settings, key: str) -> str:
    """Fetch the OIDC discovery document and return the requested endpoint."""
    issuer = settings.ragrig_oidc_issuer.rstrip("/")
    discovery_url = f"{issuer}/.well-known/openid-configuration"
    try:
        resp = httpx.get(discovery_url, timeout=10)
        resp.raise_for_status()
        doc = resp.json()
    except Exception as exc:
        raise OidcAuthError(f"OIDC discovery failed: {exc}") from exc
    endpoint = doc.get(key)
    if not endpoint:
        raise OidcAuthError(f"OIDC discovery document missing '{key}'")
    return endpoint
