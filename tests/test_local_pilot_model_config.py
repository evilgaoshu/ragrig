from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ragrig.main import create_app
from tests.test_web_console import _create_file_session_factory


def test_local_pilot_model_health_accepts_deterministic_provider(tmp_path) -> None:
    session_factory = _create_file_session_factory(tmp_path / "pilot-model-health.db")
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    client = TestClient(app)

    response = client.post(
        "/local-pilot/model-health",
        json={"provider": "deterministic-local", "model": "hash-8d", "config": {}},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "deterministic-local"
    assert body["status"] == "healthy"
    assert body["model"] == "hash-8d"
    assert body["secret_policy"] == "env_refs_only"


def test_local_pilot_model_health_rejects_raw_secret(tmp_path) -> None:
    session_factory = _create_file_session_factory(tmp_path / "pilot-model-raw-secret.db")
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    client = TestClient(app)

    response = client.post(
        "/local-pilot/model-health",
        json={
            "provider": "model.openai",
            "model": "gpt-4.1-mini",
            "config": {"api_key": "sk-raw-secret-value"},
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "secret_reference_required"
    assert "sk-raw-secret-value" not in response.text


def test_local_pilot_model_health_reports_missing_env_secret(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAGRIG_TEST_OPENAI_KEY", raising=False)
    session_factory = _create_file_session_factory(tmp_path / "pilot-model-missing-env.db")
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    client = TestClient(app)

    response = client.post(
        "/local-pilot/model-health",
        json={
            "provider": "model.openai",
            "model": "gpt-4.1-mini",
            "config": {"api_key": "env:RAGRIG_TEST_OPENAI_KEY"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "missing_credentials"
    assert body["missing_credentials"] == ["RAGRIG_TEST_OPENAI_KEY"]
    assert "RAGRIG_TEST_OPENAI_KEY" in body["detail"]


def test_local_pilot_answer_smoke_accepts_env_config_without_leaking_value(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAGRIG_TEST_OPENAI_KEY", "secret-test-value")
    session_factory = _create_file_session_factory(tmp_path / "pilot-answer-config.db")
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    client = TestClient(app)

    response = client.post(
        "/local-pilot/answer-smoke",
        json={
            "provider": "model.openai",
            "model": "gpt-4.1-mini",
            "config": {
                "api_key": "env:RAGRIG_TEST_OPENAI_KEY",
                "base_url": "http://127.0.0.1:9/v1",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "model.openai"
    assert body["model"] == "gpt-4.1-mini"
    assert body["status"] in {"unavailable", "degraded"}
    assert body["secret_policy"] == "env_refs_only"
    assert "secret-test-value" not in response.text
