"""Read multiple sanitizer drift diff artifacts and produce a historical trend report.

Usage::

    python -m scripts.sanitizer_drift_history \
        [--artifacts-dir <dir>] \
        [--output <path>] \
        [--markdown-output <path>] \
        [--stdout]

Reads all sanitizer-drift-diff*.json files under the artifacts directory,
sorts them by generated_at, and produces:
- A structured history artifact (JSON) with trend analysis.
- A Markdown report suitable for PR comments or CI job summaries.

Security: the history never includes raw secrets, full text, Bearer tokens,
or private key markers. A pre-write audit panics if forbidden fragments
are detected.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACTS_DIR = REPO_ROOT / "docs" / "operations" / "artifacts"
DEFAULT_OUTPUT = DEFAULT_ARTIFACTS_DIR / "sanitizer-drift-history.json"

ARTIFACT_VERSION = "1.0.0"
REQUIRED_ARTIFACT_TYPE = "sanitizer-drift-diff"

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


def _load_drift_report(path: Path) -> dict[str, Any]:
    """Load and validate a single drift diff artifact."""
    if not path.is_file():
        raise FileNotFoundError(f"Drift report not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("artifact") != REQUIRED_ARTIFACT_TYPE:
        raise ValueError(
            f"Invalid artifact type in {path}: expected {REQUIRED_ARTIFACT_TYPE!r}, "
            f"got {data.get('artifact')!r}"
        )
    # Minimal schema validation
    for key in ("version", "generated_at", "risk", "totals", "parsers"):
        if key not in data:
            raise ValueError(f"Missing required key {key!r} in {path}")
    return data


def _collect_reports(artifacts_dir: Path) -> list[dict[str, Any]]:
    """Find and load all valid drift diff reports, skipping corrupt ones."""
    if not artifacts_dir.is_dir():
        return []

    reports: list[dict[str, Any]] = []
    for path in sorted(artifacts_dir.glob("sanitizer-drift-diff*.json")):
        if path.name == "sanitizer-drift-diff.json":
            # Primary latest report
            pass
        try:
            report = _load_drift_report(path)
            reports.append(report)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            # Degraded: log but continue; do not fail silently
            reports.append(
                {
                    "_source_path": str(path.name),
                    "_degraded": True,
                    "_degraded_reason": str(exc),
                }
            )

    # Sort valid reports by generated_at; degraded items go to the end
    def _sort_key(r: dict[str, Any]) -> str:
        if r.get("_degraded"):
            return "9999"
        return r.get("generated_at", "")

    reports.sort(key=_sort_key)
    return reports


def _compute_trends(reports: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute trend metrics across valid drift diff reports."""
    valid_reports = [r for r in reports if not r.get("_degraded")]

    if not valid_reports:
        return {
            "available": False,
            "report_count": 0,
            "valid_report_count": 0,
            "parser_trend": [],
            "redaction_trend": [],
            "degraded_trend": [],
            "risk_trend": [],
        }

    parser_trend: list[dict[str, Any]] = []
    redaction_trend: list[dict[str, Any]] = []
    degraded_trend: list[dict[str, Any]] = []
    risk_trend: list[dict[str, Any]] = []

    for report in valid_reports:
        ts = report.get("generated_at", "")
        totals = report.get("totals", {})
        head = totals.get("head", {})
        delta = totals.get("delta", {})
        parsers = report.get("parsers", {})
        changed_count = len(parsers.get("changed", []))
        added_count = len(parsers.get("added", []))
        removed_count = len(parsers.get("removed", []))

        parser_trend.append(
            {
                "generated_at": ts,
                "changed": changed_count,
                "added": added_count,
                "removed": removed_count,
            }
        )
        redaction_trend.append(
            {
                "generated_at": ts,
                "head_redacted": head.get("redacted", 0),
                "delta_redacted": delta.get("redacted", 0),
            }
        )
        degraded_trend.append(
            {
                "generated_at": ts,
                "head_degraded": head.get("degraded", 0),
                "delta_degraded": delta.get("degraded", 0),
            }
        )
        risk_trend.append(
            {
                "generated_at": ts,
                "risk": report.get("risk", "unknown"),
                "base_golden_hash": report.get("base_golden_hash", "")[:12],
                "head_golden_hash": report.get("head_golden_hash", "")[:12],
                "golden_hash_drift": report.get("golden_hash_drift", False),
            }
        )

    return {
        "available": True,
        "report_count": len(reports),
        "valid_report_count": len(valid_reports),
        "parser_trend": parser_trend,
        "redaction_trend": redaction_trend,
        "degraded_trend": degraded_trend,
        "risk_trend": risk_trend,
    }


