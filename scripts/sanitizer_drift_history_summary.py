"""Read sanitizer drift history JSON and produce a concise PR-ready Markdown summary.

Usage::

    python -m scripts.sanitizer_drift_history_summary \
        [--history <path>] \
        [--output <path>] \
        [--stdout]

Reads the sanitizer-drift-history.json artifact and produces a compact Markdown
summary suitable for PR comments or CI job summaries.

Security: the summary never includes raw secrets, full text, Bearer tokens,
or private key markers. A pre-write audit panics if forbidden fragments
are detected.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HISTORY_PATH = (
    REPO_ROOT / "docs" / "operations" / "artifacts" / "sanitizer-drift-history.json"
)

REQUIRED_ARTIFACT_TYPE = "sanitizer-drift-history"
REQUIRED_SCHEMA_VERSION = "1.0.0"

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


def _load_history(path: Path) -> dict[str, Any]:
    """Load and validate a sanitizer-drift-history.json artifact."""
    if not path.is_file():
        raise FileNotFoundError(f"History artifact not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("artifact") != REQUIRED_ARTIFACT_TYPE:
        raise ValueError(
            f"Invalid artifact type in {path}: expected {REQUIRED_ARTIFACT_TYPE!r}, "
            f"got {data.get('artifact')!r}"
        )
    schema = data.get("schema_version", data.get("version", ""))
    if schema != REQUIRED_SCHEMA_VERSION:
        raise ValueError(
            f"Schema version mismatch in {path}: expected {REQUIRED_SCHEMA_VERSION!r}, "
            f"got {schema!r}"
        )
    for key in ("status", "generated_at", "trends"):
        if key not in data:
            raise ValueError(f"Missing required key {key!r} in {path}")
    return data


def _build_summary(history: dict[str, Any], history_path: Path) -> dict[str, Any]:
    """Build a compact summary dict from the history artifact."""
    latest = history.get("latest") or {}
    trends = history.get("trends", {})
    degraded_reports = history.get("degraded_reports", [])

    try:
        report_path = str(history_path.relative_to(REPO_ROOT))
    except ValueError:
        report_path = str(history_path)

    return {
        "status": history.get("status", "unknown"),
        "latest_risk": latest.get("risk", "unknown") if latest else "unknown",
        "base_golden_hash": latest.get("base_golden_hash", "") if latest else "",
        "head_golden_hash": latest.get("head_golden_hash", "") if latest else "",
        "changed_parser_count": latest.get("changed_parser_count", 0) if latest else 0,
        "degraded_reports_count": len(degraded_reports),
        "report_path": report_path,
        "valid_report_count": trends.get("valid_report_count", 0),
        "total_report_count": trends.get("report_count", 0),
        "generated_at": history.get("generated_at", ""),
    }


def _render_markdown(summary: dict[str, Any]) -> str:
    """Render the summary as a compact Markdown report."""
    lines: list[str] = []
    lines.append("## Sanitizer Drift History Summary")
    lines.append("")

    status = summary["status"]
    status_emoji = "✅" if status == "success" else "⚠️" if status == "degraded" else "❓"
    lines.append(f"- **Status**: {status_emoji} `{status}`")

    risk = summary["latest_risk"]
    risk_emoji = "⚠️" if risk == "degraded" else "✅" if risk == "unchanged" else "❓"
    lines.append(f"- **Latest risk**: {risk_emoji} `{risk}`")

    if summary["base_golden_hash"]:
        lines.append(f"- **Base hash**: `{summary['base_golden_hash']}`")
    if summary["head_golden_hash"]:
        lines.append(f"- **Head hash**: `{summary['head_golden_hash']}`")

    lines.append(f"- **Changed parsers**: {summary['changed_parser_count']}")
    lines.append(f"- **Degraded reports**: {summary['degraded_reports_count']}")
    lines.append(
        f"- **Valid / total reports**: {summary['valid_report_count']} / "
        f"{summary['total_report_count']}"
    )
    lines.append(f"- **Report path**: `{summary['report_path']}`")
    lines.append("")
    lines.append("---")
    lines.append("*Generated by sanitizer-drift-history-summary. No raw secrets are included.*")
    lines.append("")
    return "\n".join(lines)


def build_summary(history_path: Path) -> dict[str, Any]:
    """Load history and build the summary."""
    history = _load_history(history_path)
    summary = _build_summary(history, history_path)
    _assert_no_raw_secrets(summary, "sanitizer-drift-history-summary")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read sanitizer drift history and produce a concise PR-ready Markdown summary."
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=DEFAULT_HISTORY_PATH,
        help="Path to sanitizer-drift-history.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output path for the Markdown summary",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print the Markdown summary to stdout",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the raw summary JSON to stdout",
    )
    args = parser.parse_args(argv)

    try:
        summary = build_summary(args.history)
    except FileNotFoundError as exc:
        summary = {
            "status": "failure",
            "latest_risk": "unknown",
            "base_golden_hash": "",
            "head_golden_hash": "",
            "changed_parser_count": 0,
            "degraded_reports_count": 0,
            "report_path": str(args.history),
            "valid_report_count": 0,
            "total_report_count": 0,
            "generated_at": "",
            "error": str(exc),
        }
    except (ValueError, json.JSONDecodeError, RuntimeError) as exc:
        summary = {
            "status": "failure",
            "latest_risk": "unknown",
            "base_golden_hash": "",
            "head_golden_hash": "",
            "changed_parser_count": 0,
            "degraded_reports_count": 0,
            "report_path": str(args.history),
            "valid_report_count": 0,
            "total_report_count": 0,
            "generated_at": "",
            "error": str(exc),
        }

    markdown = _render_markdown(summary)

    # Pre-write audit on markdown output
    try:
        _assert_no_raw_secrets(markdown, "sanitizer-drift-history-summary-markdown")
    except RuntimeError as exc:
        print(f"Safety check failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(summary, indent=2, ensure_ascii=False))

    if args.stdout:
        print(markdown)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
        print(f"Summary written to {args.output}")

    # Exit codes: 0 = success/no_history, 1 = failure, 3 = degraded
    if summary["status"] == "failure":
        return 1
    if summary["status"] == "degraded":
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
