"""Offline verification and audit summary for Understanding Runs export JSON.

Usage:
    uv run python -m scripts.verify_understanding_export <path> [<path> ...] [--json]

Verifies that export files contain all required schema fields, consistent
counts, and no sensitive data.  Outputs a concise summary suitable for
offline audit — never prints full prompts, original text, or secrets.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REQUIRED_TOP_FIELDS = frozenset(
    {
        "schema_version",
        "generated_at",
        "filter",
        "run_count",
        "run_ids",
        "knowledge_base",
        "knowledge_base_id",
        "runs",
    }
)

REQUIRED_RUN_FIELDS = frozenset(
    {
        "id",
        "knowledge_base_id",
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
        "error_summary",
        "started_at",
        "finished_at",
    }
)

FILTER_FIELDS = (
    "provider",
    "model",
    "profile_id",
    "status",
    "started_after",
    "started_before",
    "limit",
)

FORBIDDEN_KEYS = frozenset(
    {
        "extracted_text",
        "prompt",
        "full_prompt",
        "system_prompt",
        "user_prompt",
        "messages",
        "raw_response",
    }
)

SECRET_PATTERNS = (
    "api_key",
    "access_key",
    "secret_key",
    "session_token",
    "password",
    "private_key",
    "credential",
    "sk-",  # OpenAI-style API key prefix
)


class VerificationError(Exception):
    """Raised when a verification check fails."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def _scan_sanitization(data: object, path: str = "$") -> tuple[list[str], int]:
    """Recursively scan for forbidden keys and secret-like values.

    Returns a tuple of (issues, redacted_count).
    """
    issues: list[str] = []
    redacted_count = 0

    if isinstance(data, dict):
        for key, value in data.items():
            key_lower = key.lower()
            subpath = f"{path}.{key}"
            if key_lower in FORBIDDEN_KEYS:
                issues.append(f"[FORBIDDEN KEY] {subpath}")
                redacted_count += 1
                continue
            matched_pattern = _secret_pattern_match(key, value)
            if matched_pattern:
                issues.append(f"[SECRET PATTERN] {subpath} matches '{matched_pattern}'")
                redacted_count += 1
                continue
            sub_issues, sub_count = _scan_sanitization(value, subpath)
            issues.extend(sub_issues)
            redacted_count += sub_count
    elif isinstance(data, list):
        for i, item in enumerate(data):
            sub_issues, sub_count = _scan_sanitization(item, f"{path}[{i}]")
            issues.extend(sub_issues)
            redacted_count += sub_count

    return issues, redacted_count


def _secret_pattern_match(key: str, value: object) -> str | None:
    """Return the first matched secret pattern, or None."""
    key_lower = key.lower()
    for pattern in SECRET_PATTERNS:
        if pattern in key_lower:
            if isinstance(value, (str, int, float)) and value:
                return pattern
    if isinstance(value, str):
        val_lower = value.lower()
        for pattern in SECRET_PATTERNS:
            if pattern in val_lower and len(value) > 3:
                return pattern
    return None


def verify_export(data: dict[str, Any]) -> dict[str, Any]:
    """Verify a single export document and return an audit summary.

    Raises VerificationError on any structural or sanitization failure.
    """
    errors: list[str] = []

    # 1. Required top-level fields
    missing_top = REQUIRED_TOP_FIELDS - data.keys()
    if missing_top:
        errors.append(f"MISSING top-level fields: {sorted(missing_top)}")

    # 2. schema_version
    schema_version = data.get("schema_version")
    if schema_version != "1.0":
        errors.append(f"INVALID schema_version: expected '1.0', got {schema_version!r}")

    # 3. Filter structure
    filter_obj = data.get("filter", {})
    if not isinstance(filter_obj, dict):
        errors.append("INVALID filter: must be an object")
    else:
        missing_filter = [f for f in FILTER_FIELDS if f not in filter_obj]
        if missing_filter:
            errors.append(f"MISSING filter fields: {missing_filter}")

    # 4. Count consistency
    run_count = data.get("run_count", 0)
    run_ids = data.get("run_ids", [])
    runs = data.get("runs", [])

    if not isinstance(run_count, int) or run_count < 0:
        errors.append(f"INVALID run_count: must be a non-negative int, got {run_count!r}")

    if len(run_ids) != run_count:
        errors.append(f"MISMATCH run_count ({run_count}) != len(run_ids) ({len(run_ids)})")

    if len(runs) != run_count:
        errors.append(f"MISMATCH len(runs) ({len(runs)}) != run_count ({run_count})")

    # 5. Run-level required fields
    for i, run in enumerate(runs):
        if not isinstance(run, dict):
            errors.append(f"INVALID runs[{i}]: must be an object")
            continue
        missing_run = REQUIRED_RUN_FIELDS - run.keys()
        if missing_run:
            errors.append(f"MISSING runs[{i}] fields: {sorted(missing_run)}")

    # 6. Sanitization audit
    sanitization_issues, redacted_count = _scan_sanitization(data)
    if sanitization_issues:
        errors.extend(sanitization_issues)

    if errors:
        raise VerificationError(
            code="verification_failed",
            message="; ".join(errors),
        )

    # Build safe summary (never includes prompts, text, or secrets)
    summary: dict[str, Any] = {
        "status": "pass",
        "schema_version": schema_version,
        "run_count": run_count,
        "filter_keys": list(filter_obj.keys()) if isinstance(filter_obj, dict) else [],
        "sanitized_field_count": redacted_count,
        "run_ids_present": len(run_ids),
        "runs_present": len(runs),
    }
    return summary


