"""Tests for the artifact cleanup tool.

Covers:
- dry-run by default (lists files, does not delete)
- confirm-delete actually deletes files
- missing directory failure
- keep-count filtering
- keep-days filtering
- secret-like leak interception in output
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.artifact_cleanup import (
    _assert_no_raw_secrets,
    _collect_candidates,
    _delete_files,
    _resolve_artifacts_dir,
    _select_for_cleanup,
    main,
    run_cleanup,
)

pytestmark = pytest.mark.unit


# ── _resolve_artifacts_dir ───────────────────────────────────────────────────


def test_resolve_artifacts_dir_valid(tmp_path: Path) -> None:
    resolved = _resolve_artifacts_dir(tmp_path)
    assert resolved == tmp_path


def test_resolve_artifacts_dir_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        _resolve_artifacts_dir(tmp_path / "nope")


def test_resolve_artifacts_dir_not_a_dir(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        _resolve_artifacts_dir(path)


# ── _collect_candidates ──────────────────────────────────────────────────────


def test_collect_candidates_empty(tmp_path: Path) -> None:
    assert _collect_candidates(tmp_path, "*.json") == []


def test_collect_candidates_sorted_by_mtime(tmp_path: Path) -> None:
    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text("{}", encoding="utf-8")
    new.write_text("{}", encoding="utf-8")
    candidates = _collect_candidates(tmp_path, "*.json")
    assert len(candidates) == 2
    # Newest first
    assert candidates[0].name == "new.json"


# ── _select_for_cleanup ──────────────────────────────────────────────────────


def test_select_for_cleanup_no_rules() -> None:
    candidates = [Path("a.json"), Path("b.json")]
    to_remove = _select_for_cleanup(candidates, keep_count=None, keep_days=None)
    assert to_remove == []


def test_select_for_cleanup_keep_count() -> None:
    candidates = [Path("a.json"), Path("b.json"), Path("c.json")]
    to_remove = _select_for_cleanup(candidates, keep_count=2, keep_days=None)
    assert len(to_remove) == 1
    assert to_remove[0].name == "c.json"


def test_select_for_cleanup_keep_days(tmp_path: Path) -> None:
    import time

    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text("{}", encoding="utf-8")
    new.write_text("{}", encoding="utf-8")
    # Make old really old
    old_mtime = time.time() - (40 * 86400)
    new_mtime = time.time() - (5 * 86400)
    old.stat()  # ensure file exists
    import os

    os.utime(old, (old_mtime, old_mtime))
    os.utime(new, (new_mtime, new_mtime))

    candidates = _collect_candidates(tmp_path, "*.json")
    to_remove = _select_for_cleanup(candidates, keep_count=None, keep_days=30)
    assert len(to_remove) == 1
    assert to_remove[0].name == "old.json"


# ── _delete_files ────────────────────────────────────────────────────────────


def test_delete_files_dry_run(tmp_path: Path) -> None:
    path = tmp_path / "to_delete.json"
    path.write_text("{}", encoding="utf-8")
    result = _delete_files([path], dry_run=True)
    assert path.exists()  # not deleted
    assert result["deleted"] == []
    assert result["failed"] == []


def test_delete_files_actual_delete(tmp_path: Path) -> None:
    path = tmp_path / "to_delete.json"
    path.write_text("{}", encoding="utf-8")
    result = _delete_files([path], dry_run=False)
    assert not path.exists()
    assert result["deleted"] == ["to_delete.json"]
    assert result["failed"] == []


# ── run_cleanup ──────────────────────────────────────────────────────────────


def test_run_cleanup_dry_run_by_default(tmp_path: Path) -> None:
    for i in range(3):
        (tmp_path / f"file{i}.json").write_text("{}", encoding="utf-8")
    result = run_cleanup(
        tmp_path,
        "*.json",
        keep_count=1,
        keep_days=None,
        confirm_delete=False,
    )
    assert result["status"] == "dry_run"
    assert result["dry_run"] is True
    assert result["to_remove_count"] == 2
    assert all((tmp_path / f"file{i}.json").exists() for i in range(3))


def test_run_cleanup_confirm_delete(tmp_path: Path) -> None:
    for i in range(3):
        (tmp_path / f"file{i}.json").write_text("{}", encoding="utf-8")
    result = run_cleanup(
        tmp_path,
        "*.json",
        keep_count=1,
        keep_days=None,
        confirm_delete=True,
    )
    assert result["status"] == "success"
    assert result["dry_run"] is False
    assert result["deleted_count"] == 2
    remaining = list(tmp_path.glob("*.json"))
    assert len(remaining) == 1


def test_run_cleanup_no_matches(tmp_path: Path) -> None:
    result = run_cleanup(
        tmp_path,
        "*.json",
        keep_count=1,
        keep_days=None,
        confirm_delete=False,
    )
    assert result["status"] == "dry_run"
    assert result["to_remove_count"] == 0


# ── Security boundary ─────────────────────────────────────────────────────────


def test_assert_no_raw_secrets_panics() -> None:
    with pytest.raises(RuntimeError, match="raw secret fragment"):
        _assert_no_raw_secrets({"foo": "contains Bearer token"}, "test")


def test_run_cleanup_output_no_secrets(tmp_path: Path) -> None:
    result = run_cleanup(
        tmp_path,
        "*.json",
        keep_count=1,
        keep_days=None,
        confirm_delete=False,
    )
    serialized = json.dumps(result, indent=2, ensure_ascii=False)
    assert "Bearer " not in serialized
    assert "PRIVATE KEY-----" not in serialized
    assert "sk-live-" not in serialized


# ── CLI / main ───────────────────────────────────────────────────────────────


def test_cli_dry_run_default(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for i in range(3):
        (tmp_path / f"file{i}.json").write_text("{}", encoding="utf-8")
    rc = main(
        [
            "--artifacts-dir",
            str(tmp_path),
            "--pattern",
            "*.json",
            "--keep-count",
            "1",
            "--stdout",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "dry_run"
    assert data["dry_run"] is True
    assert data["to_remove_count"] == 2
    # Files still exist
    assert all((tmp_path / f"file{i}.json").exists() for i in range(3))


def test_cli_confirm_delete(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for i in range(3):
        (tmp_path / f"file{i}.json").write_text("{}", encoding="utf-8")
    rc = main(
        [
            "--artifacts-dir",
            str(tmp_path),
            "--pattern",
            "*.json",
            "--keep-count",
            "1",
            "--confirm-delete",
            "--stdout",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "success"
    assert data["dry_run"] is False
    assert data["deleted_count"] == 2


def test_cli_missing_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "--artifacts-dir",
            str(tmp_path / "nope"),
            "--pattern",
            "*.json",
            "--keep-count",
            "1",
        ]
    )
    assert rc == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "failure"
    assert "not found" in data["error"].lower()


def test_cli_keep_days(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import os
    import time

    old = tmp_path / "old.json"
    new = tmp_path / "new.json"
    old.write_text("{}", encoding="utf-8")
    new.write_text("{}", encoding="utf-8")
    os.utime(old, (time.time() - 40 * 86400, time.time() - 40 * 86400))
    os.utime(new, (time.time() - 5 * 86400, time.time() - 5 * 86400))

    rc = main(
        [
            "--artifacts-dir",
            str(tmp_path),
            "--pattern",
            "*.json",
            "--keep-days",
            "30",
            "--stdout",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "dry_run"
    assert data["to_remove_count"] == 1
    assert data["to_remove"] == ["old.json"]


# ── End-to-end via subprocess ────────────────────────────────────────────────


def test_subprocess_invocation(tmp_path: Path) -> None:
    for i in range(3):
        (tmp_path / f"file{i}.json").write_text("{}", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.artifact_cleanup",
            "--artifacts-dir",
            str(tmp_path),
            "--pattern",
            "*.json",
            "--keep-count",
            "1",
            "--stdout",
        ],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["status"] == "dry_run"
    assert data["to_remove_count"] == 2
