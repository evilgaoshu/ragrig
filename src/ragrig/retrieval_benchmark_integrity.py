"""Retrieval benchmark baseline integrity checker.

Evaluates the health of the retrieval benchmark baseline by comparing
manifest metadata against the actual baseline artifact. Produces both
Web Console summaries and CI artifacts.

Never includes raw secret fragments in output.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.retrieval_benchmark_baseline_refresh import _compute_metrics_hash

DEFAULT_MANIFEST_PATH = Path("docs/benchmarks/retrieval-benchmark-baseline.manifest.json")
DEFAULT_BASELINE_PATH = Path("docs/benchmarks/retrieval-benchmark-baseline.json")
DEFAULT_MAX_AGE_DAYS = 30
SUPPORTED_SCHEMA_VERSION = "1.0"

_SECRET_KEY_PARTS = (
    "api_key",
    "access_key",
    "secret",
    "password",
    "token",
    "credential",
    "private_key",
    "dsn",
    "service_account",
    "session_token",
)


def _redact_secrets(obj: Any) -> Any:
    """Recursively redact secret-like values."""
    if isinstance(obj, dict):
        return {
            k: "[redacted]"
            if any(p in k.lower() for p in _SECRET_KEY_PARTS)
            else _redact_secrets(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_secrets(v) for v in obj]
    return obj


def _parse_iso_datetime(value: str) -> datetime | None:
    """Parse ISO 8601 datetime string, return None on failure."""
    try:
        # Handle both with and without Z suffix
        value = value.replace("Z", "+00:00")
        return datetime.fromisoformat(value)
    except (ValueError, TypeError, AttributeError):
        return None


def _compute_baseline_age_days(created_at: str) -> float | None:
    """Return age in days from created_at to now (UTC)."""
    dt = _parse_iso_datetime(created_at)
    if dt is None:
        return None
    now = datetime.now(timezone.utc)
    return (now - dt).total_seconds() / 86400.0


def _check_metrics_hash(baseline_data: dict, expected_hash: str) -> tuple[bool, str]:
    """Recompute metrics hash from baseline and compare with manifest.

    Returns (matches, computed_hash).
    """
    computed = _compute_metrics_hash(baseline_data)
    return computed == expected_hash, computed


def check_integrity(
    *,
    manifest_path: Path | None = None,
    baseline_path: Path | None = None,
    max_age_days: int | None = None,
) -> dict[str, Any]:
    """Check retrieval benchmark baseline integrity.

    Returns a dict with:
    - schema_version
    - baseline_age (days, rounded to 2 decimals)
    - fixture_id
    - iteration_count
    - metrics_hash_status: "match" | "mismatch"
    - overall_status: "pass" | "degraded" | "failure"
    - reasons: list of reason strings for degraded/failure
    - checked_at: ISO timestamp
    - manifest_present: bool
    - baseline_present: bool
    """
    manifest_path = manifest_path or DEFAULT_MANIFEST_PATH
    baseline_path = baseline_path or DEFAULT_BASELINE_PATH
    max_age_days = max_age_days if max_age_days is not None else DEFAULT_MAX_AGE_DAYS

    result: dict[str, Any] = {
        "schema_version": None,
        "baseline_age": None,
        "fixture_id": None,
        "iteration_count": None,
        "metrics_hash_status": None,
        "overall_status": "failure",
        "reasons": [],
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "manifest_present": False,
        "baseline_present": False,
    }

    # Check manifest existence
    if not manifest_path.exists():
        result["reasons"].append("manifest_missing: manifest file not found")
        return _redact_secrets(result)

    result["manifest_present"] = True

    # Parse manifest
    try:
        manifest_text = manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(manifest_text)
    except json.JSONDecodeError as exc:
        result["reasons"].append(f"manifest_corrupt: invalid JSON ({exc})")
        return _redact_secrets(result)
    except OSError as exc:
        result["reasons"].append(f"manifest_corrupt: read error ({exc})")
        return _redact_secrets(result)

    if not isinstance(manifest, dict):
        result["reasons"].append("manifest_corrupt: manifest is not a JSON object")
        return _redact_secrets(result)

    result["schema_version"] = manifest.get("schema_version")
    result["fixture_id"] = manifest.get("fixture_id")
    result["iteration_count"] = manifest.get("iteration_count")

    # Schema version check
    if result["schema_version"] != SUPPORTED_SCHEMA_VERSION:
        result["reasons"].append(
            "schema_incompatible: expected "
            f"{SUPPORTED_SCHEMA_VERSION}, got {result['schema_version']}"
        )
        return _redact_secrets(result)

    # Baseline existence
    if not baseline_path.exists():
        result["reasons"].append("baseline_missing: baseline file not found")
        return _redact_secrets(result)

    result["baseline_present"] = True

    # Parse baseline
    try:
        baseline_text = baseline_path.read_text(encoding="utf-8")
        baseline = json.loads(baseline_text)
    except json.JSONDecodeError as exc:
        result["reasons"].append(f"baseline_corrupt: invalid JSON ({exc})")
        return _redact_secrets(result)
    except OSError as exc:
        result["reasons"].append(f"baseline_corrupt: read error ({exc})")
        return _redact_secrets(result)

    if not isinstance(baseline, dict):
        result["reasons"].append("baseline_corrupt: baseline is not a JSON object")
        return _redact_secrets(result)

    # Age check
    created_at = manifest.get("created_at")
    age_days = _compute_baseline_age_days(created_at) if created_at else None
    result["baseline_age"] = round(age_days, 2) if age_days is not None else None

    if age_days is None:
        result["reasons"].append("baseline_age_invalid: created_at is missing or unparsable")
    elif age_days > max_age_days:
        result["reasons"].append(
            f"baseline_stale: age {round(age_days, 1)} days exceeds threshold {max_age_days} days"
        )

    # Metrics hash check
    expected_hash = manifest.get("metrics_hash")
    if expected_hash is None:
        result["reasons"].append("metrics_hash_missing: metrics_hash not in manifest")
        result["metrics_hash_status"] = "mismatch"
    else:
        matches, computed = _check_metrics_hash(baseline, expected_hash)
        result["metrics_hash_status"] = "match" if matches else "mismatch"
        if not matches:
            result["reasons"].append(
                f"metrics_hash_mismatch: manifest says {expected_hash}, computed {computed}"
            )

    # Determine overall status
    failure_reasons = [
        r
        for r in result["reasons"]
        if r.split(":")[0]
        in {
            "manifest_missing",
            "manifest_corrupt",
            "baseline_missing",
            "baseline_corrupt",
            "schema_incompatible",
        }
    ]
    degraded_reasons = [
        r
        for r in result["reasons"]
        if r.split(":")[0]
        in {
            "baseline_stale",
            "baseline_age_invalid",
            "metrics_hash_mismatch",
            "metrics_hash_missing",
        }
    ]

    if failure_reasons:
        result["overall_status"] = "failure"
    elif degraded_reasons:
        result["overall_status"] = "degraded"
    else:
        result["overall_status"] = "pass"

    return _redact_secrets(result)


def generate_artifact(
    *,
    output_path: Path | None = None,
    manifest_path: Path | None = None,
    baseline_path: Path | None = None,
    max_age_days: int | None = None,
) -> dict[str, Any]:
    """Generate a CI artifact JSON for retrieval benchmark integrity.

    Writes to output_path if provided. Returns the artifact dict.
    """
    result = check_integrity(
        manifest_path=manifest_path,
        baseline_path=baseline_path,
        max_age_days=max_age_days,
    )

    artifact = {
        "artifact": "retrieval-benchmark-integrity",
        "generated_at": result["checked_at"],
        "schema_version": result["schema_version"],
        "baseline_age": result["baseline_age"],
        "fixture_id": result["fixture_id"],
        "iteration_count": result["iteration_count"],
        "metrics_hash_status": result["metrics_hash_status"],
        "overall_status": result["overall_status"],
        "reasons": result["reasons"],
        "manifest_present": result["manifest_present"],
        "baseline_present": result["baseline_present"],
    }

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(artifact, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    return artifact


def get_integrity_summary() -> dict[str, Any]:
    """Return a Web Console-safe summary of retrieval benchmark integrity.

    Never includes raw secret fragments.
    """
    result = check_integrity()

    # Convert to a simpler summary for the console
    summary = {
        "available": result["manifest_present"] and result["baseline_present"],
        "schema_version": result["schema_version"],
        "baseline_age": result["baseline_age"],
        "fixture_id": result["fixture_id"],
        "iteration_count": result["iteration_count"],
        "metrics_hash_status": result["metrics_hash_status"],
        "overall_status": result["overall_status"],
        "reasons": result["reasons"],
        "checked_at": result["checked_at"],
    }

    return summary


def summarize_artifact(
    artifact_path: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Read a JSON integrity artifact and produce a Markdown summary + JSON report."""
    ap = Path(artifact_path)
    if not ap.exists():
        raise FileNotFoundError(f"Artifact not found: {ap}")
    try:
        artifact = json.loads(ap.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Corrupt artifact (invalid JSON): {ap} - {exc}") from exc
    if not isinstance(artifact, dict):
        raise ValueError(f"Artifact root is not a JSON object: {ap}")
    out_dir = Path(output_dir) if output_dir else ap.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / f"{ap.stem}_summary.md"
    json_path = out_dir / f"{ap.stem}_summary.json"
    overall_status = artifact.get("overall_status", "unknown")
    reasons = artifact.get("reasons", [])
    baseline_age = artifact.get("baseline_age")
    baseline_age_str = f"{baseline_age:.1f}d" if baseline_age is not None else "unknown"
    fixture_id = artifact.get("fixture_id", "unknown") or "unknown"
    iteration_count = artifact.get("iteration_count", 0) or 0
    metrics_hash_status = artifact.get("metrics_hash_status", "unchecked") or "unchecked"
    schema_version = artifact.get("schema_version", "unknown") or "unknown"
    generated_at = artifact.get("generated_at", "unknown") or "unknown"
    summary = {
        "overall_status": overall_status,
        "reasons": reasons,
        "baseline_age": baseline_age_str,
        "fixture_id": str(fixture_id),
        "iteration_count": int(iteration_count),
        "metrics_hash_status": metrics_hash_status,
        "schema_version": schema_version,
        "generated_at": generated_at,
        "json_report_path": str(json_path),
        "md_report_path": str(md_path),
    }
    json_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    md_lines = [
        "# Integrity Summary",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| **Overall Status** | {overall_status} |",
        f"| **Fixture ID** | {fixture_id} |",
        f"| **Iteration Count** | {iteration_count} |",
        f"| **Baseline Age** | {baseline_age_str} |",
        f"| **Metrics Hash Status** | {metrics_hash_status} |",
        f"| **Schema Version** | {schema_version} |",
        f"| **Generated At** | {generated_at} |",
    ]
    if reasons:
        md_lines.extend(["", "## Reasons"])
        for r in reasons:
            md_lines.append(f"- {r}")
    md_lines.extend(
        [
            "",
            "## Reports",
            f"- JSON: `{summary['json_report_path']}`",
            f"- Markdown: `{summary['md_report_path']}`",
            "",
        ]
    )
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    return summary


def summary_main() -> int:
    """CLI entry point for Markdown summary generation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate a Markdown integrity summary from an artifact JSON."
    )
    parser.add_argument("artifact_path", help="Path to the integrity artifact JSON")
    parser.add_argument("--output-dir", default=None, help="Output directory for summary files")
    args = parser.parse_args()
    summary = summarize_artifact(args.artifact_path, output_dir=args.output_dir)
    status = summary["overall_status"]
    print(f"Integrity Summary: {status}")
    print(f"  Fixture ID:      {summary['fixture_id']}")
    print(f"  Baseline Age:    {summary['baseline_age']}")
    print(f"  Iteration Count: {summary['iteration_count']}")
    print(f"  Metrics Hash:    {summary['metrics_hash_status']}")
    print(f"  JSON Report:     {summary['json_report_path']}")
    print(f"  MD Report:       {summary['md_report_path']}")
    for r in summary.get("reasons", []):
        print(f"  Reason: {r}")
    return 0 if status != "failure" else 1


def main() -> int:
    """CLI entry point for CI artifact generation or summary delegation."""
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--summary":
        sys.argv.pop(1)
        return summary_main()
    import argparse

    parser = argparse.ArgumentParser(description="Generate retrieval benchmark integrity artifact.")
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Output path for the artifact JSON. "
            "Defaults to docs/operations/artifacts/retrieval-benchmark-integrity.json"
        ),
    )
    parser.add_argument(
        "--manifest",
        default=None,
        help=(
            "Path to manifest JSON. "
            "Defaults to docs/benchmarks/retrieval-benchmark-baseline.manifest.json"
        ),
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="Path to baseline JSON. Defaults to docs/benchmarks/retrieval-benchmark-baseline.json",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=None,
        help="Max age in days. Defaults to env BENCHMARK_BASELINE_MAX_AGE_DAYS or 30",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON to stdout.",
    )
    args = parser.parse_args()

    output_path_str = (
        args.output
        or os.environ.get("BENCHMARK_INTEGRITY_ARTIFACT_PATH")
        or "docs/operations/artifacts/retrieval-benchmark-integrity.json"
    )
    output_path = Path(output_path_str)

    manifest_path = Path(args.manifest) if args.manifest else None
    baseline_path = Path(args.baseline) if args.baseline else None

    max_age = args.max_age_days
    if max_age is None:
        env_age = os.environ.get("BENCHMARK_BASELINE_MAX_AGE_DAYS")
        if env_age is not None:
            try:
                max_age = int(env_age)
            except ValueError:
                max_age = DEFAULT_MAX_AGE_DAYS
        else:
            max_age = DEFAULT_MAX_AGE_DAYS

    artifact = generate_artifact(
        output_path=output_path,
        manifest_path=manifest_path,
        baseline_path=baseline_path,
        max_age_days=max_age,
    )

    indent = 2 if args.pretty else None
    print(json.dumps(artifact, indent=indent, ensure_ascii=False, sort_keys=True))
    print(f"\nArtifact written to {output_path}", file=__import__("sys").stderr)

    # Exit with non-zero on failure so CI can optionally fail
    return 0 if artifact["overall_status"] != "failure" else 1


if __name__ == "__main__":
    raise SystemExit(main())
