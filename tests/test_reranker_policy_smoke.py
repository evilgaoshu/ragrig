from __future__ import annotations

import json

import pytest

from scripts.reranker_policy_smoke import _redact, main, run_smoke

pytestmark = pytest.mark.unit


def test_reranker_policy_smoke_covers_required_policy_cases() -> None:
    result = run_smoke()

    assert result["status"] == "pass"
    checks = {check["name"]: check for check in result["checks"]}

    production = checks["production_fake_reranker_blocked"]
    assert production["observed"]["status"] == "blocked"
    assert production["observed"]["fake_reranker_allowed"] is False
    assert production["observed"]["policy"] == "production_requires_real_reranker"

    local = checks["local_fake_reranker_allowed"]
    assert local["observed"]["status"] == "development_fallback_allowed"
    assert local["observed"]["fake_reranker_allowed"] is True

    test_override = checks["test_explicit_fake_reranker_allowed"]
    assert test_override["observed"]["status"] == "override_allowed"
    assert test_override["observed"]["fake_reranker_allowed"] is True


def test_real_reranker_contract_probe_is_not_degraded() -> None:
    result = run_smoke()
    checks = {check["name"]: check for check in result["checks"]}

    real_probe = checks["real_reranker_available_contract"]
    assert real_probe["status"] == "pass"
    assert real_probe["provider"] == "reranker.bge"
    assert real_probe["degraded"] is False
    assert real_probe["details"]["top_index"] == 1


def test_reranker_policy_smoke_redacts_secret_like_keys() -> None:
    result = _redact(
        {
            "api_key": "sk-example",
            "nested": {"password": "example", "safe": "visible"},
            "items": [{"session_token": "example"}],
        }
    )

    assert result == {
        "api_key": "[redacted]",
        "nested": {"password": "[redacted]", "safe": "visible"},
        "items": [{"session_token": "[redacted]"}],
    }


def test_reranker_policy_smoke_cli_writes_output(tmp_path, capsys) -> None:
    output_path = tmp_path / "reranker-policy-smoke.json"

    exit_code = main(["--pretty", "--output", str(output_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out)["status"] == "pass"
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "pass"
