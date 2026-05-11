"""Tests for the sanitizer drift history summary tool.

Covers:
- summary generation from valid history
- no-history (missing file)
- corrupt history (bad JSON)
- schema incompatible (wrong artifact type or version)
- secret-like leak interception
- CLI argument handling and exit codes
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.sanitizer_drift_history_summary import (
    _assert_no_raw_secrets,
    _build_summary,
    _load_history,
    _render_markdown,
    build_summary,
    main,
)

pytestmark = pytest.mark.unit


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_history(
    status: str = "success",
    risk: str = "unchanged",
    base_hash: str = "abc123",
    head_hash: str = "def456",
    changed_parser_count: int = 0,
    degraded_reports: list[dict[str, Any]] | None = None,
    valid_report_count: int = 1,
    total_report_count: int = 1,
) -> dict[str, Any]:
    return {
        "artifact": "sanitizer-drift-history",
        "version": "1.0.0",
        "schema_version": "1.0.0",
        "generated_at": "2026-05-11T00:00:00+00:00",
        "status": status,
        "reports_dir": "docs/operations/artifacts",
        "trends": {
            "available": True,
            "report_count": total_report_count,
            "valid_report_count": valid_report_count,
            "parser_trend": [],
            "redaction_trend": [],
            "degraded_trend": [],
            "risk_trend": [],
        },
        "latest": {
            "risk": risk,
            "base_golden_hash": base_hash,
            "head_golden_hash": head_hash,
            "changed_parser_count": changed_parser_count,
            "added_parser_count": 0,
            "removed_parser_count": 0,
            "generated_at": "2026-05-11T00:00:00+00:00",
            "head_redacted": 10,
            "head_degraded": 0,
        },
        "degraded_reports": degraded_reports or [],
    }


# ── _load_history ────────────────────────────────────────────────────────────


def test_load_history_valid(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text(json.dumps(_make_history()), encoding="utf-8")
    loaded = _load_history(path)
    assert loaded["artifact"] == "sanitizer-drift-history"
    assert loaded["status"] == "success"


def test_load_history_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _load_history(tmp_path / "nope.json")


def test_load_history_invalid_artifact(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"artifact": "wrong"}), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid artifact type"):
        _load_history(path)


def test_load_history_schema_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    history = _make_history()
    history["schema_version"] = "2.0.0"
    path.write_text(json.dumps(history), encoding="utf-8")
    with pytest.raises(ValueError, match="Schema version mismatch"):
        _load_history(path)


def test_load_history_missing_key(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text(
        json.dumps(
            {
                "artifact": "sanitizer-drift-history",
                "version": "1.0.0",
                "schema_version": "1.0.0",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Missing required key"):
        _load_history(path)


def test_load_history_corrupt_json(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        _load_history(path)


# ── _build_summary ───────────────────────────────────────────────────────────


def test_build_summary_basic(tmp_path: Path) -> None:
    history = _make_history(
        status="success",
        risk="unchanged",
        base_hash="abc123",
        head_hash="def456",
        changed_parser_count=2,
        degraded_reports=[{"source_path": "bad.json", "reason": "corrupt"}],
    )
    summary = _build_summary(history, tmp_path / "history.json")
    assert summary["status"] == "success"
    assert summary["latest_risk"] == "unchanged"
    assert summary["base_golden_hash"] == "abc123"
    assert summary["head_golden_hash"] == "def456"
    assert summary["changed_parser_count"] == 2
    assert summary["degraded_reports_count"] == 1


def test_build_summary_no_latest(tmp_path: Path) -> None:
    history = _make_history()
    history["latest"] = None
    summary = _build_summary(history, tmp_path / "history.json")
    assert summary["latest_risk"] == "unknown"
    assert summary["changed_parser_count"] == 0


# ── _render_markdown ─────────────────────────────────────────────────────────


def test_render_markdown_contains_expected_fields() -> None:
    summary = {
        "status": "degraded",
        "latest_risk": "degraded",
        "base_golden_hash": "abc123",
        "head_golden_hash": "def456",
        "changed_parser_count": 3,
        "degraded_reports_count": 2,
        "report_path": "docs/operations/artifacts/history.json",
        "valid_report_count": 5,
        "total_report_count": 7,
        "generated_at": "2026-05-11T00:00:00+00:00",
    }
    md = _render_markdown(summary)
    assert "## Sanitizer Drift History Summary" in md
    assert "`degraded`" in md
    assert "`abc123`" in md
    assert "`def456`" in md
    assert "**Changed parsers**: 3" in md
    assert "**Degraded reports**: 2" in md
    assert "docs/operations/artifacts/history.json" in md


def test_render_markdown_no_hashes() -> None:
    summary = {
        "status": "no_history",
        "latest_risk": "unknown",
        "base_golden_hash": "",
        "head_golden_hash": "",
        "changed_parser_count": 0,
        "degraded_reports_count": 0,
        "report_path": "docs/operations/artifacts/history.json",
        "valid_report_count": 0,
        "total_report_count": 0,
        "generated_at": "",
    }
    md = _render_markdown(summary)
    assert "## Sanitizer Drift History Summary" in md
    assert "`no_history`" in md


# ── build_summary ────────────────────────────────────────────────────────────


def test_build_summary_integration(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text(json.dumps(_make_history()), encoding="utf-8")
    summary = build_summary(path)
    assert summary["status"] == "success"
    assert summary["latest_risk"] == "unchanged"


# ── Security boundary ─────────────────────────────────────────────────────────


def test_assert_no_raw_secrets_panics() -> None:
    with pytest.raises(RuntimeError, match="raw secret fragment"):
        _assert_no_raw_secrets({"foo": "contains Bearer token"}, "test")


def test_build_summary_no_secrets_in_output(tmp_path: Path) -> None:
    history = _make_history()
    history["degraded_reports"] = [
        {"source_path": "bad.json", "reason": "Auth failed with sk-live-12345"}
    ]
    path = tmp_path / "history.json"
    path.write_text(json.dumps(history), encoding="utf-8")
    summary = build_summary(path)
    serialized = json.dumps(summary, indent=2, ensure_ascii=False)
    # The secret from input must not propagate to summary output
    assert "sk-live-12345" not in serialized


def test_render_markdown_no_secrets() -> None:
    summary = {
        "status": "success",
        "latest_risk": "unchanged",
        "base_golden_hash": "abc",
        "head_golden_hash": "def",
        "changed_parser_count": 0,
        "degraded_reports_count": 0,
        "report_path": "docs/artifacts/history.json",
        "valid_report_count": 1,
        "total_report_count": 1,
        "generated_at": "2026-05-11T00:00:00+00:00",
    }
    md = _render_markdown(summary)
    assert "Bearer " not in md
    assert "PRIVATE KEY-----" not in md
    assert "sk-live-" not in md


# ── CLI / main ───────────────────────────────────────────────────────────────


def test_cli_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "history.json"
    path.write_text(json.dumps(_make_history()), encoding="utf-8")
    rc = main(["--history", str(path), "--stdout"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Sanitizer Drift History Summary" in captured.out


def test_cli_degraded(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "history.json"
    path.write_text(
        json.dumps(_make_history(status="degraded", risk="degraded")),
        encoding="utf-8",
    )
    rc = main(["--history", str(path), "--stdout"])
    assert rc == 3
    captured = capsys.readouterr()
    assert "degraded" in captured.out


def test_cli_missing_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--history", str(tmp_path / "nope.json"), "--stdout"])
    assert rc == 1
    captured = capsys.readouterr()
    assert "failure" in captured.out or "not found" in captured.out.lower()


def test_cli_corrupt_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "history.json"
    path.write_text("not json", encoding="utf-8")
    rc = main(["--history", str(path), "--stdout"])
    assert rc == 1


def test_cli_invalid_schema(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "history.json"
    path.write_text(json.dumps({"artifact": "wrong"}), encoding="utf-8")
    rc = main(["--history", str(path), "--stdout"])
    assert rc == 1


def test_cli_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "history.json"
    path.write_text(json.dumps(_make_history()), encoding="utf-8")
    rc = main(["--history", str(path), "--json"])
    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "success"


def test_cli_output_file(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text(json.dumps(_make_history()), encoding="utf-8")
    out_path = tmp_path / "summary.md"
    rc = main(["--history", str(path), "--output", str(out_path)])
    assert rc == 0
    assert out_path.is_file()
    assert "Sanitizer Drift History Summary" in out_path.read_text(encoding="utf-8")


def test_cli_secret_in_input_safety_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    history = _make_history()
    history["degraded_reports"] = [{"source_path": "bad.json", "reason": "leaked sk-live-12345"}]
    path = tmp_path / "history.json"
    path.write_text(json.dumps(history), encoding="utf-8")
    rc = main(["--history", str(path), "--stdout"])
    # The summary generation filters degraded_reports, so this should succeed
    assert rc == 0
    captured = capsys.readouterr()
    assert "sk-live-12345" not in captured.out


# ── End-to-end via subprocess ────────────────────────────────────────────────


def test_subprocess_invocation(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    path.write_text(json.dumps(_make_history()), encoding="utf-8")
    out_path = tmp_path / "summary.md"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.sanitizer_drift_history_summary",
            "--history",
            str(path),
            "--output",
            str(out_path),
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 0, result.stderr
    assert out_path.is_file()
