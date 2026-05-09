"""Generate sanitizer-coverage-summary.json artifact.

Usage::

    python -m scripts.sanitizer_coverage [--output <path>]

Reads all golden snapshot files under tests/goldens/sanitizer_*.json,
computes a structured coverage summary, and writes it to OUTPUT (defaults
to docs/operations/artifacts/sanitizer-coverage-summary.json).

The output is a versioned artifact suitable for CI upload, PR comment
summaries, and Web Console display.  It never contains raw secrets.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "operations" / "artifacts" / "sanitizer-coverage-summary.json"

ARTIFACT_VERSION = "1.0.0"

# ── Fields that must never contain raw secrets ─────────────────────────────
FORBIDDEN_FRAGMENTS: tuple[str, ...] = (
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
        for fragment in FORBIDDEN_FRAGMENTS:
            if fragment in data:
                raise RuntimeError(f"{source}: raw secret fragment '{fragment}' detected in output")
    elif isinstance(data, dict):
        for k, v in data.items():
            _assert_no_raw_secrets(v, f"{source}.{k}")
    elif isinstance(data, list):
        for i, v in enumerate(data):
            _assert_no_raw_secrets(v, f"{source}[{i}]")


def build_coverage_summary(goldens_dir: Path) -> dict:
    """Parse all sanitizer golden files and build the coverage summary.

    Returns a dict ready for JSON serialisation.  Every parser record
    includes: parser_id, fixtures, redacted, degraded, golden_hash, status.
    """
    golden_files = sorted(goldens_dir.glob("sanitizer_*.json"))
    if not golden_files:
        raise FileNotFoundError(f"No sanitizer golden files found in {goldens_dir}")

    parsers: list[dict] = []
    total_fixtures = 0
    total_redacted = 0
    total_degraded = 0

    for golden_path in golden_files:
        golden = json.loads(golden_path.read_text(encoding="utf-8"))
        parser_id: str = golden.get("parser_id", "unknown")
        redacted: int = golden.get("redaction_count", 0)
        status: str = golden.get("status", "unknown")
        degraded: int = 1 if status == "degraded" else 0

        # Compute deterministic hash of the golden content (excluding raw text)
        content_for_hash = json.dumps(golden, sort_keys=True, ensure_ascii=False)
        golden_hash = sha256(content_for_hash.encode("utf-8")).hexdigest()

        record = {
            "parser_id": parser_id,
            "fixtures": 1,
            "redacted": redacted,
            "degraded": degraded,
            "golden_hash": golden_hash,
            "status": status,
        }

        # Include optional fields for audit
        if "degraded_reason" in golden:
            record["degraded_reason"] = golden["degraded_reason"]
        if "csv_parse_error" in golden:
            record["csv_parse_error"] = golden["csv_parse_error"]
        # text_summary is NOT included – it may contain redacted fragment patterns

        parsers.append(record)
        total_fixtures += 1
        total_redacted += redacted
        total_degraded += degraded

    # Compute aggregate hash across all parser records
    aggregate_content = json.dumps(parsers, sort_keys=True, ensure_ascii=False)
    aggregate_hash = sha256(aggregate_content.encode("utf-8")).hexdigest()

    summary = {
        "artifact": "sanitizer-coverage-summary",
        "version": ARTIFACT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "fixtures": total_fixtures,
            "redacted": total_redacted,
            "degraded": total_degraded,
        },
        "golden_hash": aggregate_hash,
        "parsers": parsers,
        "redaction_floor": 1,
        "redaction_floor_check": all(p["redacted"] >= 1 for p in parsers),
    }

    # Safety check before writing
    _assert_no_raw_secrets(summary, "sanitizer-coverage-summary")

    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate sanitizer coverage summary artifact")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output JSON path")
    args = parser.parse_args(argv)

    goldens_dir = REPO_ROOT / "tests" / "goldens"
    try:
        summary = build_coverage_summary(goldens_dir)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as exc:
        print(f"Safety check failed: {exc}", file=sys.stderr)
        sys.exit(2)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Sanitizer coverage summary written to {args.output}")
    print(f"  Parsers: {summary['totals']['fixtures']}")
    print(f"  Total redactions: {summary['totals']['redacted']}")
    print(f"  Degraded: {summary['totals']['degraded']}")
    print(f"  Redaction floor check: {'PASS' if summary['redaction_floor_check'] else 'FAIL'}")


if __name__ == "__main__":
    main()
