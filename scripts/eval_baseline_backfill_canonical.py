"""CLI entry point for canonical backfill of existing baselines.

Scans all baselines in the baseline directory and rewrites their
metrics section with the canonical Pydantic representation, then
regenerates the corresponding manifest.

Usage:
    uv run python -m scripts.eval_baseline_backfill_canonical
    uv run python -m scripts.eval_baseline_backfill_canonical --dry-run
    uv run python -m scripts.eval_baseline_backfill_canonical --baseline-dir /path
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ragrig.evaluation.baseline_manifest import (
    _canonical_metrics_dict,
    build_manifest,
    read_manifest,
    write_manifest,
)

DEFAULT_BASELINE_DIR = Path("evaluation_baselines")


def _is_canonical(metrics_raw: dict[str, Any]) -> bool:
    """Check if a raw metrics dict is already canonical (all fields present)."""
    canonical = _canonical_metrics_dict(metrics_raw)
    return metrics_raw == canonical


def _backfill_baseline(
    baseline_path: Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Backfill canonical metrics and manifest for a single baseline.

    Returns a dict with:
    - path: the baseline file path
    - metrics_changed: bool, whether metrics were non-canonical
    - manifest_action: "created", "rewritten", or "unchanged"
    """
    result: dict[str, Any] = {
        "path": str(baseline_path),
        "metrics_changed": False,
        "manifest_action": "unchanged",
    }

    if not baseline_path.exists():
        result["error"] = "file_not_found"
        return result

    try:
        raw = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        result["error"] = f"corrupt_json: {exc}"
        return result

    metrics_raw = raw.get("metrics")
    if not metrics_raw or not isinstance(metrics_raw, dict):
        result["error"] = "missing_or_invalid_metrics"
        return result

    # Check if already canonical
    if _is_canonical(metrics_raw):
        result["metrics_changed"] = False
        result["manifest_action"] = "unchanged"
        return result

    result["metrics_changed"] = True
    canonical_metrics = _canonical_metrics_dict(metrics_raw)

    if dry_run:
        return result

    # Write canonical metrics back to the baseline file
    raw["metrics"] = canonical_metrics
    baseline_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")

    # Check existing manifest
    manifest_path = baseline_path.with_suffix(".manifest.json")
    if manifest_path.exists():
        try:
            existing_manifest = read_manifest(baseline_path)
            existing_hash = existing_manifest.get("metrics_hash", "")
        except Exception:
            existing_hash = ""
        # Compute canonical metrics hash and compare
        new_manifest = build_manifest(
            baseline_id=baseline_path.stem,
            source_run_id=raw.get("id", baseline_path.stem),
            report_path=baseline_path,
            metrics=canonical_metrics,
            created_at=raw.get("created_at", ""),
        )
        if new_manifest.get("metrics_hash") != existing_hash:
            write_manifest(new_manifest, baseline_path)
            result["manifest_action"] = "rewritten"
    else:
        # Create manifest from canonical data
        new_manifest = build_manifest(
            baseline_id=baseline_path.stem,
            source_run_id=raw.get("id", baseline_path.stem),
            report_path=baseline_path,
            metrics=canonical_metrics,
            created_at=raw.get("created_at", ""),
        )
        write_manifest(new_manifest, baseline_path)
        result["manifest_action"] = "created"

    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Backfill canonical metrics and manifests for existing baselines."
    )
    parser.add_argument(
        "--baseline-dir",
        default=str(DEFAULT_BASELINE_DIR),
        help=f"Directory containing baseline JSON files. Default: {DEFAULT_BASELINE_DIR}",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report non-canonical baselines without modifying any files.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output path for the backfill report JSON.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    baseline_dir = Path(args.baseline_dir)

    if not baseline_dir.exists():
        print(
            json.dumps(
                {"error": f"Baseline directory not found: {baseline_dir}", "results": []},
                indent=2,
                ensure_ascii=False,
            )
        )
        return 1

    baseline_files = sorted(baseline_dir.glob("*.json"))
    results: list[dict[str, Any]] = []

    for fpath in baseline_files:
        if fpath.name.endswith(".manifest.json") or fpath.name == "baseline_registry.json":
            continue
        result = _backfill_baseline(fpath, dry_run=args.dry_run)
        results.append(result)

    metrics_changed = [r for r in results if r.get("metrics_changed")]
    errors = [r for r in results if "error" in r]

    report = {
        "dry_run": args.dry_run,
        "total_scanned": len(results),
        "metrics_non_canonical": len(metrics_changed),
        "errors": len(errors),
        "results": results,
    }

    print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nReport written to {output_path}", file=sys.stderr)

    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
