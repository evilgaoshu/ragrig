"""Validate the Understanding Runs export contract fixture.

Usage: uv run python -m scripts.verify_export_fixture

Verifies that the fixture file contains all required schema fields and no
sensitive data (secrets, full prompts, full extracted_text).
"""

import json
import sys
from pathlib import Path

REQUIRED_TOP_FIELDS = {
    "schema_version",
    "generated_at",
    "filter",
    "run_count",
    "run_ids",
    "knowledge_base",
    "knowledge_base_id",
    "runs",
}

REQUIRED_RUN_FIELDS = {
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

FORBIDDEN_KEYS = {
    "extracted_text",
    "prompt",
    "full_prompt",
    "system_prompt",
    "user_prompt",
    "messages",
    "raw_response",
}

FORBIDDEN_VALUE_PATTERNS = (
    "api_key",
    "access_key",
    "secret_key",
    "session_token",
    "password",
    "private_key",
    "credential",
    "sk-",  # OpenAI-style API key prefix
)


def _find_forbidden(data: object, path: str = "$") -> list[str]:
    """Recursively search for forbidden keys or secret-like values."""
    issues: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            key_lower = key.lower()
            if key_lower in FORBIDDEN_KEYS:
                issues.append(f"[FORBIDDEN KEY] {path}.{key} = {str(value)[:50]}...")
            if isinstance(value, str):
                for pattern in FORBIDDEN_VALUE_PATTERNS:
                    if pattern in value.lower() and len(value) > 3:
                        issues.append(f"[SECRET PATTERN] {path}.{key} matches '{pattern}'")
            issues.extend(_find_forbidden(value, f"{path}.{key}"))
    elif isinstance(data, list):
        for i, item in enumerate(data):
            issues.extend(_find_forbidden(item, f"{path}[{i}]"))
    return issues


def main() -> int:
    fixture_path = (
        Path(__file__).parent.parent / "tests" / "fixtures" / "understanding_export_contract.json"
    )
    if not fixture_path.exists():
        print(f"ERROR: Fixture not found at {fixture_path}")
        return 1

    with open(fixture_path, encoding="utf-8") as f:
        data = json.load(f)

    errors: list[str] = []

    # Check top-level required fields
    for field in REQUIRED_TOP_FIELDS:
        if field not in data:
            errors.append(f"MISSING top-level field: {field}")

    # Check schema_version
    if data.get("schema_version") != "1.0":
        errors.append(f"schema_version must be '1.0', got: {data.get('schema_version')}")

    # Check generated_at
    if "generated_at" not in data:
        errors.append("MISSING generated_at")

    # Check filter fields
    filter_obj = data.get("filter", {})
    if not isinstance(filter_obj, dict):
        errors.append("filter must be an object")
    else:
        filter_fields = (
            "provider",
            "model",
            "profile_id",
            "status",
            "started_after",
            "started_before",
            "limit",
        )
        for f in filter_fields:
            if f not in filter_obj:
                errors.append(f"MISSING filter.{f}")

    # Check run_count matches run_ids
    run_count = data.get("run_count", 0)
    run_ids = data.get("run_ids", [])
    if len(run_ids) != run_count:
        errors.append(f"run_count ({run_count}) != len(run_ids) ({len(run_ids)})")

    runs = data.get("runs", [])
    if len(runs) != run_count:
        errors.append(f"len(runs) ({len(runs)}) != run_count ({run_count})")

    # Check each run
    for i, run in enumerate(runs):
        for field in REQUIRED_RUN_FIELDS:
            if field not in run:
                errors.append(f"MISSING runs[{i}].{field}")

    # Check no secrets or forbidden content
    issues = _find_forbidden(data)
    errors.extend(issues)

    if errors:
        print(f"FAIL: {len(errors)} issue(s) found in fixture:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"PASS: fixture at {fixture_path} is valid.")
    print(f"  schema_version: {data['schema_version']}")
    print(f"  run_count: {data['run_count']}")
    print(f"  filter fields: {list(data['filter'].keys())}")
    print(f"  runs: {len(data['runs'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
