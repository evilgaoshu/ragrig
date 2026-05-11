"""Compare two Understanding Runs export JSON files and produce a drift/delta report.

Usage::

    python -m scripts.understanding_export_diff \
        --baseline <baseline-export.json> \
        --current  <current-export.json> \
        --output   <diff-report.json>

Produces a structured JSON report containing:
- schema_version, current/baseline run_count
- added/removed/changed run ids
- status (pass / degraded / failure)
- drift reasons
- sanitized_field_count

Security: the report never includes full prompts, original text, secrets,
or secret-like values.  A pre-write audit panics if forbidden fragments
are detected.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.verify_understanding_export import (
    FORBIDDEN_KEYS,
    SECRET_PATTERNS,
    verify_file,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "operations" / "artifacts" / "understanding-export-diff.json"

ARTIFACT_VERSION = "1.0.0"

# ── Fields that must never appear in diff output ────────────────────────────
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

# Fields compared per run for drift detection
_RUN_DIFF_FIELDS: tuple[str, ...] = (
    "provider",
    "model",
    "profile_id",
    "trigger_source",
    "operator",
    "status",
    "total",
    "created",
    "skipped",
    "failed",
    "started_at",
    "finished_at",
)


class DiffError(Exception):
    """Raised when the diff operation encounters an unrecoverable error."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _assert_no_raw_secrets(data: object, source: str = "diff") -> None:
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


def _scan_output_sanitization(data: object, path: str = "$") -> int:
    """Recursively scan output data for forbidden keys or secret-like values.

    Returns the count of sanitized/redacted fields found.
    """
    count = 0
    if isinstance(data, dict):
        for key, value in data.items():
            key_lower = key.lower()
            subpath = f"{path}.{key}"
            if key_lower in FORBIDDEN_KEYS:
                count += 1
                continue
            for pattern in SECRET_PATTERNS:
                if pattern in key_lower:
                    if isinstance(value, (str, int, float)) and value:
                        count += 1
                        break
            if isinstance(value, str):
                val_lower = value.lower()
                for pattern in SECRET_PATTERNS:
                    if pattern in val_lower and len(value) > 3:
                        count += 1
                        break
            count += _scan_output_sanitization(value, subpath)
    elif isinstance(data, list):
        for i, item in enumerate(data):
            count += _scan_output_sanitization(item, f"{path}[{i}]")
    return count


def _load_export(path: Path, label: str = "current") -> dict[str, Any]:
    """Load and validate an understanding export file.

    Raises DiffError on missing, corrupt, or schema-incompatible files.
    """
    result = verify_file(path)
    if result["status"] == "error":
        raise DiffError(
            code=f"{label}_{result['error']}",
            message=result["message"],
        )
    if result["status"] == "fail":
        raise DiffError(
            code="verification_failed",
            message=result["message"],
        )
    # Re-load the raw data for diffing
    # (verify_file already confirmed it's valid JSON)
    data = json.loads(path.read_text(encoding="utf-8"))
    return data  # type: ignore[return-value]


