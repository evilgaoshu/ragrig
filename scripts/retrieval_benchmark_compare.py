"""Retrieval benchmark baseline comparison CLI.

Compares a current benchmark run against a stored baseline and produces
a structured JSON regression report.

Usage:
    make retrieval-benchmark-compare
    uv run python -m scripts.retrieval_benchmark_compare --current benchmark.json
    BENCHMARK_BASELINE_PATH=/path/to/baseline.json \\
        uv run python -m scripts.retrieval_benchmark_compare
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from scripts.retrieval_benchmark import (
    DEFAULT_CANDIDATE_K,
    DEFAULT_ITERATIONS,
    DEFAULT_TOP_K,
    _sanitize_summary,
    run_benchmarks,
)
from scripts.retrieval_benchmark_baseline_refresh import (
    SCHEMA_VERSION,
    _compute_fixture_id,
    _compute_metrics_hash,
)

DEFAULT_BASELINE_PATH = Path("docs/benchmarks/retrieval-benchmark-baseline.json")
DEFAULT_LATENCY_THRESHOLD_PCT = 20
DEFAULT_RESULT_COUNT_THRESHOLD = 5


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare current retrieval benchmark against a baseline."
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help=(
            "Path to baseline JSON. Defaults to env BENCHMARK_BASELINE_PATH, "
            "then docs/benchmarks/retrieval-benchmark-baseline.json"
        ),
    )
    parser.add_argument(
        "--current",
        default=None,
        help=(
            "Path to current benchmark JSON. If omitted, a fresh benchmark is run "
            "via fixture data (deterministic, no network/GPU)."
        ),
    )
    parser.add_argument(
        "--latency-threshold-pct",
        type=float,
        default=None,
        help=(
            "Latency regression threshold in percent. "
            "Defaults to env BENCHMARK_LATENCY_THRESHOLD_PCT, then 20."
        ),
    )
    parser.add_argument(
        "--result-count-threshold",
        type=int,
        default=None,
        help=(
            "Result count drift threshold (absolute). "
            "Defaults to env BENCHMARK_RESULT_COUNT_THRESHOLD, then 5."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output path for the compare JSON report.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON to stdout.",
    )
    return parser


def _load_baseline(path: Path) -> tuple[dict | None, str]:
    """Load baseline JSON from *path*.

    Returns (baseline_dict, error_reason).  On success error_reason is "".
    """
    if not path.exists():
        return None, f"Baseline file not found: {path}"

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"Baseline file contains invalid JSON: {exc}"

    if not isinstance(data, dict):
        return None, "Baseline file root must be a JSON object"

    return data, ""


def _load_current(path: Path | None) -> tuple[dict | None, str]:
    """Load current benchmark JSON from *path*, or return None with error."""
    if path is None:
        return None, ""

    if not path.exists():
        return None, f"Current benchmark file not found: {path}"

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"Current benchmark file contains invalid JSON: {exc}"

    if not isinstance(data, dict):
        return None, "Current benchmark file root must be a JSON object"

    return data, ""


def _latency_delta_pct(current: float, baseline: float) -> float:
    """Compute latency delta as a percentage relative to baseline."""
    if baseline == 0:
        return 0.0 if current == 0 else float("inf")
    return round(((current - baseline) / baseline) * 100, 3)


def _compare_mode(
    current_mode: dict,
    baseline_mode: dict,
    latency_threshold_pct: float,
    result_count_threshold: int,
) -> dict:
    """Compare a single mode and return the comparison record."""
    mode = current_mode.get("mode", "unknown")

    current_p50 = current_mode.get("p50_latency_ms", 0.0)
    current_p95 = current_mode.get("p95_latency_ms", 0.0)
    baseline_p50 = baseline_mode.get("p50_latency_ms", 0.0)
    baseline_p95 = baseline_mode.get("p95_latency_ms", 0.0)

    p50_delta = _latency_delta_pct(current_p50, baseline_p50)
    p95_delta = _latency_delta_pct(current_p95, baseline_p95)

    current_rc = current_mode.get("result_count", 0)
    baseline_rc = baseline_mode.get("result_count", 0)
    result_count_delta = current_rc - baseline_rc

    # Determine status
    reasons: list[str] = []

    # Check benchmark-level degradation first
    if current_mode.get("degraded"):
        dr = current_mode.get("degraded_reason", "")
        reasons.append(f"degraded: {dr}" if dr else "degraded")

    # Latency regression checks
    if p50_delta > latency_threshold_pct:
        reasons.append(
            f"p50 latency regression {p50_delta:.1f}% > threshold {latency_threshold_pct}%"
        )
    if p95_delta > latency_threshold_pct:
        reasons.append(
            f"p95 latency regression {p95_delta:.1f}% > threshold {latency_threshold_pct}%"
        )

    # Result count drift check
    if abs(result_count_delta) > result_count_threshold:
        reasons.append(
            f"result_count delta {result_count_delta} exceeds threshold ±{result_count_threshold}"
        )

    if reasons:
        # If there are threshold failures, status is fail.
        # If only degraded (no threshold failures), status is degraded.
        has_threshold_failures = any(
            r.startswith(("p50 latency regression", "p95 latency regression", "result_count delta"))
            for r in reasons
        )
        if has_threshold_failures:
            status = "fail"
        else:
            status = "degraded"
    else:
        status = "pass"

    return {
        "mode": mode,
        "current": {
            "p50_latency_ms": current_p50,
            "p95_latency_ms": current_p95,
        },
        "baseline": {
            "p50_latency_ms": baseline_p50,
            "p95_latency_ms": baseline_p95,
        },
        "delta": {
            "p50_latency_ms": p50_delta,
            "p95_latency_ms": p95_delta,
        },
        "result_count_delta": result_count_delta,
        "status": status,
        "reason": "; ".join(reasons) if reasons else "",
    }


def _check_manifest_compatibility(baseline: dict, current: dict) -> tuple[bool, str]:
    """Check baseline manifest against current benchmark for compatibility.

    Returns (compatible, reason).  If compatible, reason is "".
    """
    manifest = baseline.get("_manifest")
    if not manifest:
        return False, "baseline missing _manifest: run baseline refresh first"

    if not isinstance(manifest, dict):
        return False, "baseline _manifest is not a dict"

    # schema_version
    baseline_schema = manifest.get("schema_version")
    if baseline_schema != SCHEMA_VERSION:
        return (
            False,
            f"schema_version mismatch: baseline {baseline_schema!r} != expected {SCHEMA_VERSION!r}",
        )

    # fixture_id
    baseline_fixture_id = manifest.get("fixture_id")
    current_fixture_id = current.get("_manifest", {}).get("fixture_id")
    if current_fixture_id is None:
        from scripts.retrieval_benchmark import FIXTURE_ROOT

        current_fixture_id = _compute_fixture_id(FIXTURE_ROOT)
    if baseline_fixture_id != current_fixture_id:
        return (
            False,
            (
                f"fixture_id mismatch: baseline {baseline_fixture_id!r}"
                f" != current {current_fixture_id!r}"
            ),
        )

    # iteration_count
    baseline_iters = manifest.get("iteration_count")
    current_iters = current.get("_manifest", {}).get("iteration_count")
    if current_iters is None:
        current_iters = current.get("iterations_per_query")
    if baseline_iters is not None and current_iters is not None and baseline_iters != current_iters:
        return (
            False,
            f"iteration_count mismatch: baseline {baseline_iters} != current {current_iters}",
        )

    # metrics_hash
    baseline_hash = manifest.get("metrics_hash")
    current_hash = current.get("_manifest", {}).get("metrics_hash")
    if current_hash is None:
        current_hash = _compute_metrics_hash(current)
    if baseline_hash is not None and baseline_hash != current_hash:
        return (
            False,
            f"metrics_hash mismatch: baseline {baseline_hash!r} != current {current_hash!r}"
            " (metrics structure changed)",
        )

    return True, ""


def compare_benchmarks(
    baseline: dict,
    current: dict,
    *,
    latency_threshold_pct: float = DEFAULT_LATENCY_THRESHOLD_PCT,
    result_count_threshold: int = DEFAULT_RESULT_COUNT_THRESHOLD,
) -> dict:
    """Compare *current* benchmark against *baseline* and return a report dict."""
    baseline_modes = {m["mode"]: m for m in baseline.get("modes", []) if isinstance(m, dict)}
    current_modes = {m["mode"]: m for m in current.get("modes", []) if isinstance(m, dict)}

    all_modes = sorted(set(baseline_modes) | set(current_modes))
    comparisons: list[dict] = []
    overall_status = "pass"
    overall_reasons: list[str] = []

    for mode in all_modes:
        if mode not in baseline_modes:
            comparisons.append(
                {
                    "mode": mode,
                    "current": {"p50_latency_ms": 0.0, "p95_latency_ms": 0.0},
                    "baseline": {"p50_latency_ms": 0.0, "p95_latency_ms": 0.0},
                    "delta": {"p50_latency_ms": 0.0, "p95_latency_ms": 0.0},
                    "result_count_delta": 0,
                    "status": "fail",
                    "reason": f"mode '{mode}' missing from baseline",
                }
            )
            overall_status = "fail"
            overall_reasons.append(f"mode '{mode}' missing from baseline")
            continue

        if mode not in current_modes:
            comparisons.append(
                {
                    "mode": mode,
                    "current": {"p50_latency_ms": 0.0, "p95_latency_ms": 0.0},
                    "baseline": {"p50_latency_ms": 0.0, "p95_latency_ms": 0.0},
                    "delta": {"p50_latency_ms": 0.0, "p95_latency_ms": 0.0},
                    "result_count_delta": 0,
                    "status": "fail",
                    "reason": f"mode '{mode}' missing from current run",
                }
            )
            overall_status = "fail"
            overall_reasons.append(f"mode '{mode}' missing from current run")
            continue

        comp = _compare_mode(
            current_modes[mode],
            baseline_modes[mode],
            latency_threshold_pct,
            result_count_threshold,
        )
        comparisons.append(comp)

        if comp["status"] == "fail":
            overall_status = "fail"
            overall_reasons.append(f"{mode}: {comp['reason']}")
        elif comp["status"] == "degraded" and overall_status == "pass":
            overall_status = "degraded"
            overall_reasons.append(f"{mode}: {comp['reason']}")

    report = {
        "knowledge_base": current.get("knowledge_base", baseline.get("knowledge_base", "")),
        "baseline_path": str(baseline.get("_path", "")),
        "latency_threshold_pct": latency_threshold_pct,
        "result_count_threshold": result_count_threshold,
        "overall_status": overall_status,
        "overall_reason": "; ".join(overall_reasons) if overall_reasons else "",
        "modes": comparisons,
    }

    return report


def main() -> int:
    args = build_parser().parse_args()

    # Resolve baseline path
    baseline_path_str = (
        args.baseline or os.environ.get("BENCHMARK_BASELINE_PATH") or str(DEFAULT_BASELINE_PATH)
    )
    baseline_path = Path(baseline_path_str)

    baseline, baseline_err = _load_baseline(baseline_path)
    if baseline_err:
        report = {
            "knowledge_base": "",
            "baseline_path": str(baseline_path),
            "latency_threshold_pct": 0.0,
            "result_count_threshold": 0,
            "overall_status": "failure",
            "overall_reason": baseline_err,
            "modes": [],
        }
        report = _sanitize_summary(report)
        indent = 2 if args.pretty else None
        print(json.dumps(report, indent=indent, ensure_ascii=False, sort_keys=True))
        return 1

    baseline["_path"] = str(baseline_path)

    # Resolve thresholds
    latency_threshold_pct = (
        args.latency_threshold_pct
        if args.latency_threshold_pct is not None
        else float(os.environ.get("BENCHMARK_LATENCY_THRESHOLD_PCT", DEFAULT_LATENCY_THRESHOLD_PCT))
    )
    result_count_threshold = (
        args.result_count_threshold
        if args.result_count_threshold is not None
        else int(os.environ.get("BENCHMARK_RESULT_COUNT_THRESHOLD", DEFAULT_RESULT_COUNT_THRESHOLD))
    )

    # Resolve current benchmark
    if args.current:
        current_path = Path(args.current)
        current, current_err = _load_current(current_path)
        if current_err:
            report = {
                "knowledge_base": "",
                "baseline_path": str(baseline_path),
                "latency_threshold_pct": latency_threshold_pct,
                "result_count_threshold": result_count_threshold,
                "overall_status": "failure",
                "overall_reason": current_err,
                "modes": [],
            }
            report = _sanitize_summary(report)
            indent = 2 if args.pretty else None
            print(json.dumps(report, indent=indent, ensure_ascii=False, sort_keys=True))
            return 1
    else:
        current = run_benchmarks(
            iterations=DEFAULT_ITERATIONS,
            top_k=DEFAULT_TOP_K,
            candidate_k=DEFAULT_CANDIDATE_K,
        )

    # Manifest compatibility check
    compatible, compat_reason = _check_manifest_compatibility(baseline, current)
    if not compatible:
        report = {
            "knowledge_base": current.get("knowledge_base", baseline.get("knowledge_base", "")),
            "baseline_path": str(baseline_path),
            "latency_threshold_pct": latency_threshold_pct,
            "result_count_threshold": result_count_threshold,
            "overall_status": "failure",
            "overall_reason": compat_reason,
            "modes": [],
        }
        report = _sanitize_summary(report)
        indent = 2 if args.pretty else None
        print(json.dumps(report, indent=indent, ensure_ascii=False, sort_keys=True))
        return 1

    report = compare_benchmarks(
        baseline,
        current,
        latency_threshold_pct=latency_threshold_pct,
        result_count_threshold=result_count_threshold,
    )
    report["baseline_path"] = str(baseline_path)
    report = _sanitize_summary(report)

    indent = 2 if args.pretty else None
    json_output = json.dumps(report, indent=indent, ensure_ascii=False, sort_keys=True)
    print(json_output)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json_output, encoding="utf-8")
        print(f"\nCompare report written to {output_path}", file=sys.stderr)

    return 0 if report["overall_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
