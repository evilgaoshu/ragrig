"""CLI entry point for evaluation run retention cleanup: make eval-cleanup.

Usage:
    uv run python -m scripts.eval_cleanup --keep-count 20
    uv run python -m scripts.eval_cleanup --keep-days 30
    uv run python -m scripts.eval_cleanup --keep-count 20 --keep-days 30 --dry-run
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ragrig.evaluation.retention import cleanup_evaluation_runs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clean up old evaluation runs while protecting baselines."
    )
    parser.add_argument(
        "--store-dir",
        default="evaluation_runs",
        help="Directory containing evaluation runs. Default: evaluation_runs",
    )
    parser.add_argument(
        "--baseline-dir",
        default="evaluation_baselines",
        help="Directory containing baselines. Default: evaluation_baselines",
    )
    parser.add_argument(
        "--keep-count",
        type=int,
        default=None,
        help="Retain at most N newest runs (by file mtime).",
    )
    parser.add_argument(
        "--keep-days",
        type=int,
        default=None,
        help="Retain runs newer than N days.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be deleted without deleting.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.keep_count is None and args.keep_days is None:
        print(
            json.dumps(
                {
                    "error": "At least one of --keep-count or --keep-days is required.",
                    "hint": "Use --dry-run to preview without deleting.",
                },
                indent=2,
            )
        )
        return 1

    result = cleanup_evaluation_runs(
        store_dir=Path(args.store_dir),
        baseline_dir=Path(args.baseline_dir),
        keep_count=args.keep_count,
        keep_days=args.keep_days,
        dry_run=args.dry_run,
    )

    result["dry_run"] = args.dry_run
    result["store_dir"] = args.store_dir
    result["baseline_dir"] = args.baseline_dir

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