def _run_map(export: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build a dict mapping run_id → run record."""
    runs = export.get("runs", [])
    if not isinstance(runs, list):
        raise DiffError(code="invalid_runs", message="'runs' must be a list")
    result: dict[str, dict[str, Any]] = {}
    for run in runs:
        if not isinstance(run, dict):
            raise DiffError(code="invalid_run", message="Each run must be an object")
        rid = run.get("id")
        if not rid:
            raise DiffError(code="invalid_run_id", message="Run missing 'id' field")
        result[rid] = run
    return result


def _compute_run_diff(
    baseline_run: dict[str, Any] | None,
    current_run: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Compute the diff for a single run between baseline and current.

    Returns None if there is no change (and the run exists in both).
    """
    if baseline_run is None and current_run is None:
        return None

    if baseline_run is None:
        return {
            "run_id": current_run["id"],
            "change_type": "added",
            "baseline": None,
            "current": {
                "provider": current_run.get("provider"),
                "model": current_run.get("model"),
                "profile_id": current_run.get("profile_id"),
                "trigger_source": current_run.get("trigger_source"),
                "operator": current_run.get("operator"),
                "status": current_run.get("status"),
                "total": current_run.get("total"),
                "created": current_run.get("created"),
                "skipped": current_run.get("skipped"),
                "failed": current_run.get("failed"),
                "error_summary_present": current_run.get("error_summary") is not None,
                "started_at": current_run.get("started_at"),
                "finished_at": current_run.get("finished_at"),
            },
        }

    if current_run is None:
        return {
            "run_id": baseline_run["id"],
            "change_type": "removed",
            "baseline": {
                "provider": baseline_run.get("provider"),
                "model": baseline_run.get("model"),
                "profile_id": baseline_run.get("profile_id"),
                "trigger_source": baseline_run.get("trigger_source"),
                "operator": baseline_run.get("operator"),
                "status": baseline_run.get("status"),
                "total": baseline_run.get("total"),
                "created": baseline_run.get("created"),
                "skipped": baseline_run.get("skipped"),
                "failed": baseline_run.get("failed"),
                "error_summary_present": baseline_run.get("error_summary") is not None,
                "started_at": baseline_run.get("started_at"),
                "finished_at": baseline_run.get("finished_at"),
            },
            "current": None,
        }

    # Both exist — check for changes
    changes: list[dict[str, Any]] = []
    for field in _RUN_DIFF_FIELDS:
        base_val = baseline_run.get(field)
        cur_val = current_run.get(field)
        if base_val != cur_val:
            changes.append(
                {
                    "field": field,
                    "baseline": base_val,
                    "current": cur_val,
                }
            )

    # error_summary presence/absence is also a drift signal
    base_err = baseline_run.get("error_summary") is not None
    cur_err = current_run.get("error_summary") is not None
    if base_err != cur_err:
        changes.append(
            {
                "field": "error_summary_present",
                "baseline": base_err,
                "current": cur_err,
            }
        )

    if not changes:
        return None

    return {
        "run_id": baseline_run["id"],
        "change_type": "changed",
        "baseline": {
            "provider": baseline_run.get("provider"),
            "model": baseline_run.get("model"),
            "profile_id": baseline_run.get("profile_id"),
            "trigger_source": baseline_run.get("trigger_source"),
            "operator": baseline_run.get("operator"),
            "status": baseline_run.get("status"),
            "total": baseline_run.get("total"),
            "created": baseline_run.get("created"),
            "skipped": baseline_run.get("skipped"),
            "failed": baseline_run.get("failed"),
            "error_summary_present": base_err,
            "started_at": baseline_run.get("started_at"),
            "finished_at": baseline_run.get("finished_at"),
        },
        "current": {
            "provider": current_run.get("provider"),
            "model": current_run.get("model"),
            "profile_id": current_run.get("profile_id"),
            "trigger_source": current_run.get("trigger_source"),
            "operator": current_run.get("operator"),
            "status": current_run.get("status"),
            "total": current_run.get("total"),
            "created": current_run.get("created"),
            "skipped": current_run.get("skipped"),
            "failed": current_run.get("failed"),
            "error_summary_present": cur_err,
            "started_at": current_run.get("started_at"),
            "finished_at": current_run.get("finished_at"),
        },
        "changes": changes,
    }


def compute_export_diff(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    """Compare baseline and current understanding exports and return a drift report.

    The report includes:
    - schema_version compatibility check
    - added, removed, changed runs
    - status (pass / degraded / failure)
    - drift reasons
    - sanitized_field_count
    """
    # Schema version compatibility
    baseline_schema = baseline.get("schema_version")
    current_schema = current.get("schema_version")
    schema_compatible = baseline_schema == current_schema

    baseline_runs = _run_map(baseline)
    current_runs = _run_map(current)

    all_ids = sorted(set(baseline_runs) | set(current_runs))

    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []

    for rid in all_ids:
        diff = _compute_run_diff(baseline_runs.get(rid), current_runs.get(rid))
        if diff is None:
            continue
        if diff["change_type"] == "added":
            added.append(diff)
        elif diff["change_type"] == "removed":
            removed.append(diff)
        else:
            changed.append(diff)

    # Build drift reasons
    drift_reasons: list[dict[str, Any]] = []

    if not schema_compatible:
        drift_reasons.append(
            {
                "type": "schema_incompatible",
                "baseline_schema": baseline_schema,
                "current_schema": current_schema,
            }
        )

    if added:
        drift_reasons.append(
            {
                "type": "runs_added",
                "count": len(added),
                "run_ids": [a["run_id"] for a in added],
            }
        )

    if removed:
        drift_reasons.append(
            {
                "type": "runs_removed",
                "count": len(removed),
                "run_ids": [r["run_id"] for r in removed],
            }
        )

    if changed:
        for ch in changed:
            drift_reasons.append(
                {
                    "type": "run_changed",
                    "run_id": ch["run_id"],
                    "fields_changed": [c["field"] for c in ch.get("changes", [])],
                }
            )

    # Determine status
    has_error = not schema_compatible
    has_drift = bool(added or removed or changed)

    if has_error:
        status = "failure"
    elif has_drift:
        status = "degraded"
    else:
        status = "pass"

    # Compute sanitized field count for the report itself
    report: dict[str, Any] = {
        "artifact": "understanding-export-diff",
        "version": ARTIFACT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": current_schema if current_schema else "unknown",
        "schema_compatible": schema_compatible,
        "baseline": {
            "run_count": len(baseline_runs),
            "schema_version": baseline_schema,
        },
        "current": {
            "run_count": len(current_runs),
            "schema_version": current_schema,
        },
        "runs": {
            "added": [a["run_id"] for a in added],
            "removed": [r["run_id"] for r in removed],
            "changed": [c["run_id"] for c in changed],
        },
        "run_details": {
            "added": added,
            "removed": removed,
            "changed": changed,
        },
        "status": status,
        "drift_reasons": drift_reasons,
        "sanitized_field_count": 0,
    }

    # Audit for secrets in the output
    _assert_no_raw_secrets(report, "understanding-export-diff")
    report["sanitized_field_count"] = _scan_output_sanitization(report)

    return report


def _render_markdown(report: dict[str, Any]) -> str:
    """Render the drift report as a Markdown report."""
    lines: list[str] = []
    lines.append("## Understanding Export Baseline Diff")
    lines.append("")
    lines.append(f"- **Schema version**: `{report['schema_version']}`")
    lines.append(f"- **Schema compatible**: {'yes' if report['schema_compatible'] else 'no'}")
    lines.append("")

    baseline = report["baseline"]
    current = report["current"]
    lines.append("### Run Counts")
    lines.append("")
    lines.append("| Source | Run Count | Schema Version |")
    lines.append("|--------|-----------|----------------|")
    b_ver = baseline["schema_version"] or "unknown"
    c_ver = current["schema_version"] or "unknown"
    lines.append(f"| Baseline | {baseline['run_count']} | {b_ver} |")
    lines.append(f"| Current | {current['run_count']} | {c_ver} |")
    lines.append("")

    status = report["status"]
    emoji = "✅" if status == "pass" else "⚠️" if status == "degraded" else "❌"
    lines.append(f"### Status: {emoji} `{status}`")
    lines.append("")

    runs = report["runs"]
    if runs["added"]:
        lines.append(f"- 🆕 Added runs: {len(runs['added'])}")
        for rid in runs["added"]:
            lines.append(f"  - `{rid}`")
    if runs["removed"]:
        lines.append(f"- 🗑️ Removed runs: {len(runs['removed'])}")
        for rid in runs["removed"]:
            lines.append(f"  - `{rid}`")
    if runs["changed"]:
        lines.append(f"- 📝 Changed runs: {len(runs['changed'])}")
        for rid in runs["changed"]:
            lines.append(f"  - `{rid}`")
    if not any(runs.values()):
        lines.append("- No run changes detected.")
    lines.append("")

    drift_reasons = report["drift_reasons"]
    if drift_reasons:
        lines.append("### Drift Reasons")
        lines.append("")
        for reason in drift_reasons:
            rtype = reason["type"]
            if rtype == "schema_incompatible":
                lines.append(
                    f"- ❌ Schema incompatible: baseline={reason['baseline_schema']}, "
                    f"current={reason['current_schema']}"
                )
            elif rtype == "runs_added":
                lines.append(f"- 🆕 {reason['count']} run(s) added")
            elif rtype == "runs_removed":
                lines.append(f"- 🗑️ {reason['count']} run(s) removed")
            elif rtype == "run_changed":
                fields = ", ".join(reason["fields_changed"])
                lines.append(f"- 📝 Run `{reason['run_id']}` changed fields: {fields}")
            else:
                lines.append(f"- {rtype}: {reason}")
        lines.append("")

    lines.append(f"- **Sanitized field count**: {report['sanitized_field_count']}")
    lines.append("")
    lines.append("---")
    lines.append("*Generated by understanding-export-diff. No raw secrets are included.*")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare two Understanding Runs export files and produce a drift report."
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        required=True,
        help="Path to baseline understanding export JSON",
    )
    parser.add_argument(
        "--current",
        type=Path,
        required=True,
        help="Path to current understanding export JSON",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output JSON path for the diff report",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=None,
        help="Optional output path for the Markdown report",
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown", "both"),
        default="both",
        help="Output format (default: both)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Also print the Markdown report to stdout",
    )
    args = parser.parse_args(argv)

    try:
        baseline_data = _load_export(args.baseline, label="baseline")
        current_data = _load_export(args.current, label="current")
    except DiffError as exc:
        print(f"Error: {exc.message}", file=sys.stderr)
        # Write a failure report
        failure_report: dict[str, Any] = {
            "artifact": "understanding-export-diff",
            "version": ARTIFACT_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "schema_version": "unknown",
            "schema_compatible": False,
            "baseline": {"run_count": 0, "schema_version": None},
            "current": {"run_count": 0, "schema_version": None},
            "runs": {"added": [], "removed": [], "changed": []},
            "run_details": {"added": [], "removed": [], "changed": []},
            "status": "failure",
            "drift_reasons": [
                {
                    "type": (
                        "baseline_load_error"
                        if exc.code.startswith("baseline_")
                        else "current_load_error"
                    ),
                    "error_code": exc.code,
                    "message": exc.message,
                }
            ],
            "sanitized_field_count": 0,
        }
        _assert_no_raw_secrets(failure_report, "understanding-export-diff")
        failure_report["sanitized_field_count"] = _scan_output_sanitization(failure_report)

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(failure_report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Failure report written to {args.output}")
        return 1

    report = compute_export_diff(baseline_data, current_data)
    markdown = _render_markdown(report)

    # Write JSON artifact
    if args.format in ("json", "both"):
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Diff report JSON written to {args.output}")

    # Write Markdown report
    if args.format in ("markdown", "both"):
        md_path = args.markdown_output or args.output.with_suffix(".md")
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(markdown, encoding="utf-8")
        print(f"Diff report Markdown written to {md_path}")

    if args.stdout:
        print("\n" + markdown)

    if report["status"] == "failure":
        return 1
    if report["status"] == "degraded":
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
