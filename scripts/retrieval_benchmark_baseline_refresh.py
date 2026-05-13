"""Retrieval benchmark baseline refresh CLI.

Generates a versioned baseline with an embedded manifest from offline
fixture data.  No network, GPU, torch, or BGE dependency.

Usage:
    make retrieval-benchmark-baseline-refresh
    uv run python -m scripts.retrieval_benchmark_baseline_refresh
    uv run python -m scripts.retrieval_benchmark_baseline_refresh \
        --output docs/benchmarks/retrieval-benchmark-baseline.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
from pathlib import Path

from scripts.retrieval_benchmark import (
    DEFAULT_CANDIDATE_K,
    DEFAULT_ITERATIONS,
    DEFAULT_TOP_K,
    FIXTURE_ROOT,
    _sanitize_summary,
    run_benchmarks,
)

DEFAULT_BASELINE_PATH = Path("docs/benchmarks/retrieval-benchmark-baseline.json")
DEFAULT_MANIFEST_PATH = Path("docs/benchmarks/retrieval-benchmark-baseline.manifest.json")
SCHEMA_VERSION = "1.0"


def _iter_fixture_files(fixture_root: Path) -> list[Path]:
    """Return fixture files in deterministic order for identity hashing."""
    return sorted(path for path in fixture_root.rglob("*") if path.is_file())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Refresh the retrieval benchmark baseline from fixture data."
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Path for the baseline JSON. Defaults to env "
            "BENCHMARK_BASELINE_PATH, then docs/benchmarks/"
            "retrieval-benchmark-baseline.json"
        ),
    )
    parser.add_argument(
        "--manifest-output",
        default=None,
        help=("Path for the manifest JSON. Defaults to <baseline-path>.manifest.json"),
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
        help=f"Iterations per query. Default: {DEFAULT_ITERATIONS}",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help=f"top_k parameter. Default: {DEFAULT_TOP_K}",
    )
    parser.add_argument(
        "--candidate-k",
        type=int,
        default=DEFAULT_CANDIDATE_K,
        help=f"candidate_k parameter. Default: {DEFAULT_CANDIDATE_K}",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON to stdout.",
    )
    return parser


def _compute_fixture_id(fixture_root: Path) -> str:
    """Compute a stable fixture identifier from fixture file names and bytes."""
    if not fixture_root.exists():
        return hashlib.sha256(b"missing-fixture-root").hexdigest()[:16]

    hasher = hashlib.sha256()
    hasher.update(b"fixture-v2")

    for fixture_file in _iter_fixture_files(fixture_root):
        rel = fixture_file.relative_to(fixture_root).as_posix()
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(hashlib.sha256(fixture_file.read_bytes()).digest())

    return hasher.hexdigest()[:16]


def _compute_metrics_hash(benchmark_data: dict) -> str:
    """Compute a hash of the metrics structure (ignoring volatile latency values)."""
    modes = benchmark_data.get("modes", [])
    canonical = []
    for mode in sorted(modes, key=lambda m: m.get("mode", "")):
        canonical.append(
            {
                "mode": mode.get("mode"),
                "top_k": mode.get("top_k"),
                "candidate_k": mode.get("candidate_k"),
                "iterations": mode.get("iterations"),
                "result_count": mode.get("result_count"),
                "degraded": mode.get("degraded"),
                "degraded_reason": mode.get("degraded_reason", ""),
            }
        )

    payload = json.dumps(canonical, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _get_generator_version() -> str:
    """Return the generator version (project version)."""
    try:
        import importlib.metadata

        return importlib.metadata.version("ragrig")
    except Exception:
        return "0.1.0"


def build_manifest(benchmark_data: dict, *, fixture_root: Path | None = None) -> dict:
    """Build the manifest dict from benchmark data."""
    fixture_root = fixture_root or FIXTURE_ROOT
    modes = benchmark_data.get("modes", [])
    mode_names = sorted([m.get("mode", "") for m in modes if isinstance(m, dict)])

    return {
        "schema_version": SCHEMA_VERSION,
        "baseline_id": str(uuid.uuid4()),
        "fixture_id": _compute_fixture_id(fixture_root),
        "iteration_count": benchmark_data.get("iterations_per_query", DEFAULT_ITERATIONS),
        "modes": mode_names,
        "metrics_hash": _compute_metrics_hash(benchmark_data),
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "generator_version": _get_generator_version(),
    }


def refresh_baseline(
    *,
    iterations: int = DEFAULT_ITERATIONS,
    top_k: int = DEFAULT_TOP_K,
    candidate_k: int = DEFAULT_CANDIDATE_K,
    fixture_root: Path | None = None,
) -> dict:
    """Run benchmarks and return a baseline dict with embedded manifest."""
    fixture_root = fixture_root or FIXTURE_ROOT

    if not fixture_root.exists():
        raise FileNotFoundError(f"Fixture directory not found: {fixture_root}")

    benchmark_data = run_benchmarks(
        iterations=iterations,
        top_k=top_k,
        candidate_k=candidate_k,
    )

    manifest = build_manifest(benchmark_data, fixture_root=fixture_root)
    baseline = dict(benchmark_data)
    baseline["_manifest"] = manifest

    return baseline


def main() -> int:
    args = build_parser().parse_args()

    baseline_path_str = (
        args.output
        or __import__("os").environ.get("BENCHMARK_BASELINE_PATH")
        or str(DEFAULT_BASELINE_PATH)
    )
    baseline_path = Path(baseline_path_str)

    manifest_path_str = args.manifest_output or str(baseline_path.with_suffix(".manifest.json"))
    manifest_path = Path(manifest_path_str)

    fixture_root = FIXTURE_ROOT
    if not fixture_root.exists():
        error_report = {
            "error": f"Fixture directory not found: {fixture_root}",
            "hint": (
                "Run from the repo root; the fixture directory is tests/fixtures/local_ingestion"
            ),
        }
        print(json.dumps(error_report), file=sys.stderr)
        return 1

    try:
        baseline = refresh_baseline(
            iterations=args.iterations,
            top_k=args.top_k,
            candidate_k=args.candidate_k,
            fixture_root=fixture_root,
        )
    except Exception as exc:
        error_report = {"error": f"Failed to refresh baseline: {exc}"}
        print(json.dumps(error_report), file=sys.stderr)
        return 1

    baseline = _sanitize_summary(baseline)

    indent = 2 if args.pretty else None
    baseline_json = json.dumps(baseline, indent=indent, ensure_ascii=False, sort_keys=True)
    manifest_json = json.dumps(
        baseline["_manifest"], indent=indent, ensure_ascii=False, sort_keys=True
    )

    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(baseline_json, encoding="utf-8")

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(manifest_json, encoding="utf-8")

    print(baseline_json)
    print(f"\nBaseline written to {baseline_path}", file=sys.stderr)
    print(f"Manifest written to {manifest_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
