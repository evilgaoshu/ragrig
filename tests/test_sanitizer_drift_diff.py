"""Tests for the sanitizer drift diff tool.

Covers:
- Correct diff computation for added/removed/changed parsers
- Risk assessment logic (degraded vs unchanged)
- golden_hash drift detection
- Security boundary: diff output never contains raw secrets
- CLI argument handling and error paths
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.sanitizer_drift_diff import (
    _assert_no_raw_secrets,
    _compute_parser_diff,
    _load_summary,
    _render_markdown,
    compute_drift_diff,
    main,
)

pytestmark = pytest.mark.unit


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_summary(
    parsers: list[dict[str, Any]],
    golden_hash: str = "abc123",
) -> dict[str, Any]:
    total_redacted = sum(p.get("redacted", 0) for p in parsers)
    total_degraded = sum(p.get("degraded", 0) for p in parsers)
    return {
        "artifact": "sanitizer-coverage-summary",
        "version": "1.0.0",
        "generated_at": "2026-05-11T00:00:00+00:00",
        "totals": {
            "fixtures": len(parsers),
            "redacted": total_redacted,
            "degraded": total_degraded,
        },
        "golden_hash": golden_hash,
        "parsers": parsers,
        "redaction_floor": 1,
        "redaction_floor_check": True,
    }


def _make_parser(
    parser_id: str,
    fixtures: int = 1,
    redacted: int = 2,
    degraded: int = 0,
    golden_hash: str = "hash",
    status: str = "success",
) -> dict[str, Any]:
    return {
        "parser_id": parser_id,
        "fixtures": fixtures,
        "redacted": redacted,
        "degraded": degraded,
        "golden_hash": golden_hash,
        "status": status,
    }


# ── _load_summary ────────────────────────────────────────────────────────────


def test_load_summary_valid(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    summary = _make_summary([_make_parser("parser.text")])
    path.write_text(json.dumps(summary), encoding="utf-8")
    loaded = _load_summary(path)
    assert loaded["artifact"] == "sanitizer-coverage-summary"
    assert loaded["totals"]["fixtures"] == 1


def test_load_summary_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _load_summary(tmp_path / "nope.json")


def test_load_summary_invalid_artifact(tmp_path: Path) -> None:
    path = tmp_path / "summary.json"
    path.write_text(json.dumps({"artifact": "wrong"}), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid artifact type"):
        _load_summary(path)


# ── _compute_parser_diff ─────────────────────────────────────────────────────


def test_parser_diff_unchanged() -> None:
    record = _make_parser("parser.text", redacted=2, degraded=0)
    assert _compute_parser_diff(record, record) is None


def test_parser_diff_added() -> None:
    head = _make_parser("parser.new", redacted=3, degraded=0)
    diff = _compute_parser_diff(None, head)
    assert diff is not None
    assert diff["change_type"] == "added"
    assert diff["parser_id"] == "parser.new"
    assert diff["head"]["redacted"] == 3
    assert diff["base"] is None


def test_parser_diff_removed() -> None:
    base = _make_parser("parser.old", redacted=1, degraded=1)
    diff = _compute_parser_diff(base, None)
    assert diff is not None
    assert diff["change_type"] == "removed"
    assert diff["parser_id"] == "parser.old"
    assert diff["base"]["degraded"] == 1
    assert diff["head"] is None


def test_parser_diff_redacted_changed() -> None:
    base = _make_parser("parser.text", redacted=2, degraded=0)
    head = _make_parser("parser.text", redacted=3, degraded=0)
    diff = _compute_parser_diff(base, head)
    assert diff is not None
    assert diff["change_type"] == "changed"
    assert diff["base"]["redacted"] == 2
    assert diff["head"]["redacted"] == 3


def test_parser_diff_status_changed() -> None:
    base = _make_parser("parser.text", status="success")
    head = _make_parser("parser.text", status="degraded")
    diff = _compute_parser_diff(base, head)
    assert diff is not None
    assert diff["base"]["status"] == "success"
    assert diff["head"]["status"] == "degraded"


# ── compute_drift_diff ───────────────────────────────────────────────────────


def test_drift_no_changes() -> None:
    parsers = [_make_parser("parser.text", redacted=2)]
    base = _make_summary(parsers, golden_hash="abc")
    head = _make_summary(parsers, golden_hash="abc")
    diff = compute_drift_diff(base, head)
    assert diff["parsers"]["added"] == []
    assert diff["parsers"]["removed"] == []
    assert diff["parsers"]["changed"] == []
    assert diff["golden_hash_drift"] is False
    assert diff["risk"] == "unchanged"
    assert diff["risk_details"] == []


def test_drift_parser_added() -> None:
    base = _make_summary([_make_parser("parser.text", redacted=2)])
    head = _make_summary(
        [
            _make_parser("parser.text", redacted=2),
            _make_parser("parser.new", redacted=1),
        ]
    )
    diff = compute_drift_diff(base, head)
    assert len(diff["parsers"]["added"]) == 1
    assert diff["parsers"]["added"][0]["parser_id"] == "parser.new"
    assert diff["risk"] == "unchanged"


def test_drift_parser_removed() -> None:
    base = _make_summary(
        [
            _make_parser("parser.text", redacted=2),
            _make_parser("parser.old", redacted=1),
        ]
    )
    head = _make_summary([_make_parser("parser.text", redacted=2)])
    diff = compute_drift_diff(base, head)
    assert len(diff["parsers"]["removed"]) == 1
    assert diff["parsers"]["removed"][0]["parser_id"] == "parser.old"
    # Removing a parser drops total redactions, which is flagged as degraded
    assert diff["risk"] == "degraded"


def test_drift_redaction_count_increased() -> None:
    base = _make_summary([_make_parser("parser.text", redacted=2)])
    head = _make_summary([_make_parser("parser.text", redacted=3)])
    diff = compute_drift_diff(base, head)
    assert len(diff["parsers"]["changed"]) == 1
    assert diff["totals"]["delta"]["redacted"] == 1
    assert diff["risk"] == "unchanged"


def test_drift_redaction_count_dropped_triggers_risk() -> None:
    base = _make_summary([_make_parser("parser.text", redacted=3)])
    head = _make_summary([_make_parser("parser.text", redacted=2)])
    diff = compute_drift_diff(base, head)
    assert diff["risk"] == "degraded"
    assert any(
        d["type"] == "parser_degraded" and d["parser_id"] == "parser.text"
        for d in diff["risk_details"]
    )


def test_drift_degraded_increased_triggers_risk() -> None:
    base = _make_summary([_make_parser("parser.text", redacted=2, degraded=0)])
    head = _make_summary([_make_parser("parser.text", redacted=2, degraded=1)])
    diff = compute_drift_diff(base, head)
    assert diff["risk"] == "degraded"
    assert diff["totals"]["delta"]["degraded"] == 1
    assert any(d["type"] == "parser_degraded" for d in diff["risk_details"])


def test_drift_total_redaction_drop_triggers_risk() -> None:
    base = _make_summary(
        [
            _make_parser("parser.a", redacted=3),
            _make_parser("parser.b", redacted=2),
        ]
    )
    head = _make_summary(
        [
            _make_parser("parser.a", redacted=1),
            _make_parser("parser.b", redacted=2),
        ]
    )
    diff = compute_drift_diff(base, head)
    assert diff["risk"] == "degraded"
    assert diff["totals"]["delta"]["redacted"] == -2
    assert any(d["type"] == "total_redaction_drop" for d in diff["risk_details"])


def test_drift_total_degraded_increase_triggers_risk() -> None:
    base = _make_summary(
        [
            _make_parser("parser.a", redacted=2, degraded=0),
            _make_parser("parser.b", redacted=2, degraded=0),
        ]
    )
    head = _make_summary(
        [
            _make_parser("parser.a", redacted=2, degraded=1),
            _make_parser("parser.b", redacted=2, degraded=0),
        ]
    )
    diff = compute_drift_diff(base, head)
    assert diff["risk"] == "degraded"
    assert diff["totals"]["delta"]["degraded"] == 1
    assert any(d["type"] == "total_degraded_increase" for d in diff["risk_details"])


def test_drift_golden_hash_drift() -> None:
    base = _make_summary([_make_parser("parser.text")], golden_hash="abc")
    head = _make_summary([_make_parser("parser.text")], golden_hash="def")
    diff = compute_drift_diff(base, head)
    assert diff["golden_hash_drift"] is True


def test_drift_added_parser_zero_redaction_is_risk() -> None:
    base = _make_summary([_make_parser("parser.text", redacted=2)])
    head = _make_summary(
        [
            _make_parser("parser.text", redacted=2),
            _make_parser("parser.new", redacted=0, degraded=0),
        ]
    )
    diff = compute_drift_diff(base, head)
    assert diff["risk"] == "degraded"
    assert any(
        d["type"] == "parser_added_with_risk" and d["parser_id"] == "parser.new"
        for d in diff["risk_details"]
    )


def test_drift_added_parser_degraded_is_risk() -> None:
    base = _make_summary([_make_parser("parser.text", redacted=2)])
    head = _make_summary(
        [
            _make_parser("parser.text", redacted=2),
            _make_parser("parser.new", redacted=2, degraded=1),
        ]
    )
    diff = compute_drift_diff(base, head)
    assert diff["risk"] == "degraded"
    assert any(d["type"] == "parser_added_with_risk" for d in diff["risk_details"])


def test_drift_multiple_changes() -> None:
    base = _make_summary(
        [
            _make_parser("parser.a", redacted=3, degraded=0),
            _make_parser("parser.b", redacted=2, degraded=1),
            _make_parser("parser.c", redacted=1, degraded=0),
        ]
    )
    head = _make_summary(
        [
            _make_parser("parser.a", redacted=2, degraded=0),  # redaction drop
            _make_parser("parser.b", redacted=2, degraded=1),
            _make_parser("parser.d", redacted=2, degraded=0),  # added
        ]
    )
    diff = compute_drift_diff(base, head)
    assert len(diff["parsers"]["removed"]) == 1
    assert diff["parsers"]["removed"][0]["parser_id"] == "parser.c"
    assert len(diff["parsers"]["added"]) == 1
    assert diff["parsers"]["added"][0]["parser_id"] == "parser.d"
    assert len(diff["parsers"]["changed"]) == 1
    assert diff["parsers"]["changed"][0]["parser_id"] == "parser.a"
    assert diff["risk"] == "degraded"


# ── Security boundary ─────────────────────────────────────────────────────────


def test_diff_output_never_contains_raw_secrets() -> None:
    """Even if input summaries contain secret-like strings in degraded_reason,
    the diff output must never propagate them."""
    base = _make_summary(
        [
            _make_parser(
                "parser.text",
                redacted=2,
                degraded=0,
            )
        ]
    )
    # Inject a secret-like degraded_reason that should NOT appear in diff
    head = _make_summary(
        [
            {
                "parser_id": "parser.text",
                "fixtures": 1,
                "redacted": 1,
                "degraded": 1,
                "golden_hash": "x",
                "status": "degraded",
                "degraded_reason": "Auth failed with Bearer eyJhbGci token",
            }
        ]
    )
    diff = compute_drift_diff(base, head)
    serialized = json.dumps(diff, indent=2, ensure_ascii=False)
    # The diff itself should not contain the secret fragment
    assert "Bearer eyJhbGci" not in serialized
    # The degraded_reason from head is NOT included in the diff output
    # (only base/head slices of fixtures/redacted/degraded/golden_hash/status)


def test_assert_no_raw_secrets_panics() -> None:
    with pytest.raises(RuntimeError, match="raw secret fragment"):
        _assert_no_raw_secrets({"foo": "contains Bearer token"}, "test")


def test_render_markdown_no_secrets() -> None:
    diff = compute_drift_diff(
        _make_summary([_make_parser("parser.text", redacted=2)]),
        _make_summary([_make_parser("parser.text", redacted=3)]),
    )
    md = _render_markdown(diff)
    assert "Bearer " not in md
    assert "PRIVATE KEY-----" not in md
    assert "sk-live-" not in md


# ── Markdown rendering ───────────────────────────────────────────────────────


def test_render_markdown_contains_expected_sections() -> None:
    summary = _make_summary([_make_parser("parser.text", redacted=2)])
    diff = compute_drift_diff(summary, summary)
    md = _render_markdown(diff)
    assert "## Sanitizer Golden Drift Diff" in md
    assert "### Totals" in md
    assert "### Risk Assessment" in md
    assert "No parser changes detected." in md


def test_render_markdown_with_changes() -> None:
    base = _make_summary(
        [
            _make_parser("parser.a", redacted=3),
            _make_parser("parser.b", redacted=2),
        ]
    )
    head = _make_summary(
        [
            _make_parser("parser.a", redacted=1),  # changed
            _make_parser("parser.c", redacted=2),  # added
        ]
    )
    diff = compute_drift_diff(base, head)
    md = _render_markdown(diff)
    assert "### Added Parsers" in md
    assert "### Removed Parsers" in md
    assert "### Changed Parsers" in md
    assert "`parser.a`" in md
    assert "`parser.b`" in md
    assert "`parser.c`" in md


def test_render_markdown_risk_degraded() -> None:
    base = _make_summary([_make_parser("parser.text", redacted=3)])
    head = _make_summary([_make_parser("parser.text", redacted=1)])
    diff = compute_drift_diff(base, head)
    md = _render_markdown(diff)
    assert "⚠️ `degraded`" in md
    assert "redactions dropped" in md.lower() or "degraded" in md.lower()


# ── CLI / main ───────────────────────────────────────────────────────────────


def test_cli_no_changes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base_path = tmp_path / "base.json"
    head_path = tmp_path / "head.json"
    out_path = tmp_path / "diff.json"
    summary = _make_summary([_make_parser("parser.text")])
    base_path.write_text(json.dumps(summary), encoding="utf-8")
    head_path.write_text(json.dumps(summary), encoding="utf-8")

    rc = main(["--base", str(base_path), "--head", str(head_path), "--output", str(out_path)])
    assert rc == 0
    assert out_path.is_file()
    diff = json.loads(out_path.read_text(encoding="utf-8"))
    assert diff["risk"] == "unchanged"


def test_cli_risk_exit_code(tmp_path: Path) -> None:
    base_path = tmp_path / "base.json"
    head_path = tmp_path / "head.json"
    out_path = tmp_path / "diff.json"
    base_path.write_text(
        json.dumps(_make_summary([_make_parser("parser.text", redacted=3)])),
        encoding="utf-8",
    )
    head_path.write_text(
        json.dumps(_make_summary([_make_parser("parser.text", redacted=1)])),
        encoding="utf-8",
    )

    rc = main(["--base", str(base_path), "--head", str(head_path), "--output", str(out_path)])
    assert rc == 2
    diff = json.loads(out_path.read_text(encoding="utf-8"))
    assert diff["risk"] == "degraded"


def test_cli_missing_base(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["--base", str(tmp_path / "nope.json"), "--head", str(tmp_path / "nope.json")])
    assert rc == 1


def test_cli_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base_path = tmp_path / "base.json"
    head_path = tmp_path / "head.json"
    summary = _make_summary([_make_parser("parser.text")])
    base_path.write_text(json.dumps(summary), encoding="utf-8")
    head_path.write_text(json.dumps(summary), encoding="utf-8")

    rc = main(
        [
            "--base",
            str(base_path),
            "--head",
            str(head_path),
            "--output",
            str(tmp_path / "diff.json"),
            "--stdout",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "Sanitizer Golden Drift Diff" in captured.out


def test_cli_markdown_only(tmp_path: Path) -> None:
    base_path = tmp_path / "base.json"
    head_path = tmp_path / "head.json"
    md_path = tmp_path / "report.md"
    summary = _make_summary([_make_parser("parser.text")])
    base_path.write_text(json.dumps(summary), encoding="utf-8")
    head_path.write_text(json.dumps(summary), encoding="utf-8")

    rc = main(
        [
            "--base",
            str(base_path),
            "--head",
            str(head_path),
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
    base_path = tmp_path / "base.json"
    head_path = tmp_path / "head.json"
    summary = _make_summary([_make_parser("parser.text")])
    base_path.write_text(json.dumps(summary), encoding="utf-8")
    head_path.write_text(json.dumps(summary), encoding="utf-8")

    rc = main(
        [
            "--base",
            str(base_path),
            "--head",
            str(head_path),
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
    base_path = tmp_path / "base.json"
    head_path = tmp_path / "head.json"
    out_path = tmp_path / "diff.json"
    summary = _make_summary([_make_parser("parser.text")])
    base_path.write_text(json.dumps(summary), encoding="utf-8")
    head_path.write_text(json.dumps(summary), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.sanitizer_drift_diff",
            "--base",
            str(base_path),
            "--head",
            str(head_path),
            "--output",
            str(out_path),
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 0, result.stderr
    assert out_path.is_file()
