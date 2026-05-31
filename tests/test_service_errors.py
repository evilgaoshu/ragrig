from __future__ import annotations

import uuid

import pytest
from conftest import _create_session
from fastapi.testclient import TestClient

from ragrig.config import Settings
from ragrig.main import create_app

pytestmark = pytest.mark.unit


def test_service_error_handler_converts_service_exceptions_to_json_response() -> None:
    app = create_app(
        check_database=lambda: None,
        session_factory=_create_session,
        settings=Settings(ragrig_auth_enabled=False),
    )
    client = TestClient(app)

    response = client.get(f"/understanding-runs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json() == {"error": "understanding_run_not_found"}
