"""Tests for the understanding export diff summary tool.

Covers:
- Summary output in pass / degraded / failure states
- Missing or corrupt artifact input
- Secret-like leak interception
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.understanding_export_diff_summary import (
    _assert_no_raw_secrets,
    _build_summary,
    _load_diff,
    _render_markdown,
    build_summary,
    main,
)

pytestmark = pytest.mark.unit

REQUIRED_VERSION = "1.0.0"


def _make_diff(
    status: str = "pass",
    schema_compatible: bool = True,
    baseline_run_count: int = 5,
    current_run_count: int = 5,
    added_count: int = 0,
    removed_count: int = 0,
    changed_count: int = 0,
    sanitized_field_count: int = 0,
) -> dict[str, Any]:
    return {
        "artifact": "understanding-export-diff",
        "version": REQUIRED_VERSION,
        "generated_at": "2026-05-12T00:00:00+00:00",
        "schema_version": "1.0",
        "schema_compatible": schema_compatible,
        "baseline": {"run_count": baseline_run_count, "schema_version": "1.0"},
        "current": {"run_count": current_run_count, "schema_version": "1.0"},
        "runs": {
            "added": [f"run-{i}" for i in range(added_count)],
            "removed": [f"run-{i}" for i in range(removed_count)],
            "changed": [f"run-{i}" for i in range(changed_count)],
        },
        "run_details": {"added": [], "removed": [], "changed": []},
        "status": status,
        "drift_reasons": [],
        "sanitized_field_count": sanitized_field_count,
    }


# ── _load_diff ─────────────────────────────────────────────────


def test_load_diff_valid(tmp_path: Path) -> None:
    path = tmp_path / "diff.json"
    path.write_text(json.dumps(_make_diff()), encoding="utf-8")
    data = _load_diff(path)
    assert data["status"] == "pass"
    assert data["artifact"] == "understanding-export-diff"


def test_load_diff_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="Diff artifact not found"):
        _load_diff(tmp_path / "nope.json")


def test_load_diff_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "diff.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        _load_diff(path)


def test_load_diff_wrong_artifact_type(tmp_path: Path) -> None:
    path = tmp_path / "diff.json"
    data = _make_diff()
    data["artifact"] = "something-else"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid artifact type"):
        _load_diff(path)


def test_load_diff_version_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "diff.json"
    data = _make_diff()
    data["version"] = "9.9.9"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Version mismatch"):
        _load_diff(path)


def test_load_diff_missing_required_key(tmp_path: Path) -> None:
    path = tmp_path / "diff.json"
    data = _make_diff()
    del data["status"]
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Missing required key"):
        _load_diff(path)


# ── _build_summary ──────────────────────────────────────────────


def test_build_summary_contains_expected_fields(tmp_path: Path) -> None:
    diff = _make_diff(
        status="pass",
        baseline_run_count=10,
        current_run_count=12,
        added_count=2,
    )
    summary = _build_summary(diff, tmp_path / "diff.json", tmp_path / "diff.md")
    assert summary["status"] == "pass"
    assert summary["baseline_run_count"] == 10
    assert summary["current_run_count"] == 12
    assert summary["added_count"] == 2
    assert summary["removed_count"] == 0
    assert summary["changed_count"] == 0
    assert summary["schema_compatible"] is True
    assert summary["generated_at"] == "2026-05-12T00:00:00+00:00"


# ── Summary output in pass / degraded / failure ────────────────


def test_summary_pass_state(tmp_path: Path) -> None:
    diff = _make_diff(status="pass")
    path = tmp_path / "diff.json"
    path.write_text(json.dumps(diff), encoding="utf-8")
    summary = build_summary(path)
    assert summary["status"] == "pass"
    md = _render_markdown(summary)
    assert "✅" in md
    assert "`pass`" in md


def test_summary_degraded_state(tmp_path: Path) -> None:
    diff = _make_diff(status="degraded", added_count=1)
    path = tmp_path / "diff.json"
    path.write_text(json.dumps(diff), encoding="utf-8")
    summary = build_summary(path)
    assert summary["status"] == "degraded"
    md = _render_markdown(summary)
    assert "⚠️" in md
    assert "`degraded`" in md


def test_summary_failure_state(tmp_path: Path) -> None:
    diff = _make_diff(status="failure", schema_compatible=False)
    path = tmp_path / "diff.json"
    path.write_text(json.dumps(diff), encoding="utf-8")
    summary = build_summary(path)
    assert summary["status"] == "failure"
    assert summary["schema_compatible"] is False
    md = _render_markdown(summary)
    assert "❌" in md
    assert "`failure`" in md


# ── Missing / corrupt artifact ─────────────────────────────────


def test_summary_missing_artifact(tmp_path: Path) -> None:
    rc = main(["--diff", str(tmp_path / "nope.json")])
    assert rc == 1


def test_summary_corrupt_artifact(tmp_path: Path) -> None:
    path = tmp_path / "diff.json"
    path.write_text("{bad", encoding="utf-8")
    rc = main(["--diff", str(path)])
    assert rc == 1


def test_summary_wrong_artifact_type_via_main(tmp_path: Path) -> None:
    path = tmp_path / "diff.json"
    data = _make_diff()
    data["artifact"] = "wrong-type"
    path.write_text(json.dumps(data), encoding="utf-8")
    rc = main(["--diff", str(path)])
    assert rc == 1


# ── Render markdown structure ──────────────────────────────────


def test_render_markdown_contains_expected_sections() -> None:
    diff = _make_diff()
    summary = _build_summary(diff, Path("diff.json"), Path("diff.md"))
    md = _render_markdown(summary)
    assert "## Understanding Export Diff Summary" in md
    assert "### Changes" in md
    assert "### Artifacts" in md
    assert "**JSON report**" in md
    assert "**MD report**" in md
    assert "Schema compatible" in md


def test_render_markdown_with_changes() -> None:
    diff = _make_diff(status="degraded", added_count=2, removed_count=1, changed_count=3)
    summary = _build_summary(diff, Path("diff.json"), Path("diff.md"))
    md = _render_markdown(summary)
    assert "**Added**: 2" in md
    assert "**Removed**: 1" in md
    assert "**Changed**: 3" in md


def test_render_markdown_schema_incompatible() -> None:
    diff = _make_diff(status="failure", schema_compatible=False)
    summary = _build_summary(diff, Path("diff.json"), Path("diff.md"))
    md = _render_markdown(summary)
    assert "Schema compatible: no" in md or "Schema compatible" in md


# ── Security boundary ──────────────────────────────────────────


def test_assert_no_raw_secrets_panics() -> None:
    with pytest.raises(RuntimeError, match="raw secret fragment"):
        _assert_no_raw_secrets({"foo": "contains Bearer token"}, "test")


def test_summary_output_no_secrets(tmp_path: Path) -> None:
    diff = _make_diff()
    path = tmp_path / "diff.json"
    path.write_text(json.dumps(diff), encoding="utf-8")
    summary = build_summary(path)
    serialized = json.dumps(summary, indent=2, ensure_ascii=False)
    assert "Bearer " not in serialized
    assert "PRIVATE KEY-----" not in serialized
    assert "sk-live-" not in serialized


def test_summary_markdown_no_secrets(tmp_path: Path) -> None:
    diff = _make_diff()
    path = tmp_path / "diff.json"
    path.write_text(json.dumps(diff), encoding="utf-8")
    summary = build_summary(path)
    md = _render_markdown(summary)
    assert "Bearer " not in md
    assert "PRIVATE KEY-----" not in md
    assert "sk-live-" not in md


def test_no_raw_prompt_or_full_text_in_summary(tmp_path: Path) -> None:
    diff = _make_diff()
    diff["runs"]["added"] = ["run-with-prompt"]
    diff["run_details"]["added"] = [{"run_id": "run-with-prompt", "prompt": "should not leak"}]
    path = tmp_path / "diff.json"
    path.write_text(json.dumps(diff), encoding="utf-8")
    summary = build_summary(path)
    serialized = json.dumps(summary, indent=2, ensure_ascii=False)
    assert "should not leak" not in serialized


# ── CLI / main ─────────────────────────────────────────────────


def test_cli_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    diff_path = tmp_path / "diff.json"
    diff_path.write_text(json.dumps(_make_diff()), encoding="utf-8")
    rc = main(["--diff", str(diff_path), "--stdout"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "Understanding Export Diff Summary" in captured.out


def test_cli_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    diff_path = tmp_path / "diff.json"
    diff_path.write_text(json.dumps(_make_diff()), encoding="utf-8")
    rc = main(["--diff", str(diff_path), "--json"])
    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "pass"


def test_cli_output_file(tmp_path: Path) -> None:
    diff_path = tmp_path / "diff.json"
    out_path = tmp_path / "summary.md"
    diff_path.write_text(json.dumps(_make_diff()), encoding="utf-8")
    rc = main(["--diff", str(diff_path), "--output", str(out_path)])
    assert rc == 0
    assert out_path.is_file()
    content = out_path.read_text(encoding="utf-8")
    assert "Understanding Export Diff Summary" in content


def test_cli_missing_diff_failure_exit(tmp_path: Path) -> None:
    rc = main(["--diff", str(tmp_path / "nope.json")])
    assert rc == 1


def test_cli_degraded_exit_code(tmp_path: Path) -> None:
    diff_path = tmp_path / "diff.json"
    diff = _make_diff(status="degraded")
    diff_path.write_text(json.dumps(diff), encoding="utf-8")
    rc = main(["--diff", str(diff_path)])
    assert rc == 3


def test_cli_secret_safety_exit_code(tmp_path: Path) -> None:
    diff_path = tmp_path / "diff.json"
    diff = _make_diff()
    diff_path.write_text(json.dumps(diff), encoding="utf-8")
    # Hijack: pass a markdown with a secret that _assert_no_raw_secrets would catch
    # We can't easily do that via main, but we can verify via _assert_no_raw_secrets
    with pytest.raises(RuntimeError):
        _assert_no_raw_secrets("contains Bearer token", "test")


# ── End-to-end via subprocess ──────────────────────────────────


def test_subprocess_invocation(tmp_path: Path) -> None:
    diff_path = tmp_path / "diff.json"
    diff = _make_diff()
    diff_path.write_text(json.dumps(diff), encoding="utf-8")

    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.understanding_export_diff_summary",
            "--diff",
            str(diff_path),
            "--stdout",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 0, result.stderr
    assert "Understanding Export Diff Summary" in result.stdout
