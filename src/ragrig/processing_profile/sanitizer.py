"""ProcessingProfile metadata sanitizer — single source of truth.

This module is the **only** place where sensitive key/value detection rules are
defined for ProcessingProfile metadata.  All callers (repository audit/diff/rollback,
model ``to_api_dict()``, and any future API display layer) MUST use the helpers
exported here.

Modes
-----
*redacted* — Replace sensitive fields with ``[REDACTED]``; also returns redaction
count and dot-separated paths for audit trails.
  Call point: repository audit / diff / rollback state snapshots.

*removal* — Sensitive fields are **omitted** from the output entirely.
  Call point: ``ProcessingProfile.to_api_dict()`` (API response payloads).

Shared configuration
--------------------
``SENSITIVE_KEY_PARTS`` and ``SENSITIVE_VALUE_PREFIXES`` are the canonical
allowlist of what is considered sensitive.  Every call site consumes these
rules through the shared predicates ``is_sensitive_key`` / ``is_sensitive_value``.

Adding or removing a keyword here **automatically** propagates to all callers.
The drift-protection tests in ``tests/test_processing_profile_sanitizer.py``
enforce that repository, model, and API callers stay consistent.
"""

from __future__ import annotations

from typing import Any

REDACTED = "[REDACTED]"

SENSITIVE_KEY_PARTS: tuple[str, ...] = (
    "api_key",
    "access_key",
    "secret",
    "session_token",
    "token",
    "password",
    "private_key",
    "credential",
    "dsn",
    "service_account",
)

SENSITIVE_VALUE_PREFIXES: tuple[str, ...] = (
    "bearer ",
    "-----begin",
)


def is_sensitive_key(key: str) -> bool:
    """Return True if *key* contains any known sensitive key part (case-insensitive)."""
    key_lower = key.lower()
    return any(part in key_lower for part in SENSITIVE_KEY_PARTS)


def is_sensitive_value(value: object) -> bool:
    """Return True if *value* looks like a secret (Bearer token, PEM header, etc.).

    Only string values are inspected; non-strings always return ``False``.
    """
    if not isinstance(value, str):
        return False
    value_lower = value.lower()
    return any(pattern in value_lower for pattern in SENSITIVE_VALUE_PREFIXES)


# ── recursive implementation (private) ────────────────────────────────────


def _sanitize_list_impl(
    items: list[Any],
    *,
    mode: str,
    prefix: str = "",
) -> tuple[list[Any], int, list[str]]:
    """Recurse into a list, applying the chosen *mode*."""
    sanitized: list[Any] = []
    count = 0
    paths: list[str] = []

    for idx, item in enumerate(items):
        item_path = f"{prefix}[{idx}]"
        if isinstance(item, dict):
            sub, sub_count, sub_paths = _sanitize_metadata_impl(item, mode=mode, prefix=item_path)
            sanitized.append(sub)
            count += sub_count
            paths.extend(sub_paths)
        elif isinstance(item, list):
            sub, sub_count, sub_paths = _sanitize_list_impl(item, mode=mode, prefix=item_path)
            sanitized.append(sub)
            count += sub_count
            paths.extend(sub_paths)
        elif is_sensitive_value(item):
            if mode == "redact":
                sanitized.append(REDACTED)
            # "remove" mode skips the item
            count += 1
            paths.append(item_path)
        else:
            sanitized.append(item)

    return sanitized, count, paths


def _sanitize_metadata_impl(
    metadata: dict[str, Any],
    *,
    mode: str,
    prefix: str = "",
) -> tuple[dict[str, Any], int, list[str]]:
    """Core recursive sanitizer shared by ``redact_metadata`` and ``remove_metadata``.

    Parameters
    ----------
    metadata : dict
        The metadata dict to sanitize.
    mode : str
        ``"redact"`` → replace sensitive fields with ``[REDACTED]``.
        ``"remove"`` → omit sensitive fields entirely.
    prefix : str
        Dot-path prefix for tracking redacted paths (only meaningful in redact mode).

    Returns
    -------
    (sanitized_dict, redaction_count, redacted_paths)
    """
    sanitized: dict[str, Any] = {}
    count = 0
    paths: list[str] = []

    for key, value in metadata.items():
        current_path = f"{prefix}.{key}" if prefix else key

        if is_sensitive_key(key):
            if mode == "redact":
                sanitized[key] = REDACTED
            # remove mode: skip entire entry
            count += 1
            paths.append(current_path)
        elif isinstance(value, dict):
            sub, sub_count, sub_paths = _sanitize_metadata_impl(
                value, mode=mode, prefix=current_path
            )
            sanitized[key] = sub
            count += sub_count
            paths.extend(sub_paths)
        elif isinstance(value, list):
            sub, sub_count, sub_paths = _sanitize_list_impl(value, mode=mode, prefix=current_path)
            sanitized[key] = sub
            count += sub_count
            paths.extend(sub_paths)
        elif is_sensitive_value(value):
            if mode == "redact":
                sanitized[key] = REDACTED
            # remove mode: skip entire entry
            count += 1
            paths.append(current_path)
        else:
            sanitized[key] = value

    return sanitized, count, paths


# ── public API ────────────────────────────────────────────────────────────


def redact_metadata(
    metadata: dict[str, Any],
    prefix: str = "",
) -> tuple[dict[str, Any], int, list[str]]:
    """Redact sensitive fields, replacing them with ``[REDACTED]``.

    Returns ``(sanitized_dict, redaction_count, redacted_paths)``.
    Used by repository audit/diff/rollback and any caller that needs to
    preserve field presence while hiding values.
    """
    return _sanitize_metadata_impl(metadata, mode="redact", prefix=prefix)


def remove_metadata(metadata: dict[str, object]) -> dict[str, object]:
    """Remove sensitive fields entirely from *metadata*.

    Returns a new dict with sensitive keys and values omitted.
    Used by ``ProcessingProfile.to_api_dict()`` for API response payloads.
    """
    result, _count, _paths = _sanitize_metadata_impl(metadata, mode="remove")
    return result  # type: ignore[return-value]


def redact_state(
    state: dict[str, Any],
    metadata_key: str = "metadata_json",
) -> dict[str, Any]:
    """Redact sensitive fields from a state dict for audit logging.

    Top-level sensitive keys are redacted.  The *metadata_key* field (default
    ``"metadata_json"``) is recursively redacted via ``redact_metadata``.
    When any redactions happened, a ``_redaction`` key is added with
    ``count`` and ``paths``.
    """
    sanitized: dict[str, Any] = {}
    redaction_count = 0
    redacted_paths: list[str] = []

    for key, value in state.items():
        if is_sensitive_key(key):
            sanitized[key] = REDACTED
            redaction_count += 1
            redacted_paths.append(key)
        elif key == metadata_key and isinstance(value, dict):
            sub, sub_count, sub_paths = redact_metadata(value, prefix=metadata_key)
            sanitized[key] = sub
            redaction_count += sub_count
            redacted_paths.extend(sub_paths)
        else:
            sanitized[key] = value

    if redaction_count > 0:
        sanitized["_redaction"] = {
            "count": redaction_count,
            "paths": redacted_paths,
        }

    return sanitized


__all__ = [
    "REDACTED",
    "SENSITIVE_KEY_PARTS",
    "SENSITIVE_VALUE_PREFIXES",
    "is_sensitive_key",
    "is_sensitive_value",
    "redact_metadata",
    "redact_state",
    "remove_metadata",
]
