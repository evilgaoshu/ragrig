"""Build sanitized evaluation reports for Web Console and CLI output.

Reports are guaranteed to never include raw secrets, provider keys,
or sensitive ACL principal identifiers.
"""

from __future__ import annotations

from typing import Any

from ragrig.evaluation.models import EvaluationRun

# Sensitive key patterns that must never appear in reports
_SENSITIVE_KEY_PARTS = (
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

_SENSITIVE_VALUE_KEYWORDS = (
    "secret",
    "password",
    "token",
    "credential",
)

# Sensitive ACL principal identifiers
_SENSITIVE_ACL_PATTERNS = (
    "principal",
    "acl",
)


def _is_sensitive_key(key: str) -> bool:
    key_lower = key.lower()
    return any(part in key_lower for part in _SENSITIVE_KEY_PARTS)


def _sanitize_dict(data: dict[str, Any], path: str = "") -> dict[str, Any]:
    """Recursively sanitize a dict, redacting sensitive keys."""
    result: dict[str, Any] = {}
    for key, value in data.items():
        full_path = f"{path}.{key}" if path else key
        if _is_sensitive_key(key):
            result[key] = "[REDACTED]"
        elif isinstance(value, dict):
            if any(pattern in key.lower() for pattern in _SENSITIVE_ACL_PATTERNS):
                # For ACL-related dicts, sanitize deeply
                result[key] = {
                    k: _sanitize_value(v, f"{full_path}.{k}")
                    if not _is_sensitive_key(k)
                    else "[REDACTED]"
                    for k, v in value.items()
                }
            else:
                result[key] = _sanitize_dict(value, full_path)
        elif isinstance(value, list):
            result[key] = [
                _sanitize_value(item, f"{full_path}[{i}]")
                if isinstance(item, (dict, str))
                else item
                for i, item in enumerate(value)
            ]
        else:
            result[key] = value
    return result


def _sanitize_value(value: Any, path: str = "") -> Any:
    """Sanitize a single value, redacting if it contains sensitive keywords."""
    if isinstance(value, dict):
        return _sanitize_dict(value, path)
    if isinstance(value, str):
        value_lower = value.lower()
        if any(kw in value_lower for kw in _SENSITIVE_VALUE_KEYWORDS):
            # Only redact if it looks like an actual credentials string
            # (not just a word that happens to contain "secret")
            if "://" in value_lower or "=" in value_lower or len(value) > 80:
                return "[REDACTED]"
        # Check for raw key patterns
        for part in _SENSITIVE_KEY_PARTS:
            if part in value_lower and len(value) > 20:
                return "[REDACTED]"
    return value


def build_evaluation_report(run: EvaluationRun) -> dict[str, Any]:
    """Build a sanitized JSON-serializable report for an evaluation run."""
    # Use model_dump which returns a dict, then sanitize
    data = run.model_dump()
    return _sanitize_dict(data)


def build_evaluation_list_report(
    runs: list[EvaluationRun],
) -> dict[str, Any]:
    """Build a sanitized list report with metadata."""
    sanitized_runs = [build_evaluation_report(run) for run in runs]
    latest = sanitized_runs[0] if sanitized_runs else None
    return {
        "runs": sanitized_runs,
        "latest_id": latest["id"] if latest else None,
        "latest_metrics": latest.get("metrics") if latest else None,
    }


def build_evaluation_run_report(
    run: EvaluationRun,
    include_items: bool = True,
) -> dict[str, Any]:
    """Build a sanitized single-run report, optionally including items."""
    data = run.model_dump()
    sanitized = _sanitize_dict(data)
    if not include_items:
        sanitized.pop("items", None)
    return sanitized
