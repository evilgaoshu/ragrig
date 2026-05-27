"""Clean generated Graph Console demo artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from scripts.artifact_cleanup import _assert_no_raw_secrets

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACTS_DIR = REPO_ROOT / "docs" / "operations" / "artifacts"

DEMO_ARTIFACTS = (
    "demo-graph-console.db",
    "demo-graph-console-runbook.json",
    "demo-graph-console-runbook.md",
    "demo-graph-console-smoke.json",
    "demo-rc-gate.json",
    "demo-rc-gate.md",
    "evaluation_runs/demo-rc-dense.json",
    "evaluation_runs/demo-rc-graph.json",
    "evaluation_runs/demo-rc-hybrid_graph.json",
)


def _display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _target_paths(artifacts_dir: Path) -> list[Path]:
    return [artifacts_dir / relative for relative in DEMO_ARTIFACTS]


def run_cleanup(
    *,
    artifacts_dir: Path = DEFAULT_ARTIFACTS_DIR,
    confirm_delete: bool = False,
) -> dict[str, Any]:
    artifacts_dir = artifacts_dir.resolve()
    dry_run = not confirm_delete
    targets = _target_paths(artifacts_dir)
    existing = [path for path in targets if path.exists()]
    missing = [path for path in targets if not path.exists()]
    deleted: list[str] = []
    failed: list[dict[str, str]] = []

    if confirm_delete:
        for path in existing:
            try:
                path.unlink()
                deleted.append(_display(path))
            except OSError as exc:
                failed.append({"path": _display(path), "error": str(exc)})

    removed_dirs: list[str] = []
    eval_dir = artifacts_dir / "evaluation_runs"
    if confirm_delete and eval_dir.exists() and eval_dir.is_dir():
        try:
            next(eval_dir.iterdir())
        except StopIteration:
            try:
                eval_dir.rmdir()
                removed_dirs.append(_display(eval_dir))
            except OSError as exc:
                failed.append({"path": _display(eval_dir), "error": str(exc)})

    status = "dry_run" if dry_run else "success"
    if failed:
        status = "failure"
    return {
        "artifact": "demo-graph-console-cleanup",
        "status": status,
        "dry_run": dry_run,
        "artifacts_dir": _display(artifacts_dir),
        "target_count": len(targets),
        "existing_count": len(existing),
        "would_delete": [_display(path) for path in existing] if dry_run else [],
        "deleted_count": len(deleted),
        "deleted": deleted,
        "missing": [_display(path) for path in missing],
        "removed_dirs": removed_dirs,
        "failed": failed,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Clean generated Graph Console demo artifacts.")
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=DEFAULT_ARTIFACTS_DIR,
        help="Directory containing demo artifacts.",
    )
    parser.add_argument(
        "--confirm-delete",
        action="store_true",
        help="Actually delete artifacts. Without this flag, only lists targets.",
    )
    parser.add_argument("--stdout", action="store_true", help="Print result JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_cleanup(
        artifacts_dir=args.artifacts_dir,
        confirm_delete=args.confirm_delete,
    )
    _assert_no_raw_secrets(result, "demo-graph-console-cleanup")
    if args.stdout or not args.confirm_delete:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 1 if result["status"] == "failure" else 0


if __name__ == "__main__":
    sys.exit(main())
