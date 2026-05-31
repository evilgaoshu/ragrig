from __future__ import annotations

import uuid

import pytest
from conftest import _create_session
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from ragrig.config import Settings
from ragrig.main import create_app
from ragrig.services.middleware import configure_service_exception_handlers

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


def test_global_exception_handler_returns_safe_json_response() -> None:
    app = FastAPI()
    configure_service_exception_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("secret traceback detail")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom", headers={"x-request-id": "req-123"})

    assert response.status_code == 500
    assert response.headers["x-request-id"] == "req-123"
    assert response.json() == {
        "error": {
            "code": "internal_server_error",
            "message": "Internal server error",
        }
    }


def test_global_http_exception_handler_preserves_fastapi_detail_shape() -> None:
    app = FastAPI()
    configure_service_exception_handlers(app)

    @app.get("/http-error")
    def http_error() -> None:
        raise HTTPException(status_code=418, detail="teapot")

    client = TestClient(app)
    response = client.get("/http-error")

    assert response.status_code == 418
    assert response.json() == {"detail": "teapot"}
