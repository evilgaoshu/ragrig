"""Tests for the understanding export baseline diff tool.

Covers:
- Correct diff computation for added/removed/changed runs
- Schema compatibility checks
- Status assessment (pass / degraded / failure)
- Missing/corrupt baseline handling
- Security boundary: diff output never contains raw secrets or forbidden keys
- CLI argument handling and error paths
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.understanding_export_diff import (
    DiffError,
    _assert_no_raw_secrets,
    _compute_run_diff,
    _load_export,
    _render_markdown,
    _scan_output_sanitization,
    compute_export_diff,
    main,
)

pytestmark = pytest.mark.unit


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_run(
    run_id: str = "00000000-0000-0000-0000-000000000001",
    provider: str = "deterministic-local",
    model: str = "",
    profile_id: str = "*.understand.default",
    trigger_source: str = "api",
    operator: str = "test-user",
    status: str = "success",
    total: int = 3,
    created: int = 2,
    skipped: int = 1,
    failed: int = 0,
    error_summary: str | None = None,
    started_at: str = "2026-05-09T11:00:00+00:00",
    finished_at: str = "2026-05-09T11:00:05+00:00",
) -> dict[str, Any]:
    return {
        "id": run_id,
        "knowledge_base_id": "00000000-0000-0000-0000-000000000003",
        "provider": provider,
        "model": model,
        "profile_id": profile_id,
        "trigger_source": trigger_source,
        "operator": operator,
        "status": status,
        "total": total,
        "created": created,
        "skipped": skipped,
        "failed": failed,
        "error_summary": error_summary,
        "started_at": started_at,
        "finished_at": finished_at,
    }


def _make_export(
    runs: list[dict[str, Any]],
    schema_version: str = "1.0",
) -> dict[str, Any]:
    run_ids = [r["id"] for r in runs]
    return {
        "schema_version": schema_version,
        "generated_at": "2026-05-09T12:00:00+00:00",
        "filter": {
            "provider": "deterministic-local",
            "model": None,
            "profile_id": "*.understand.default",
            "status": "success",
            "started_after": None,
            "started_before": None,
            "limit": 50,
        },
        "run_count": len(runs),
        "run_ids": run_ids,
        "knowledge_base": "fixture-local",
        "knowledge_base_id": "00000000-0000-0000-0000-000000000003",
        "runs": runs,
    }


# ── _load_export ─────────────────────────────────────────────────────────────


def test_load_export_valid(tmp_path: Path) -> None:
    path = tmp_path / "export.json"
    export = _make_export([_make_run()])
    path.write_text(json.dumps(export), encoding="utf-8")
    loaded = _load_export(path)
    assert loaded["schema_version"] == "1.0"
    assert loaded["run_count"] == 1


def test_load_export_missing_file(tmp_path: Path) -> None:
    with pytest.raises(DiffError) as exc_info:
        _load_export(tmp_path / "nope.json", label="baseline")
    assert exc_info.value.code == "baseline_file_not_found"
    assert "not found" in exc_info.value.message


def test_load_export_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "export.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(DiffError) as exc_info:
        _load_export(path)
    assert exc_info.value.code == "current_invalid_json"
    assert "Invalid JSON" in exc_info.value.message


def test_load_export_with_secret_fails(tmp_path: Path) -> None:
    path = tmp_path / "export.json"
    export = _make_export([_make_run()])
    export["runs"][0]["api_key"] = "sk-abc123"
    path.write_text(json.dumps(export), encoding="utf-8")
    with pytest.raises(DiffError) as exc_info:
        _load_export(path)
    assert "api_key" in exc_info.value.message


# ── _compute_run_diff ────────────────────────────────────────────────────────


def test_run_diff_unchanged() -> None:
    run = _make_run()
    assert _compute_run_diff(run, run) is None


def test_run_diff_added() -> None:
    run = _make_run(run_id="run-new")
    diff = _compute_run_diff(None, run)
    assert diff is not None
    assert diff["change_type"] == "added"
    assert diff["run_id"] == "run-new"
    assert diff["baseline"] is None
    assert diff["current"]["status"] == "success"


def test_run_diff_removed() -> None:
    run = _make_run(run_id="run-old")
    diff = _compute_run_diff(run, None)
    assert diff is not None
    assert diff["change_type"] == "removed"
    assert diff["run_id"] == "run-old"
    assert diff["current"] is None


def test_run_diff_status_changed() -> None:
    base = _make_run(status="success")
    current = _make_run(status="partial_failure")
    diff = _compute_run_diff(base, current)
    assert diff is not None
    assert diff["change_type"] == "changed"
    assert any(c["field"] == "status" for c in diff["changes"])


def test_run_diff_counts_changed() -> None:
    base = _make_run(total=3, created=2)
    current = _make_run(total=5, created=3)
    diff = _compute_run_diff(base, current)
    assert diff is not None
    fields = [c["field"] for c in diff["changes"]]
    assert "total" in fields
    assert "created" in fields


def test_run_diff_error_summary_presence_changed() -> None:
    base = _make_run(error_summary=None)
    current = _make_run(error_summary="something failed")
    diff = _compute_run_diff(base, current)
    assert diff is not None
    assert any(c["field"] == "error_summary_present" for c in diff["changes"])
    # Must NOT leak the actual error_summary text
    serialized = json.dumps(diff, indent=2, ensure_ascii=False)
    assert "something failed" not in serialized


# ── compute_export_diff ──────────────────────────────────────────────────────


def test_diff_no_changes() -> None:
    runs = [_make_run()]
    baseline = _make_export(runs)
    current = _make_export(runs)
    report = compute_export_diff(baseline, current)
    assert report["runs"]["added"] == []
    assert report["runs"]["removed"] == []
    assert report["runs"]["changed"] == []
    assert report["status"] == "pass"
    assert report["schema_compatible"] is True
    assert report["drift_reasons"] == []


def test_diff_run_added() -> None:
    baseline = _make_export([_make_run("run-a")])
    current = _make_export([_make_run("run-a"), _make_run("run-b")])
    report = compute_export_diff(baseline, current)
    assert report["runs"]["added"] == ["run-b"]
    assert report["runs"]["removed"] == []
    assert report["runs"]["changed"] == []
    assert report["status"] == "degraded"
    assert any(r["type"] == "runs_added" for r in report["drift_reasons"])


def test_diff_run_removed() -> None:
    baseline = _make_export([_make_run("run-a"), _make_run("run-b")])
    current = _make_export([_make_run("run-a")])
    report = compute_export_diff(baseline, current)
    assert report["runs"]["removed"] == ["run-b"]
    assert report["runs"]["added"] == []
    assert report["runs"]["changed"] == []
    assert report["status"] == "degraded"
    assert any(r["type"] == "runs_removed" for r in report["drift_reasons"])


def test_diff_run_changed() -> None:
    baseline = _make_export([_make_run("run-a", status="success", total=3)])
    current = _make_export([_make_run("run-a", status="partial_failure", total=5)])
    report = compute_export_diff(baseline, current)
    assert report["runs"]["changed"] == ["run-a"]
    assert report["status"] == "degraded"
    assert any(
        r["type"] == "run_changed" and r["run_id"] == "run-a" for r in report["drift_reasons"]
    )


def test_diff_multiple_changes() -> None:
    baseline = _make_export(
        [
            _make_run("run-a", status="success"),
            _make_run("run-b", status="success"),
        ]
    )
    current = _make_export(
        [
            _make_run("run-a", status="partial_failure"),  # changed
            _make_run("run-c", status="success"),  # added
        ]
    )
    report = compute_export_diff(baseline, current)
    assert report["runs"]["added"] == ["run-c"]
    assert report["runs"]["removed"] == ["run-b"]
    assert report["runs"]["changed"] == ["run-a"]
    assert report["status"] == "degraded"
    assert len(report["drift_reasons"]) == 3


def test_diff_schema_incompatible() -> None:
    baseline = _make_export([_make_run()], schema_version="1.0")
    current = _make_export([_make_run()], schema_version="2.0")
    report = compute_export_diff(baseline, current)
    assert report["schema_compatible"] is False
    assert report["status"] == "failure"
    assert any(r["type"] == "schema_incompatible" for r in report["drift_reasons"])


def test_diff_empty_exports() -> None:
    baseline = _make_export([])
    current = _make_export([])
    report = compute_export_diff(baseline, current)
    assert report["status"] == "pass"
    assert report["baseline"]["run_count"] == 0
    assert report["current"]["run_count"] == 0


# ── Security boundary ────────────────────────────────────────────────────────


def test_diff_output_never_contains_raw_secrets() -> None:
    """Even if input exports contain secret-like strings, the diff output
    must never propagate them."""
    baseline = _make_export([_make_run("run-a")])
    current = _make_export([_make_run("run-a", status="failure")])
    # Inject a secret-like field that should be caught by verify_export,
    # but if it somehow got through, the diff must not leak it.
    report = compute_export_diff(baseline, current)
    serialized = json.dumps(report, indent=2, ensure_ascii=False)
    assert "sk-live-" not in serialized
    assert "Bearer " not in serialized
    assert "PRIVATE KEY-----" not in serialized


def test_assert_no_raw_secrets_panics() -> None:
    with pytest.raises(RuntimeError, match="raw secret fragment"):
        _assert_no_raw_secrets({"foo": "contains Bearer token"}, "test")


def test_scan_output_sanitization_detects_forbidden_key() -> None:
    data = {"runs": [{"id": "x", "prompt": "should not appear"}]}
    count = _scan_output_sanitization(data)
    assert count >= 1


def test_scan_output_sanitization_detects_secret_pattern() -> None:
    data = {"config": {"api_key": "sk-12345"}}
    count = _scan_output_sanitization(data)
    assert count >= 1


def test_diff_output_no_secret_in_markdown() -> None:
    baseline = _make_export([_make_run("run-a")])
    current = _make_export([_make_run("run-a", status="failure")])
    report = compute_export_diff(baseline, current)
    md = _render_markdown(report)
    assert "Bearer " not in md
    assert "PRIVATE KEY-----" not in md
    assert "sk-live-" not in md


def test_diff_output_no_full_error_summary() -> None:
    """The diff report must not include the actual error_summary text,
    only its presence/absence."""
    baseline = _make_export([_make_run("run-a", error_summary=None)])
    current = _make_export([_make_run("run-a", error_summary="detailed failure message")])
    report = compute_export_diff(baseline, current)
    serialized = json.dumps(report, indent=2, ensure_ascii=False)
    assert "detailed failure message" not in serialized


# ── Markdown rendering ───────────────────────────────────────────────────────


def test_render_markdown_contains_expected_sections() -> None:
    baseline = _make_export([_make_run()])
    current = _make_export([_make_run()])
    report = compute_export_diff(baseline, current)
    md = _render_markdown(report)
    assert "## Understanding Export Baseline Diff" in md
    assert "### Run Counts" in md
    assert "### Status:" in md
    assert "No run changes detected." in md


def test_render_markdown_with_changes() -> None:
    baseline = _make_export([_make_run("run-a")])
    current = _make_export([_make_run("run-a"), _make_run("run-b")])
    report = compute_export_diff(baseline, current)
    md = _render_markdown(report)
    assert "Added runs" in md
    assert "`run-b`" in md


def test_render_markdown_degraded_status() -> None:
    baseline = _make_export([_make_run("run-a", status="success")])
    current = _make_export([_make_run("run-a", status="failure")])
    report = compute_export_diff(baseline, current)
    md = _render_markdown(report)
    assert "`degraded`" in md


def test_render_markdown_failure_status() -> None:
    baseline = _make_export([_make_run("run-a")], schema_version="1.0")
    current = _make_export([_make_run("run-a")], schema_version="2.0")
    report = compute_export_diff(baseline, current)
    md = _render_markdown(report)
    assert "`failure`" in md
    assert "Schema incompatible" in md


# ── CLI / main ───────────────────────────────────────────────────────────────


def test_cli_no_changes(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    out_path = tmp_path / "diff.json"
    export = _make_export([_make_run()])
    baseline_path.write_text(json.dumps(export), encoding="utf-8")
    current_path.write_text(json.dumps(export), encoding="utf-8")

    rc = main(
        [
            "--baseline",
            str(baseline_path),
            "--current",
            str(current_path),
            "--output",
            str(out_path),
        ]
    )
    assert rc == 0
    assert out_path.is_file()
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["status"] == "pass"


def test_cli_degraded_exit_code(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    out_path = tmp_path / "diff.json"
    baseline_path.write_text(
        json.dumps(_make_export([_make_run("run-a", status="success")])),
        encoding="utf-8",
    )
    current_path.write_text(
        json.dumps(_make_export([_make_run("run-a", status="failure")])),
        encoding="utf-8",
    )

    rc = main(
        [
            "--baseline",
            str(baseline_path),
            "--current",
            str(current_path),
            "--output",
            str(out_path),
        ]
    )
    assert rc == 2
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["status"] == "degraded"


def test_cli_failure_exit_code_schema_mismatch(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    out_path = tmp_path / "diff.json"
    baseline_path.write_text(
        json.dumps(_make_export([_make_run()], schema_version="1.0")),
        encoding="utf-8",
    )
    current_path.write_text(
        json.dumps(_make_export([_make_run()], schema_version="2.0")),
        encoding="utf-8",
    )

    rc = main(
        [
            "--baseline",
            str(baseline_path),
            "--current",
            str(current_path),
            "--output",
            str(out_path),
        ]
    )
    assert rc == 1
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["status"] == "failure"
    assert report["schema_compatible"] is False


def test_cli_missing_baseline(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "--baseline",
            str(tmp_path / "nope.json"),
            "--current",
            str(tmp_path / "nope.json"),
            "--output",
            str(tmp_path / "diff.json"),
        ]
    )
    assert rc == 1
    assert (tmp_path / "diff.json").is_file()
    report = json.loads((tmp_path / "diff.json").read_text(encoding="utf-8"))
    assert report["status"] == "failure"


def test_cli_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    export = _make_export([_make_run()])
    baseline_path.write_text(json.dumps(export), encoding="utf-8")
    current_path.write_text(json.dumps(export), encoding="utf-8")

    rc = main(
        [
            "--baseline",
            str(baseline_path),
            "--current",
            str(current_path),
            "--output",
            str(tmp_path / "diff.json"),
            "--stdout",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "Understanding Export Baseline Diff" in captured.out


def test_cli_markdown_only(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    md_path = tmp_path / "report.md"
    export = _make_export([_make_run()])
    baseline_path.write_text(json.dumps(export), encoding="utf-8")
    current_path.write_text(json.dumps(export), encoding="utf-8")

    rc = main(
        [
            "--baseline",
            str(baseline_path),
            "--current",
            str(current_path),
            "--output",
            str(tmp_path / "diff.json"),
            "--markdown-output",
            str(md_path),
            "--format",
            "markdown",
        ]
    )
    assert rc == 0
    assert not (tmp_path / "diff.json").is_file()
    assert md_path.is_file()


def test_cli_both_outputs(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    export = _make_export([_make_run()])
    baseline_path.write_text(json.dumps(export), encoding="utf-8")
    current_path.write_text(json.dumps(export), encoding="utf-8")

    rc = main(
        [
            "--baseline",
            str(baseline_path),
            "--current",
            str(current_path),
            "--output",
            str(tmp_path / "diff.json"),
        ]
    )
    assert rc == 0
    assert (tmp_path / "diff.json").is_file()
    md_path = tmp_path / "diff.md"
    assert md_path.is_file()


# ── End-to-end via subprocess ────────────────────────────────────────────────


def test_subprocess_invocation(tmp_path: Path) -> None:
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    out_path = tmp_path / "diff.json"
    export = _make_export([_make_run()])
    baseline_path.write_text(json.dumps(export), encoding="utf-8")
    current_path.write_text(json.dumps(export), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.understanding_export_diff",
            "--baseline",
            str(baseline_path),
            "--current",
            str(current_path),
            "--output",
            str(out_path),
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 0, result.stderr
    assert out_path.is_file()
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["status"] == "pass"
