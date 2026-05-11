"""CLI entry point for promoting an evaluation run to baseline: make eval-baseline.

Usage:
    uv run python -m scripts.eval_baseline --run-id <uuid>
    uv run python -m scripts.eval_baseline --run-id <uuid> --baseline-id my-baseline
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ragrig.evaluation.baseline import (
    BaselineError,
    promote_run_to_baseline,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Promote an evaluation run to a baseline.")
    parser.add_argument(
        "--run-id",
        required=True,
        help="ID of the evaluation run to promote.",
    )
    parser.add_argument(
        "--baseline-id",
        default=None,
        help="Optional custom baseline ID. Generated if not provided.",
    )
    parser.add_argument(
        "--store-dir",
        default="evaluation_runs",
        help="Directory containing evaluation runs. Default: evaluation_runs",
    )
    parser.add_argument(
        "--baseline-dir",
        default="evaluation_baselines",
        help="Directory to store baselines. Default: evaluation_baselines",
    )
    parser.add_argument(
        "--promoted-by",
        default=None,
        help="Optional identifier of who/what promoted the baseline.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output path for baseline metadata JSON.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    store_dir = Path(args.store_dir)
    baseline_dir = Path(args.baseline_dir)

    try:
        metadata = promote_run_to_baseline(
            run_id=args.run_id,
            store_dir=store_dir,
            baseline_dir=baseline_dir,
            baseline_id=args.baseline_id,
            promoted_by=args.promoted_by,
        )
    except BaselineError as exc:
        print(
            json.dumps(
                {"error": str(exc), "status": "failed"},
                indent=2,
                ensure_ascii=False,
            )
        )
        return 1

    print(json.dumps(metadata, indent=2, ensure_ascii=False))

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nBaseline metadata written to {output_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
