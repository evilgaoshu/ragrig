"""Read understanding-export-diff JSON and produce a concise PR-ready Markdown summary.

Usage::

    python -m scripts.understanding_export_diff_summary \
        [--diff <path>] \
        [--output <path>] \
        [--stdout]

Reads the understanding-export-diff.json artifact and produces a compact Markdown
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
DEFAULT_DIFF_PATH = (
    REPO_ROOT / "docs" / "operations" / "artifacts" / "understanding-export-diff.json"
)
DEFAULT_MD_PATH = (
    REPO_ROOT / "docs" / "operations" / "artifacts" / "understanding-export-diff.md"
)

REQUIRED_ARTIFACT_TYPE = "understanding-export-diff"
REQUIRED_VERSION = "1.0.0"

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


def _load_diff(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Diff artifact not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("artifact") != REQUIRED_ARTIFACT_TYPE:
        raise ValueError(
            f"Invalid artifact type in {path}: expected {REQUIRED_ARTIFACT_TYPE!r}, "
            f"got {data.get('artifact')!r}"
        )
    ver = data.get("version", "")
    if ver != REQUIRED_VERSION:
        raise ValueError(
            f"Version mismatch in {path}: expected {REQUIRED_VERSION!r}, got {ver!r}"
        )
    for key in ("status", "generated_at", "baseline", "current", "runs"):
        if key not in data:
            raise ValueError(f"Missing required key {key!r} in {path}")
    return data


def _resolve_md_path(diff_path: Path) -> Path:
    """Resolve the companion Markdown report path from the diff JSON path."""
    default = diff_path.with_name("understanding-export-diff.md")
    if default.is_file():
        return default
    return DEFAULT_MD_PATH


def _build_summary(diff: dict[str, Any], diff_path: Path, md_path: Path) -> dict[str, Any]:
    try:
        diff_rel = str(diff_path.relative_to(REPO_ROOT))
    except ValueError:
        diff_rel = str(diff_path)
    try:
        md_rel = str(md_path.relative_to(REPO_ROOT))
    except ValueError:
        md_rel = str(md_path)

    baseline = diff.get("baseline", {})
    current = diff.get("current", {})
    runs = diff.get("runs", {})

    return {
        "status": diff.get("status", "unknown"),
        "baseline_run_count": baseline.get("run_count", 0),
        "current_run_count": current.get("run_count", 0),
        "added_count": len(runs.get("added", [])),
        "removed_count": len(runs.get("removed", [])),
        "changed_count": len(runs.get("changed", [])),
        "schema_compatible": diff.get("schema_compatible", False),
        "generated_at": diff.get("generated_at", ""),
        "json_report_path": diff_rel,
        "md_report_path": md_rel,
        "sanitized_field_count": diff.get("sanitized_field_count", 0),
    }


def _render_markdown(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("## Understanding Export Diff Summary")
    lines.append("")

    status = summary["status"]
    status_emoji = "✅" if status == "pass" else "⚠️" if status == "degraded" else "❌"
    lines.append(f"- **Status**: {status_emoji} `{status}`")
    lines.append(f"- **Baseline run count**: {summary['baseline_run_count']}")
    lines.append(f"- **Current run count**: {summary['current_run_count']}")
    lines.append("")
    lines.append("### Changes")
    lines.append("")
    lines.append(f"- **Added**: {summary['added_count']}")
    lines.append(f"- **Removed**: {summary['removed_count']}")
    lines.append(f"- **Changed**: {summary['changed_count']}")
    lines.append("")
    lines.append(f"- **Schema compatible**: {'yes' if summary['schema_compatible'] else 'no'}")
    lines.append(f"- **Sanitized field count**: {summary['sanitized_field_count']}")
    lines.append("")
    lines.append("### Artifacts")
    lines.append("")
    lines.append(f"- **JSON report**: `{summary['json_report_path']}`")
    lines.append(f"- **MD report**: `{summary['md_report_path']}`")
    lines.append(f"- **Generated at**: `{summary['generated_at']}`")
    lines.append("")
    lines.append("---")
    lines.append("*Generated by understanding-export-diff-summary. No raw secrets are included.*")
    lines.append("")
    return "\n".join(lines)


def build_summary(diff_path: Path, md_path: Path | None = None) -> dict[str, Any]:
    diff = _load_diff(diff_path)
    if md_path is None:
        md_path = _resolve_md_path(diff_path)
    summary = _build_summary(diff, diff_path, md_path)
    _assert_no_raw_secrets(summary, "understanding-export-diff-summary")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read understanding-export-diff JSON and produce PR-ready Markdown summary."
    )
    parser.add_argument(
        "--diff",
        type=Path,
        default=DEFAULT_DIFF_PATH,
        help="Path to understanding-export-diff.json",
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=None,
        help="Path to companion Markdown report (auto-resolved if not given)",
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
        summary = build_summary(args.diff, args.markdown_output)
    except FileNotFoundError as exc:
        summary = {
            "status": "failure",
            "baseline_run_count": 0,
            "current_run_count": 0,
            "added_count": 0,
            "removed_count": 0,
            "changed_count": 0,
            "schema_compatible": False,
            "generated_at": "",
            "json_report_path": str(args.diff),
            "md_report_path": str(args.markdown_output or DEFAULT_MD_PATH),
            "sanitized_field_count": 0,
            "error": str(exc),
        }
    except (ValueError, json.JSONDecodeError, RuntimeError) as exc:
        summary = {
            "status": "failure",
            "baseline_run_count": 0,
            "current_run_count": 0,
            "added_count": 0,
            "removed_count": 0,
            "changed_count": 0,
            "schema_compatible": False,
            "generated_at": "",
            "json_report_path": str(args.diff),
            "md_report_path": str(args.markdown_output or DEFAULT_MD_PATH),
            "sanitized_field_count": 0,
            "error": str(exc),
        }

    markdown = _render_markdown(summary)

    try:
        _assert_no_raw_secrets(markdown, "understanding-export-diff-summary-markdown")
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

    if summary["status"] == "failure":
        return 1
    if summary["status"] == "degraded":
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