def _latest_report_summary(reports: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Extract the latest valid report for badge/card display."""
    valid_reports = [r for r in reports if not r.get("_degraded")]
    if not valid_reports:
        return None
    latest = valid_reports[-1]
    parsers = latest.get("parsers", {})
    return {
        "risk": latest.get("risk", "unknown"),
        "base_golden_hash": latest.get("base_golden_hash", "")[:12],
        "head_golden_hash": latest.get("head_golden_hash", "")[:12],
        "changed_parser_count": len(parsers.get("changed", [])),
        "added_parser_count": len(parsers.get("added", [])),
        "removed_parser_count": len(parsers.get("removed", [])),
        "generated_at": latest.get("generated_at", ""),
        "head_redacted": latest.get("totals", {}).get("head", {}).get("redacted", 0),
        "head_degraded": latest.get("totals", {}).get("head", {}).get("degraded", 0),
    }


def build_history(artifacts_dir: Path) -> dict[str, Any]:
    """Build the complete drift history artifact."""
    reports = _collect_reports(artifacts_dir)
    trends = _compute_trends(reports)
    latest = _latest_report_summary(reports)

    degraded_reports = [r for r in reports if r.get("_degraded")]
    overall_status = "success"
    if degraded_reports:
        overall_status = "degraded"
    elif not latest:
        overall_status = "no_history"

    try:
        reports_dir = str(artifacts_dir.relative_to(REPO_ROOT))
    except ValueError:
        reports_dir = str(artifacts_dir)

    history = {
        "artifact": "sanitizer-drift-history",
        "version": ARTIFACT_VERSION,
        "schema_version": ARTIFACT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": overall_status,
        "reports_dir": reports_dir,
        "trends": trends,
        "latest": latest,
        "degraded_reports": [
            {
                "source_path": r.get("_source_path", ""),
                "reason": r.get("_degraded_reason", ""),
            }
            for r in degraded_reports
        ],
    }

    _assert_no_raw_secrets(history, "sanitizer-drift-history")
    return history


def _render_markdown(history: dict[str, Any]) -> str:
    """Render the drift history as a Markdown report."""
    lines: list[str] = []
    lines.append("## Sanitizer Drift History")
    lines.append("")
    lines.append(f"- **Status**: `{history['status']}`")
    lines.append(f"- **Reports scanned**: {history['trends']['report_count']}")
    lines.append(f"- **Valid reports**: {history['trends']['valid_report_count']}")
    lines.append("")

    latest = history.get("latest")
    if latest:
        lines.append("### Latest Report Summary")
        lines.append("")
        risk = latest["risk"]
        risk_emoji = "⚠️" if risk == "degraded" else "✅" if risk == "unchanged" else "❓"
        lines.append(f"- **Risk**: {risk_emoji} `{risk}`")
        lines.append(f"- **Base hash**: `{latest['base_golden_hash']}`")
        lines.append(f"- **Head hash**: `{latest['head_golden_hash']}`")
        lines.append(f"- **Changed parsers**: {latest['changed_parser_count']}")
        lines.append(f"- **Added parsers**: {latest['added_parser_count']}")
        lines.append(f"- **Removed parsers**: {latest['removed_parser_count']}")
        lines.append(f"- **Head redacted**: {latest['head_redacted']}")
        lines.append(f"- **Head degraded**: {latest['head_degraded']}")
        lines.append("")
    else:
        lines.append("### Latest Report Summary")
        lines.append("")
        lines.append("No valid drift reports found.")
        lines.append("")

    trends = history["trends"]
    if trends["available"]:
        lines.append("### Trends")
        lines.append("")

        lines.append("#### Risk Trend")
        lines.append("")
        lines.append("| Generated At | Risk | Hash Drift |")
        lines.append("|--------------|------|------------|")
        for entry in trends["risk_trend"]:
            drift = "yes" if entry["golden_hash_drift"] else "no"
            lines.append(
                f"| {entry['generated_at']} | {entry['risk']} | {drift} |"
            )
        lines.append("")

        lines.append("#### Parser Changes")
        lines.append("")
        lines.append("| Generated At | Changed | Added | Removed |")
        lines.append("|--------------|---------|-------|---------|")
        for entry in trends["parser_trend"]:
            lines.append(
                f"| {entry['generated_at']} | {entry['changed']} | "
                f"{entry['added']} | {entry['removed']} |"
            )
        lines.append("")

        lines.append("#### Redaction Trend")
        lines.append("")
        lines.append("| Generated At | Head Redacted | Delta |")
        lines.append("|--------------|---------------|-------|")
        for entry in trends["redaction_trend"]:
            sign = "+" if entry["delta_redacted"] > 0 else ""
            lines.append(
                f"| {entry['generated_at']} | {entry['head_redacted']} | "
                f"{sign}{entry['delta_redacted']} |"
            )
        lines.append("")

        lines.append("#### Degraded Trend")
        lines.append("")
        lines.append("| Generated At | Head Degraded | Delta |")
        lines.append("|--------------|---------------|-------|")
        for entry in trends["degraded_trend"]:
            sign = "+" if entry["delta_degraded"] > 0 else ""
            lines.append(
                f"| {entry['generated_at']} | {entry['head_degraded']} | "
                f"{sign}{entry['delta_degraded']} |"
            )
        lines.append("")
    else:
        lines.append("### Trends")
        lines.append("")
        lines.append("No trend data available (insufficient valid reports).")
        lines.append("")

    degraded = history.get("degraded_reports", [])
    if degraded:
        lines.append("### Degraded / Corrupt Reports")
        lines.append("")
        for d in degraded:
            lines.append(f"- `{d['source_path']}`: {d['reason']}")
        lines.append("")

    lines.append("---")
    lines.append("*Generated by sanitizer-drift-history. No raw secrets are included.*")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read sanitizer drift diff artifacts and produce a historical trend report."
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=DEFAULT_ARTIFACTS_DIR,
        help="Directory containing sanitizer-drift-diff*.json artifacts",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output JSON path for the history artifact",
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
        history = build_history(args.artifacts_dir)
    except RuntimeError as exc:
        print(f"Safety check failed: {exc}", file=sys.stderr)
        return 2

    markdown = _render_markdown(history)

    # Write JSON artifact
    if args.format in ("json", "both"):
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(history, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Drift history JSON written to {args.output}")

    # Write Markdown report
    if args.format in ("markdown", "both"):
        md_path = args.markdown_output or args.output.with_suffix(".md")
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(markdown, encoding="utf-8")
        print(f"Drift history Markdown written to {md_path}")

    if args.stdout:
        print("\n" + markdown)

    return 0 if history["status"] in ("success", "no_history") else 3


if __name__ == "__main__":
    sys.exit(main())
