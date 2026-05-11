"""Compare two sanitizer-coverage-summary.json files and produce a drift diff.

Usage::

    python -m scripts.sanitizer_drift_diff \
        --base  <base-summary.json> \
        --head  <head-summary.json> \
        --output <diff-artifact.json> \
        [--format json|markdown|both]

Produces:
- A structured diff artifact (JSON) with added/removed/changed parsers,
  redaction_count delta, degraded delta, golden_hash drift, and risk status.
- A Markdown report suitable for PR comments or CI job summaries.

Security: the diff never includes raw secrets, full text, Bearer tokens,
or private key markers.  A pre-write audit panics if forbidden fragments
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
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "operations" / "artifacts" / "sanitizer-drift-diff.json"

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


def _assert_no_raw_secrets(data: object, source: str) -> None:
    """Panic if any string value in *data* contains a forbidden fragment."""
    if isinstance(data, str):
        for fragment in _FORBIDDEN_FRAGMENTS:
            if fragment in data:
                raise RuntimeError(
                    f"{source}: raw secret fragment {fragment!r} detected in output"
                )
    elif isinstance(data, dict):
        for k, v in data.items():
            _assert_no_raw_secrets(v, f"{source}.{k}")
    elif isinstance(data, list):
        for i, v in enumerate(data):
            _assert_no_raw_secrets(v, f"{source}[{i}]")


def _load_summary(path: Path) -> dict[str, Any]:
    """Load and validate a sanitizer-coverage-summary.json file."""
    if not path.is_file():
        raise FileNotFoundError(f"Summary file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("artifact") != "sanitizer-coverage-summary":
        raise ValueError(
            f"Invalid artifact type in {path}: expected 'sanitizer-coverage-summary', "
            f"got {data.get('artifact')!r}"
        )
    return data


def _parser_map(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build a dict mapping parser_id → parser record."""
    parsers = summary.get("parsers", [])
    if not isinstance(parsers, list):
        raise ValueError("'parsers' must be a list")
    result: dict[str, dict[str, Any]] = {}
    for p in parsers:
        pid = p.get("parser_id")
        if not pid:
            raise ValueError("Parser record missing 'parser_id'")
        result[pid] = p
    return result


