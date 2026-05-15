from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_local_pilot_preflight_passes_without_model_configuration(tmp_path, monkeypatch) -> None:
    from scripts.local_pilot_preflight import run_preflight

    for name in (
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "GEMINI_API_KEY",
        "RAGRIG_ANSWER_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)

    result = run_preflight(mode="local", artifacts_dir=tmp_path)

    assert result["status"] == "pass"
    required = {check["name"]: check for check in result["required_checks"]}
    assert required["app_import"]["status"] == "pass"
    assert required["ephemeral_sqlite_health"]["status"] == "pass"
    assert required["artifact_directory_writable"]["status"] == "pass"
    optional = {check["name"]: check for check in result["optional_checks"]}
    assert optional["answer_model_configuration"]["status"] == "skip"
    assert "does not block startup" in optional["answer_model_configuration"]["detail"]


def test_local_pilot_preflight_fails_only_required_checks(tmp_path) -> None:
    from scripts.local_pilot_preflight import run_preflight

    blocked_artifact_path = tmp_path / "not-a-directory"
    blocked_artifact_path.write_text("occupied", encoding="utf-8")

    result = run_preflight(mode="local", artifacts_dir=blocked_artifact_path)

    assert result["status"] == "fail"
    failed = [check for check in result["required_checks"] if check["status"] == "fail"]
    assert [check["name"] for check in failed] == ["artifact_directory_writable"]
    assert all(check["status"] in {"pass", "skip"} for check in result["optional_checks"])


def test_local_pilot_preflight_rejects_unknown_mode(tmp_path) -> None:
    from scripts.local_pilot_preflight import run_preflight

    with pytest.raises(ValueError, match="mode must be"):
        run_preflight(mode="cloud", artifacts_dir=tmp_path)


def test_makefile_exposes_minimal_preflight_targets() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert "local-pilot-preflight:" in makefile
    assert "pilot-docker-preflight:" in makefile
    assert "scripts.local_pilot_preflight" in makefile