def verify_file(path: Path) -> dict[str, Any]:
    """Verify a single export file and return a result dict."""
    result: dict[str, Any] = {"path": str(path), "status": "unknown"}

    if not path.exists():
        result["status"] = "error"
        result["error"] = "file_not_found"
        result["message"] = f"File not found: {path}"
        return result

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        result["status"] = "error"
        result["error"] = "invalid_json"
        result["message"] = f"Invalid JSON: {exc}"
        return result
    except OSError as exc:
        result["status"] = "error"
        result["error"] = "read_error"
        result["message"] = f"Read error: {exc}"
        return result

    if not isinstance(data, dict):
        result["status"] = "error"
        result["error"] = "invalid_structure"
        result["message"] = "Top-level JSON value must be an object"
        return result

    try:
        summary = verify_export(data)
    except VerificationError as exc:
        result["status"] = "fail"
        result["error"] = exc.code
        result["message"] = exc.message
        return result

    result.update(summary)
    return result


def format_summary(results: list[dict[str, Any]]) -> str:
    """Format verification results as human-readable text."""
    lines: list[str] = []
    total = len(results)
    passed = sum(1 for r in results if r.get("status") == "pass")
    failed = sum(1 for r in results if r.get("status") == "fail")
    errors = sum(1 for r in results if r.get("status") == "error")

    lines.append("Understanding Export Verification Summary")
    lines.append(f"  files_checked: {total}")
    lines.append(f"  passed: {passed}")
    lines.append(f"  failed: {failed}")
    lines.append(f"  errors: {errors}")
    lines.append("")

    for r in results:
        path = r["path"]
        status = r["status"]
        if status == "pass":
            lines.append(
                f"[PASS] {path}\n"
                f"  schema_version: {r.get('schema_version')}\n"
                f"  run_count: {r.get('run_count')}\n"
                f"  filter_keys: {r.get('filter_keys')}\n"
                f"  sanitized_field_count: {r.get('sanitized_field_count')}"
            )
        elif status == "fail":
            lines.append(f"[FAIL] {path}\n  error: {r.get('message')}")
        else:
            lines.append(f"[ERROR] {path}\n  error: {r.get('message')}")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Offline verification and audit summary for Understanding Runs export JSON."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Path(s) to export JSON file(s). Defaults to the built-in fixture.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results as JSON instead of human-readable text.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Write JSON summary to this file (implies --json).",
    )
    args = parser.parse_args(argv)

    paths: list[Path]
    if args.paths:
        paths = [Path(p) for p in args.paths]
    else:
        # Default to the built-in fixture
        fixture = (
            Path(__file__).parent.parent
            / "tests"
            / "fixtures"
            / "understanding_export_contract.json"
        )
        paths = [fixture]

    results: list[dict[str, Any]] = [verify_file(p) for p in paths]

    use_json = args.json or args.output is not None
    if use_json:
        output = json.dumps({"results": results}, indent=2, ensure_ascii=False)
        if args.output:
            args.output.write_text(output, encoding="utf-8")
            print(f"JSON summary written to {args.output}")
        else:
            print(output)
    else:
        print(format_summary(results))

    # Exit non-zero if any file failed or had an error
    if any(r["status"] in ("fail", "error") for r in results):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