def _compute_parser_diff(
    base_record: dict[str, Any] | None,
    head_record: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Compute the diff for a single parser between base and head.

    Returns None if there is no change (and the parser exists in both).
    """
    if base_record is None and head_record is None:
        return None

    if base_record is None:
        # Added parser
        return {
            "parser_id": head_record["parser_id"],
            "change_type": "added",
            "base": None,
            "head": {
                "fixtures": head_record.get("fixtures", 0),
                "redacted": head_record.get("redacted", 0),
                "degraded": head_record.get("degraded", 0),
                "golden_hash": head_record.get("golden_hash", ""),
                "status": head_record.get("status", "unknown"),
            },
        }

    if head_record is None:
        # Removed parser
        return {
            "parser_id": base_record["parser_id"],
            "change_type": "removed",
            "base": {
                "fixtures": base_record.get("fixtures", 0),
                "redacted": base_record.get("redacted", 0),
                "degraded": base_record.get("degraded", 0),
                "golden_hash": base_record.get("golden_hash", ""),
                "status": base_record.get("status", "unknown"),
            },
            "head": None,
        }

    # Both exist — check for changes
    fields = ("fixtures", "redacted", "degraded", "golden_hash", "status")
    base_slice = {k: base_record.get(k) for k in fields}
    head_slice = {k: head_record.get(k) for k in fields}

    if base_slice == head_slice:
        return None

    return {
        "parser_id": base_record["parser_id"],
        "change_type": "changed",
        "base": base_slice,
        "head": head_slice,
    }


def compute_drift_diff(
    base_summary: dict[str, Any],
    head_summary: dict[str, Any],
) -> dict[str, Any]:
    """Compare base and head coverage summaries and return a drift diff record.

    The diff includes:
    - added, removed, changed parsers
    - total redaction_count and degraded delta
    - golden_hash drift
    - risk assessment (degraded / unchanged)
    """
    base_parsers = _parser_map(base_summary)
    head_parsers = _parser_map(head_summary)

    all_ids = sorted(set(base_parsers) | set(head_parsers))

    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []

    base_total_redacted = base_summary.get("totals", {}).get("redacted", 0)
    head_total_redacted = head_summary.get("totals", {}).get("redacted", 0)
    base_total_degraded = base_summary.get("totals", {}).get("degraded", 0)
    head_total_degraded = head_summary.get("totals", {}).get("degraded", 0)

    redacted_delta = head_total_redacted - base_total_redacted
    degraded_delta = head_total_degraded - base_total_degraded

    base_golden_hash = base_summary.get("golden_hash", "")
    head_golden_hash = head_summary.get("golden_hash", "")
    golden_hash_drift = base_golden_hash != head_golden_hash

    for pid in all_ids:
        diff = _compute_parser_diff(base_parsers.get(pid), head_parsers.get(pid))
        if diff is None:
            continue
        if diff["change_type"] == "added":
            added.append(diff)
        elif diff["change_type"] == "removed":
            removed.append(diff)
        else:
            changed.append(diff)

    # Risk assessment
    has_risk = False
    if redacted_delta < 0 or degraded_delta > 0:
        has_risk = True
    for ch in changed:
        base_redacted = ch["base"]["redacted"] if ch["base"] else 0
        head_redacted = ch["head"]["redacted"] if ch["head"] else 0
        base_degraded = ch["base"]["degraded"] if ch["base"] else 0
        head_degraded = ch["head"]["degraded"] if ch["head"] else 0
        if head_redacted < base_redacted or head_degraded > base_degraded:
            has_risk = True
            ch["risk"] = "degraded"
        else:
            ch["status"] = "changed"

    for a in added:
        # New parsers with 0 redactions or degraded are risky
        head_redacted = a["head"]["redacted"] if a["head"] else 0
        head_degraded = a["head"]["degraded"] if a["head"] else 0
        if head_redacted < 1 or head_degraded > 0:
            has_risk = True
            a["risk"] = "degraded"
        else:
            a["status"] = "added"

    for r in removed:
        r["status"] = "removed"

    risk_status = "degraded" if has_risk else "unchanged"

    # Build risk details
    risk_details: list[dict[str, Any]] = []
    if redacted_delta < 0:
        risk_details.append(
            {
                "type": "total_redaction_drop",
                "base": base_total_redacted,
                "head": head_total_redacted,
                "delta": redacted_delta,
            }
        )
    if degraded_delta > 0:
        risk_details.append(
            {
                "type": "total_degraded_increase",
                "base": base_total_degraded,
                "head": head_total_degraded,
                "delta": degraded_delta,
            }
        )
    for ch in changed:
        if ch.get("risk") == "degraded":
            risk_details.append(
                {
                    "type": "parser_degraded",
                    "parser_id": ch["parser_id"],
                    "reason": "redaction_count dropped or degraded increased",
                }
            )
    for a in added:
        if a.get("risk") == "degraded":
            risk_details.append(
                {
                    "type": "parser_added_with_risk",
                    "parser_id": a["parser_id"],
                    "reason": "new parser has zero redactions or is degraded",
                }
            )

    diff = {
        "artifact": "sanitizer-drift-diff",
        "version": ARTIFACT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_golden_hash": base_golden_hash,
        "head_golden_hash": head_golden_hash,
        "golden_hash_drift": golden_hash_drift,
        "totals": {
            "base": {
                "fixtures": base_summary.get("totals", {}).get("fixtures", 0),
                "redacted": base_total_redacted,
                "degraded": base_total_degraded,
            },
            "head": {
                "fixtures": head_summary.get("totals", {}).get("fixtures", 0),
                "redacted": head_total_redacted,
                "degraded": head_total_degraded,
            },
            "delta": {
                "fixtures": head_summary.get("totals", {}).get("fixtures", 0)
                - base_summary.get("totals", {}).get("fixtures", 0),
                "redacted": redacted_delta,
                "degraded": degraded_delta,
            },
        },
        "risk": risk_status,
        "risk_details": risk_details,
        "parsers": {
            "added": added,
            "removed": removed,
            "changed": changed,
        },
    }

    _assert_no_raw_secrets(diff, "sanitizer-drift-diff")
    return diff


def _render_markdown(diff: dict[str, Any]) -> str:
    """Render the drift diff as a Markdown report."""
    lines: list[str] = []
    lines.append("## Sanitizer Golden Drift Diff")
    lines.append("")
    lines.append(f"- **Base hash**: `{diff['base_golden_hash']}`")
    lines.append(f"- **Head hash**: `{diff['head_golden_hash']}`")
    lines.append(f"- **Golden hash drift**: {'yes' if diff['golden_hash_drift'] else 'no'}")
    lines.append("")

    totals = diff["totals"]
    lines.append("### Totals")
    lines.append("")
    lines.append("| Metric | Base | Head | Delta |")
    lines.append("|--------|------|------|-------|")
    for metric in ("fixtures", "redacted", "degraded"):
        b = totals["base"][metric]
        h = totals["head"][metric]
        d = totals["delta"][metric]
        sign = "+" if d > 0 else ""
        lines.append(f"| {metric.capitalize()} | {b} | {h} | {sign}{d} |")
    lines.append("")

    risk = diff["risk"]
    risk_emoji = "⚠️" if risk == "degraded" else "✅"
    lines.append(f"### Risk Assessment: {risk_emoji} `{risk}`")
    lines.append("")
    if diff["risk_details"]:
        for detail in diff["risk_details"]:
            t = detail["type"]
            if t == "total_redaction_drop":
                lines.append(
                    f"- ⚠️ Total redactions dropped by {abs(detail['delta'])} "
                    f"({detail['base']} → {detail['head']})"
                )
            elif t == "total_degraded_increase":
                lines.append(
                    f"- ⚠️ Total degraded increased by {detail['delta']} "
                    f"({detail['base']} → {detail['head']})"
                )
            elif t == "parser_degraded":
                lines.append(
                    f"- ⚠️ Parser `{detail['parser_id']}`: {detail['reason']}"
                )
            elif t == "parser_added_with_risk":
                lines.append(
                    f"- ⚠️ Parser `{detail['parser_id']}`: {detail['reason']}"
                )
            else:
                lines.append(f"- ⚠️ {t}: {detail}")
    else:
        lines.append("- No risk detected.")
    lines.append("")

    parsers = diff["parsers"]
    has_changes = parsers["added"] or parsers["removed"] or parsers["changed"]

    if not has_changes:
        lines.append("### Parser Changes")
        lines.append("")
        lines.append("No parser changes detected.")
        lines.append("")
    else:
        if parsers["added"]:
            lines.append("### Added Parsers")
            lines.append("")
            lines.append("| Parser | Fixtures | Redacted | Degraded | Status |")
            lines.append("|--------|----------|----------|----------|--------|")
            for a in parsers["added"]:
                h = a["head"]
                status = a.get("risk", a.get("status", "added"))
                emoji = "⚠️" if a.get("risk") == "degraded" else "🆕"
                lines.append(
                    f"| `{a['parser_id']}` | {h['fixtures']} | {h['redacted']} | "
                    f"{h['degraded']} | {emoji} {status} |"
                )
            lines.append("")

        if parsers["removed"]:
            lines.append("### Removed Parsers")
            lines.append("")
            lines.append("| Parser | Fixtures | Redacted | Degraded |")
            lines.append("|--------|----------|----------|----------|")
            for r in parsers["removed"]:
                b = r["base"]
                lines.append(
                    f"| `{r['parser_id']}` | {b['fixtures']} | {b['redacted']} | "
                    f"{b['degraded']} |"
                )
            lines.append("")

        if parsers["changed"]:
            lines.append("### Changed Parsers")
            lines.append("")
            lines.append(
                "| Parser | Base → Head (Fixtures) | Base → Head (Redacted) | "
                "Base → Head (Degraded) | Hash Drift | Status |"
            )
            lines.append(
                "|--------|------------------------|------------------------|"
                "------------------------|------------|--------|"
            )
            for ch in parsers["changed"]:
                b = ch["base"]
                h = ch["head"]
                hash_drift = "yes" if b["golden_hash"] != h["golden_hash"] else "no"
                status = ch.get("risk", ch.get("status", "changed"))
                emoji = "⚠️" if ch.get("risk") == "degraded" else "📝"
                lines.append(
                    f"| `{ch['parser_id']}` | {b['fixtures']} → {h['fixtures']} | "
                    f"{b['redacted']} → {h['redacted']} | "
                    f"{b['degraded']} → {h['degraded']} | {hash_drift} | "
                    f"{emoji} {status} |"
                )
            lines.append("")

    lines.append("---")
    lines.append("*Generated by sanitizer-drift-diff. No raw secrets are included.*")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare two sanitizer coverage summaries and produce a drift diff."
    )
    parser.add_argument(
        "--base",
        type=Path,
        required=True,
        help="Path to base sanitizer-coverage-summary.json",
    )
    parser.add_argument(
        "--head",
        type=Path,
        required=True,
        help="Path to head sanitizer-coverage-summary.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output JSON path for the diff artifact",
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
        base_summary = _load_summary(args.base)
        head_summary = _load_summary(args.head)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    diff = compute_drift_diff(base_summary, head_summary)
    markdown = _render_markdown(diff)

    # Write JSON artifact
    if args.format in ("json", "both"):
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(diff, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"Drift diff JSON written to {args.output}")

    # Write Markdown report
    if args.format in ("markdown", "both"):
        md_path = args.markdown_output or args.output.with_suffix(".md")
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(markdown, encoding="utf-8")
        print(f"Drift diff Markdown written to {md_path}")

    if args.stdout:
        print("\n" + markdown)

    return 2 if diff["risk"] == "degraded" else 0


if __name__ == "__main__":
    sys.exit(main())
