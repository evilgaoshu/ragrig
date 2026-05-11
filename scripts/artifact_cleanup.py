"""CLI entry point for artifact retention cleanup.

Usage::

    python -m scripts.artifact_cleanup \
        --artifacts-dir <dir> \
        --pattern "sanitizer-drift-diff*.json" \
        --keep-count 10 \
        --dry-run          # default behaviour: list only

    python -m scripts.artifact_cleanup \
        --artifacts-dir <dir> \
        --pattern "*.json" \
        --keep-days 30 \
        --confirm-delete   # required to actually delete

Security: output is audited for raw secret fragments before printing.
Missing or inaccessible directories are reported as failure, never success.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ── Fields that must never appear in output ────────────────────────────────
_FORBIDDEN_FRAGMENTS: tuple[str, ...] = (
    "sk-live-",
    "sk-proj-",
    "sk-ant-",
    "ghp_",
    "Bearer ",
    "PRIVATE KEY-----",
    "super_secret_db_pass",
    "db-super-secret-999",
    "prod-api-secret-key-2024",
)


def _assert_no_raw_secrets(data: object, source: str) -> None:
    """Panic if any string value in *data* contains a forbidden fragment."""
    if isinstance(data, str):
        for fragment in _FORBIDDEN_FRAGMENTS:
            if fragment in data:
                raise RuntimeError(f"{source}: raw secret fragment {fragment!r} detected in output")
    elif isinstance(data, dict):
        for k, v in data.items():
            _assert_no_raw_secrets(v, f"{source}.{k}")
    elif isinstance(data, list):
        for i, v in enumerate(data):
            _assert_no_raw_secrets(v, f"{source}[{i}]")


def _resolve_artifacts_dir(path: Path | None) -> Path:
    """Resolve the artifacts directory, failing safely if missing."""
    if path is None:
        repo_root = Path(__file__).resolve().parents[1]
        path = repo_root / "docs" / "operations" / "artifacts"
    if not path.exists():
        raise FileNotFoundError(f"Artifacts directory not found: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"Not a directory: {path}")
    return path


def _collect_candidates(
    artifacts_dir: Path,
    pattern: str,
) -> list[Path]:
    """Collect all files matching the glob pattern, sorted by mtime descending."""
    candidates = list(artifacts_dir.glob(pattern))
    # Sort by mtime descending (newest first)
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates


def _select_for_cleanup(
    candidates: list[Path],
    *,
    keep_count: int | None,
    keep_days: int | None,
) -> list[Path]:
    """Select files to remove based on keep_count and/or keep_days."""
    if not candidates:
        return []

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=keep_days) if keep_days is not None else None

    to_keep: set[Path] = set()

    # Keep by count (newest N)
    if keep_count is not None:
        for c in candidates[:keep_count]:
            to_keep.add(c.resolve())

    # Keep by age (newer than cutoff)
    if cutoff is not None:
        for c in candidates:
            mtime = datetime.fromtimestamp(c.stat().st_mtime, tz=timezone.utc)
            if mtime >= cutoff:
                to_keep.add(c.resolve())

    # If no keep rules were specified, keep everything (safe default)
    if keep_count is None and keep_days is None:
        to_keep = {c.resolve() for c in candidates}

    to_remove = [c for c in candidates if c.resolve() not in to_keep]
    return to_remove


def _delete_files(files: list[Path], dry_run: bool) -> dict[str, Any]:
    """Delete files or simulate deletion. Returns result metadata."""
    deleted: list[str] = []
    failed: list[dict[str, str]] = []

    for f in files:
        if dry_run:
            continue
        try:
            f.unlink()
            deleted.append(str(f.name))
        except OSError as exc:
            failed.append({"path": str(f.name), "error": str(exc)})

    return {"deleted": deleted, "failed": failed}


def run_cleanup(
    artifacts_dir: Path,
    pattern: str,
    *,
    keep_count: int | None,
    keep_days: int | None,
    confirm_delete: bool,
) -> dict[str, Any]:
    """Run the cleanup logic and return a structured result."""
    candidates = _collect_candidates(artifacts_dir, pattern)
    to_remove = _select_for_cleanup(candidates, keep_count=keep_count, keep_days=keep_days)

    dry_run = not confirm_delete

    result = _delete_files(to_remove, dry_run=dry_run)

    return {
        "status": "dry_run" if dry_run else "success",
        "dry_run": dry_run,
        "artifacts_dir": str(artifacts_dir),
        "pattern": pattern,
        "keep_count": keep_count,
        "keep_days": keep_days,
        "total_matched": len(candidates),
        "to_remove_count": len(to_remove),
        "to_remove": [str(f.name) for f in to_remove],
        "deleted_count": len(result["deleted"]),
        "deleted": result["deleted"],
        "failed": result["failed"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Clean up old artifact files with dry-run by default."
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=None,
        help="Directory containing artifacts. Default: docs/operations/artifacts",
    )
    parser.add_argument(
        "--pattern",
        default="*",
        help='Glob pattern for files to consider. Default: "*"',
    )
    parser.add_argument(
        "--keep-count",
        type=int,
        default=None,
        help="Retain at most N newest files (by mtime).",
    )
    parser.add_argument(
        "--keep-days",
        type=int,
        default=None,
        help="Retain files newer than N days.",
    )
    parser.add_argument(
        "--confirm-delete",
        action="store_true",
        help="Actually delete files. Without this flag, only lists what would be deleted.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print result JSON to stdout",
    )
    args = parser.parse_args(argv)

    try:
        artifacts_dir = _resolve_artifacts_dir(args.artifacts_dir)
    except (FileNotFoundError, NotADirectoryError, OSError) as exc:
        result = {
            "status": "failure",
            "error": str(exc),
            "dry_run": True,
            "confirm_delete": False,
        }
        _assert_no_raw_secrets(result, "artifact-cleanup")
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1

    result = run_cleanup(
        artifacts_dir=artifacts_dir,
        pattern=args.pattern,
        keep_count=args.keep_count,
        keep_days=args.keep_days,
        confirm_delete=args.confirm_delete,
    )

    _assert_no_raw_secrets(result, "artifact-cleanup")

    if args.stdout or not args.confirm_delete:
        print(json.dumps(result, indent=2, ensure_ascii=False))

    if result["status"] == "failure":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
