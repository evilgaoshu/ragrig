"""Tests for the sanitizer drift history tool and Console adapter.

Covers:
- no-history (zero reports)
- multi-report trend (>=2 reports)
- corrupt artifact (JSON damage / schema incompatibility)
- Console data adapter (API return format)
- secret-like leak interception (forbidden fragments in output)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.sanitizer_drift_history import (
    _assert_no_raw_secrets,
    _collect_reports,
    _compute_trends,
    _latest_report_summary,
    _load_drift_report,
    _render_markdown,
    build_history,
    main,
)
from src.ragrig.web_console import get_sanitizer_drift_history

pytestmark = pytest.mark.unit


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_drift_report(
    generated_at: str = "2026-05-11T00:00:00+00:00",
    risk: str = "unchanged",
    base_hash: str = "abc123",
    head_hash: str = "def456",
    head_redacted: int = 10,
    head_degraded: int = 0,
    delta_redacted: int = 0,
    delta_degraded: int = 0,
    changed: list[dict[str, Any]] | None = None,
    added: list[dict[str, Any]] | None = None,
    removed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "artifact": "sanitizer-drift-diff",
        "version": "1.0.0",
        "generated_at": generated_at,
        "base_golden_hash": base_hash,
        "head_golden_hash": head_hash,
        "golden_hash_drift": base_hash != head_hash,
        "totals": {
            "base": {"fixtures": 4, "redacted": 8, "degraded": 0},
            "head": {"fixtures": 4, "redacted": head_redacted, "degraded": head_degraded},
            "delta": {"fixtures": 0, "redacted": delta_redacted, "degraded": delta_degraded},
        },
        "risk": risk,
        "risk_details": [],
        "parsers": {
            "added": added or [],
            "removed": removed or [],
            "changed": changed or [],
        },
    }


# ── _load_drift_report ───────────────────────────────────────────────────────


def test_load_drift_report_valid(tmp_path: Path) -> None:
    path = tmp_path / "drift.json"
    report = _make_drift_report()
    path.write_text(json.dumps(report), encoding="utf-8")
    loaded = _load_drift_report(path)
    assert loaded["artifact"] == "sanitizer-drift-diff"
    assert loaded["risk"] == "unchanged"


def test_load_drift_report_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _load_drift_report(tmp_path / "nope.json")


def test_load_drift_report_invalid_artifact(tmp_path: Path) -> None:
    path = tmp_path / "drift.json"
    path.write_text(json.dumps({"artifact": "wrong"}), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid artifact type"):
        _load_drift_report(path)


def test_load_drift_report_missing_key(tmp_path: Path) -> None:
    path = tmp_path / "drift.json"
    path.write_text(
        json.dumps({"artifact": "sanitizer-drift-diff", "version": "1.0.0"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Missing required key"):
        _load_drift_report(path)


def test_load_drift_report_corrupt_json(tmp_path: Path) -> None:
    path = tmp_path / "drift.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        _load_drift_report(path)


# ── _collect_reports ─────────────────────────────────────────────────────────


def test_collect_reports_empty_dir(tmp_path: Path) -> None:
    reports = _collect_reports(tmp_path)
    assert reports == []


def test_collect_reports_no_matching_files(tmp_path: Path) -> None:
    (tmp_path / "other.json").write_text("{}", encoding="utf-8")
    reports = _collect_reports(tmp_path)
    assert reports == []


def test_collect_reports_single_valid(tmp_path: Path) -> None:
    path = tmp_path / "sanitizer-drift-diff.json"
    path.write_text(json.dumps(_make_drift_report()), encoding="utf-8")
    reports = _collect_reports(tmp_path)
    assert len(reports) == 1
    assert reports[0]["risk"] == "unchanged"


def test_collect_reports_multi_sorted(tmp_path: Path) -> None:
    (tmp_path / "sanitizer-drift-diff-01.json").write_text(
        json.dumps(_make_drift_report(generated_at="2026-05-10T00:00:00+00:00")),
        encoding="utf-8",
    )
    (tmp_path / "sanitizer-drift-diff-02.json").write_text(
        json.dumps(_make_drift_report(generated_at="2026-05-11T00:00:00+00:00")),
        encoding="utf-8",
    )
    reports = _collect_reports(tmp_path)
    assert len(reports) == 2
    assert reports[0]["generated_at"] == "2026-05-10T00:00:00+00:00"
    assert reports[1]["generated_at"] == "2026-05-11T00:00:00+00:00"


def test_collect_reports_skips_corrupt(tmp_path: Path) -> None:
    (tmp_path / "sanitizer-drift-diff.json").write_text(
        json.dumps(_make_drift_report()), encoding="utf-8"
    )
    (tmp_path / "sanitizer-drift-diff-bad.json").write_text("not json", encoding="utf-8")
    reports = _collect_reports(tmp_path)
    assert len(reports) == 2
    valid = [r for r in reports if not r.get("_degraded")]
    degraded = [r for r in reports if r.get("_degraded")]
    assert len(valid) == 1
    assert len(degraded) == 1
    assert "bad.json" in degraded[0]["_source_path"]


def test_collect_reports_skips_invalid_schema(tmp_path: Path) -> None:
    (tmp_path / "sanitizer-drift-diff.json").write_text(
        json.dumps(_make_drift_report()), encoding="utf-8"
    )
    (tmp_path / "sanitizer-drift-diff-wrong.json").write_text(
        json.dumps({"artifact": "sanitizer-drift-diff", "version": "1.0.0"}),
        encoding="utf-8",
    )
    reports = _collect_reports(tmp_path)
    valid = [r for r in reports if not r.get("_degraded")]
    degraded = [r for r in reports if r.get("_degraded")]
    assert len(valid) == 1
    assert len(degraded) == 1


# ── _compute_trends ──────────────────────────────────────────────────────────


def test_compute_trends_no_reports() -> None:
    trends = _compute_trends([])
    assert trends["available"] is False
    assert trends["valid_report_count"] == 0


def test_compute_trends_multi_report() -> None:
    reports = [
        _make_drift_report(
            generated_at="2026-05-10T00:00:00+00:00",
            head_redacted=8,
            delta_redacted=0,
            changed=[{"parser_id": "p1"}],
        ),
        _make_drift_report(
            generated_at="2026-05-11T00:00:00+00:00",
            head_redacted=10,
            delta_redacted=2,
            changed=[{"parser_id": "p1"}, {"parser_id": "p2"}],
        ),
    ]
    trends = _compute_trends(reports)
    assert trends["available"] is True
    assert trends["valid_report_count"] == 2
    assert len(trends["parser_trend"]) == 2
    assert trends["parser_trend"][0]["changed"] == 1
    assert trends["parser_trend"][1]["changed"] == 2
    assert trends["redaction_trend"][0]["head_redacted"] == 8
    assert trends["redaction_trend"][1]["head_redacted"] == 10


# ── _latest_report_summary ───────────────────────────────────────────────────


def test_latest_report_summary_none() -> None:
    assert _latest_report_summary([]) is None


def test_latest_report_summary_basic() -> None:
    reports = [
        _make_drift_report(
            generated_at="2026-05-10T00:00:00+00:00",
            risk="unchanged",
            changed=[{"parser_id": "p1"}],
        ),
        _make_drift_report(
            generated_at="2026-05-11T00:00:00+00:00",
            risk="degraded",
            changed=[{"parser_id": "p1"}, {"parser_id": "p2"}],
        ),
    ]
    latest = _latest_report_summary(reports)
    assert latest is not None
    assert latest["risk"] == "degraded"
    assert latest["changed_parser_count"] == 2
    assert latest["base_golden_hash"] == "abc123"
    assert latest["head_golden_hash"] == "def456"


# ── build_history ────────────────────────────────────────────────────────────


def test_build_history_no_history(tmp_path: Path) -> None:
    history = build_history(tmp_path)
    assert history["artifact"] == "sanitizer-drift-history"
    assert history["status"] == "no_history"
    assert history["trends"]["available"] is False
    assert history["latest"] is None


def test_build_history_with_reports(tmp_path: Path) -> None:
    (tmp_path / "sanitizer-drift-diff.json").write_text(
        json.dumps(_make_drift_report()), encoding="utf-8"
    )
    history = build_history(tmp_path)
    assert history["status"] == "success"
    assert history["latest"] is not None
    assert history["trends"]["available"] is True


def test_build_history_with_degraded(tmp_path: Path) -> None:
    (tmp_path / "sanitizer-drift-diff.json").write_text(
        json.dumps(_make_drift_report()), encoding="utf-8"
    )
    (tmp_path / "sanitizer-drift-diff-bad.json").write_text("not json", encoding="utf-8")
    history = build_history(tmp_path)
    assert history["status"] == "degraded"
    assert len(history["degraded_reports"]) == 1


# ── Security boundary ─────────────────────────────────────────────────────────


def test_assert_no_raw_secrets_panics() -> None:
    with pytest.raises(RuntimeError, match="raw secret fragment"):
        _assert_no_raw_secrets({"foo": "contains Bearer token"}, "test")


def test_build_history_no_secrets_in_output(tmp_path: Path) -> None:
    report = _make_drift_report()
    report["risk_details"] = [{"type": "test", "reason": "Auth failed with sk-live-12345"}]
    (tmp_path / "sanitizer-drift-diff.json").write_text(json.dumps(report), encoding="utf-8")
    history = build_history(tmp_path)
    serialized = json.dumps(history, indent=2, ensure_ascii=False)
    # The secret from input risk_details must not propagate to history output
    assert "sk-live-12345" not in serialized


def test_render_markdown_no_secrets() -> None:
    history = build_history(Path("/nonexistent"))
    md = _render_markdown(history)
    assert "Bearer " not in md
    assert "PRIVATE KEY-----" not in md
    assert "sk-live-" not in md


# ── CLI / main ───────────────────────────────────────────────────────────────


def test_cli_no_history(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out_path = tmp_path / "history.json"
    rc = main(["--artifacts-dir", str(tmp_path), "--output", str(out_path)])
    assert rc == 0
    assert out_path.is_file()
    history = json.loads(out_path.read_text(encoding="utf-8"))
    assert history["status"] == "no_history"


def test_cli_with_history(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "sanitizer-drift-diff.json").write_text(
        json.dumps(_make_drift_report()), encoding="utf-8"
    )
    out_path = tmp_path / "history.json"
    rc = main(["--artifacts-dir", str(tmp_path), "--output", str(out_path)])
    assert rc == 0
    history = json.loads(out_path.read_text(encoding="utf-8"))
    assert history["status"] == "success"


def test_cli_degraded_history(tmp_path: Path) -> None:
    (tmp_path / "sanitizer-drift-diff.json").write_text(
        json.dumps(_make_drift_report()), encoding="utf-8"
    )
    (tmp_path / "sanitizer-drift-diff-bad.json").write_text("not json", encoding="utf-8")
    out_path = tmp_path / "history.json"
    rc = main(["--artifacts-dir", str(tmp_path), "--output", str(out_path)])
    assert rc == 3
    history = json.loads(out_path.read_text(encoding="utf-8"))
    assert history["status"] == "degraded"


def test_cli_stdout(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "sanitizer-drift-diff.json").write_text(
        json.dumps(_make_drift_report()), encoding="utf-8"
    )
    rc = main(
        [
            "--artifacts-dir",
            str(tmp_path),
            "--output",
            str(tmp_path / "history.json"),
            "--stdout",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "Sanitizer Drift History" in captured.out


def test_cli_markdown_only(tmp_path: Path) -> None:
    (tmp_path / "sanitizer-drift-diff.json").write_text(
        json.dumps(_make_drift_report()), encoding="utf-8"
    )
    md_path = tmp_path / "report.md"
    rc = main(
        [
            "--artifacts-dir",
            str(tmp_path),
            "--output",
            str(tmp_path / "history.json"),
            "--markdown-output",
            str(md_path),
            "--format",
            "markdown",
        ]
    )
    assert rc == 0
    assert not (tmp_path / "history.json").is_file()
    assert md_path.is_file()


# ── End-to-end via subprocess ────────────────────────────────────────────────


def test_subprocess_invocation(tmp_path: Path) -> None:
    (tmp_path / "sanitizer-drift-diff.json").write_text(
        json.dumps(_make_drift_report()), encoding="utf-8"
    )
    out_path = tmp_path / "history.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.sanitizer_drift_history",
            "--artifacts-dir",
            str(tmp_path),
            "--output",
            str(out_path),
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 0, result.stderr
    assert out_path.is_file()


# ── Console data adapter ─────────────────────────────────────────────────────


def test_console_adapter_no_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.ragrig.web_console._SANITIZER_DRIFT_ARTIFACTS_DIR", tmp_path)
    result = get_sanitizer_drift_history()
    assert result["available"] is False
    assert result["status"] == "no_history"


def test_console_adapter_with_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "sanitizer-drift-diff.json").write_text(
        json.dumps(_make_drift_report(risk="degraded", changed=[{"parser_id": "p1"}])),
        encoding="utf-8",
    )
    monkeypatch.setattr("src.ragrig.web_console._SANITIZER_DRIFT_ARTIFACTS_DIR", tmp_path)
    result = get_sanitizer_drift_history()
    assert result["available"] is True
    assert result["status"] == "success"
    assert result["risk"] == "degraded"
    assert result["changed_parser_count"] == 1
    assert "sparkline" in result
    assert result["sparkline"]["risk"] == ["degraded"]


def test_console_adapter_corrupt_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "sanitizer-drift-diff.json").write_text("not json", encoding="utf-8")
    monkeypatch.setattr("src.ragrig.web_console._SANITIZER_DRIFT_ARTIFACTS_DIR", tmp_path)
    result = get_sanitizer_drift_history()
    assert result["available"] is False
    assert result["status"] == "no_history"
    assert result["degraded_count"] == 1


def test_console_adapter_invalid_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "sanitizer-drift-diff.json").write_text(
        json.dumps({"artifact": "wrong-thing", "version": "1.0.0"}),
        encoding="utf-8",
    )
    monkeypatch.setattr("src.ragrig.web_console._SANITIZER_DRIFT_ARTIFACTS_DIR", tmp_path)
    result = get_sanitizer_drift_history()
    assert result["available"] is False
    assert result["status"] == "no_history"
    assert result["degraded_count"] == 1


def test_console_adapter_multi_sparkline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for i in range(3):
        (tmp_path / f"sanitizer-drift-diff-{i:02d}.json").write_text(
            json.dumps(
                _make_drift_report(
                    generated_at=f"2026-05-{10 + i}T00:00:00+00:00",
                    head_redacted=8 + i,
                    risk="unchanged" if i < 2 else "degraded",
                )
            ),
            encoding="utf-8",
        )
    monkeypatch.setattr("src.ragrig.web_console._SANITIZER_DRIFT_ARTIFACTS_DIR", tmp_path)
    result = get_sanitizer_drift_history()
    assert result["available"] is True
    assert result["report_count"] == 3
    assert len(result["sparkline"]["risk"]) == 3
    assert result["sparkline"]["redacted"] == [8, 9, 10]
    assert result["sparkline"]["degraded"] == [0, 0, 0]
