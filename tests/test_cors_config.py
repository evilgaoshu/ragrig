from __future__ import annotations

import pytest
from conftest import _create_session
from fastapi.testclient import TestClient

from ragrig.config import Settings
from ragrig.main import create_app

pytestmark = pytest.mark.unit


def test_cors_allows_configured_origin() -> None:
    app = create_app(
        check_database=lambda: None,
        session_factory=_create_session,
        settings=Settings(
            ragrig_cors_origins="https://console.example.com",
            ragrig_cors_allow_credentials=True,
        ),
    )
    client = TestClient(app)

    response = client.options(
        "/health",
        headers={
            "Origin": "https://console.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://console.example.com"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_cors_does_not_allow_unconfigured_origin() -> None:
    app = create_app(
        check_database=lambda: None,
        session_factory=_create_session,
        settings=Settings(ragrig_cors_origins="https://console.example.com"),
    )
    client = TestClient(app)

    response = client.options(
        "/health",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
