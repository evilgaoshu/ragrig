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

from dataclasses import dataclass
from typing import Any

REDACTED = "[REDACTED]"
DEGRADED = "[DEGRADED: depth limit exceeded]"
DEFAULT_MAX_DEPTH = 100

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


@dataclass(frozen=True)
class SanitizationSummary:
    """Structured summary of sanitization actions.

    This summary is safe to log or return via APIs because it never includes
    raw secret values, full original text, large field values, or reprs of
    non-serializable keys.
    """

    schema_version: str = "1.0"
    redacted_count: int = 0
    removed_count: int = 0
    degraded_count: int = 0
    non_string_key_count: int = 0
    max_depth_exceeded: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "redacted_count": self.redacted_count,
            "removed_count": self.removed_count,
            "degraded_count": self.degraded_count,
            "non_string_key_count": self.non_string_key_count,
            "max_depth_exceeded": self.max_depth_exceeded,
        }


@dataclass
class _SummaryAccumulator:
    """Mutable accumulator used during recursive traversal."""

    schema_version: str = "1.0"
    redacted_count: int = 0
    removed_count: int = 0
    degraded_count: int = 0
    non_string_key_count: int = 0
    max_depth_exceeded: bool = False

    def to_summary(self) -> SanitizationSummary:
        return SanitizationSummary(
            schema_version=self.schema_version,
            redacted_count=self.redacted_count,
            removed_count=self.removed_count,
            degraded_count=self.degraded_count,
            non_string_key_count=self.non_string_key_count,
            max_depth_exceeded=self.max_depth_exceeded,
        )


def is_sensitive_key(key: object) -> bool:
    """Return True if *key* contains any known sensitive key part (case-insensitive).

    Non-string keys are treated as non-sensitive (return ``False``) to avoid
    ``AttributeError`` on unexpected key types such as ``int``, ``None``, or
    ``tuple``.
    """
    if not isinstance(key, str):
        return False
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
    max_depth: int = DEFAULT_MAX_DEPTH,
    current_depth: int = 0,
    summary: _SummaryAccumulator | None = None,
) -> tuple[list[Any], _SummaryAccumulator, list[str]]:
    """Recurse into a list, applying the chosen *mode*."""
    sanitized: list[Any] = []
    paths: list[str] = []
    acc = summary if summary is not None else _SummaryAccumulator()

    for idx, item in enumerate(items):
        item_path = f"{prefix}[{idx}]"
        if isinstance(item, dict):
            if current_depth + 1 >= max_depth:
                acc.max_depth_exceeded = True
                acc.degraded_count += 1
                if mode == "redact":
                    sanitized.append(DEGRADED)
                    acc.redacted_count += 1
                    paths.append(item_path)
                # remove mode: skip the item
                continue
            sub, sub_acc, sub_paths = _sanitize_metadata_impl(
                item,
                mode=mode,
                prefix=item_path,
                max_depth=max_depth,
                current_depth=current_depth + 1,
                summary=acc,
            )
            sanitized.append(sub)
            paths.extend(sub_paths)
        elif isinstance(item, list):
            if current_depth + 1 >= max_depth:
                acc.max_depth_exceeded = True
                acc.degraded_count += 1
                if mode == "redact":
                    sanitized.append(DEGRADED)
                    acc.redacted_count += 1
                    paths.append(item_path)
                # remove mode: skip the item
                continue
            sub, sub_acc, sub_paths = _sanitize_list_impl(
                item,
                mode=mode,
                prefix=item_path,
                max_depth=max_depth,
                current_depth=current_depth + 1,
                summary=acc,
            )
            sanitized.append(sub)
            paths.extend(sub_paths)
        elif is_sensitive_value(item):
            if mode == "redact":
                sanitized.append(REDACTED)
                acc.redacted_count += 1
            else:
                acc.removed_count += 1
            # "remove" mode skips the item
            paths.append(item_path)
        else:
            sanitized.append(item)

    return sanitized, acc, paths


def _sanitize_metadata_impl(
    metadata: dict[str, Any],
    *,
    mode: str,
    prefix: str = "",
    max_depth: int = DEFAULT_MAX_DEPTH,
    current_depth: int = 0,
    summary: _SummaryAccumulator | None = None,
) -> tuple[dict[str, Any], _SummaryAccumulator, list[str]]:
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
    max_depth : int
        Maximum recursion depth.  When exceeded the subtree is replaced with
        ``DEGRADED`` (redact) or omitted (remove).
    current_depth : int
        Current recursion depth (used internally).
    summary : _SummaryAccumulator | None
        Mutable summary accumulator. When provided, counts are merged in-place
        to support flat accumulation across recursive calls.

    Returns
    -------
    (sanitized_dict, summary_accumulator, redacted_paths)
    """
    sanitized: dict[str, Any] = {}
    paths: list[str] = []
    acc = summary if summary is not None else _SummaryAccumulator()

    if max_depth <= 0:
        # Top-level depth limit of 0 means we can't inspect anything.
        acc.max_depth_exceeded = True
        acc.degraded_count += 1
        if mode == "redact":
            sanitized[prefix or "_root"] = DEGRADED
            acc.redacted_count += 1
            paths.append(prefix or "_root")
        return sanitized, acc, paths

    for key, value in metadata.items():
        current_path = f"{prefix}.{key}" if prefix else str(key)

        if not isinstance(key, str):
            acc.non_string_key_count += 1

        if is_sensitive_key(key):
            if mode == "redact":
                sanitized[key] = REDACTED
                acc.redacted_count += 1
            else:
                acc.removed_count += 1
            paths.append(current_path)
        elif isinstance(value, dict):
            if current_depth + 1 >= max_depth:
                acc.max_depth_exceeded = True
                acc.degraded_count += 1
                if mode == "redact":
                    sanitized[key] = DEGRADED
                    acc.redacted_count += 1
                    paths.append(current_path)
                # remove mode: skip the key
                continue
            sub, sub_acc, sub_paths = _sanitize_metadata_impl(
                value,
                mode=mode,
                prefix=current_path,
                max_depth=max_depth,
                current_depth=current_depth + 1,
                summary=acc,
            )
            sanitized[key] = sub
            paths.extend(sub_paths)
        elif isinstance(value, list):
            if current_depth + 1 >= max_depth:
                acc.max_depth_exceeded = True
                acc.degraded_count += 1
                if mode == "redact":
                    sanitized[key] = DEGRADED
                    acc.redacted_count += 1
                    paths.append(current_path)
                # remove mode: skip the key
                continue
            sub, sub_acc, sub_paths = _sanitize_list_impl(
                value,
                mode=mode,
                prefix=current_path,
                max_depth=max_depth,
                current_depth=current_depth + 1,
                summary=acc,
            )
            sanitized[key] = sub
            paths.extend(sub_paths)
        elif is_sensitive_value(value):
            if mode == "redact":
                sanitized[key] = REDACTED
                acc.redacted_count += 1
            else:
                acc.removed_count += 1
            paths.append(current_path)
        else:
            sanitized[key] = value

    return sanitized, acc, paths


# ── public API ────────────────────────────────────────────────────────────


def redact_metadata(
    metadata: dict[str, Any],
    prefix: str = "",
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> tuple[dict[str, Any], int, list[str], SanitizationSummary]:
    """Redact sensitive fields, replacing them with ``[REDACTED]``.

    Returns ``(sanitized_dict, redaction_count, redacted_paths, summary)``.
    Used by repository audit/diff/rollback and any caller that needs to
    preserve field presence while hiding values.
    """
    result, acc, paths = _sanitize_metadata_impl(
        metadata, mode="redact", prefix=prefix, max_depth=max_depth
    )
    return result, acc.redacted_count, paths, acc.to_summary()


def remove_metadata(
    metadata: dict[str, object],
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> tuple[dict[str, object], SanitizationSummary]:
    """Remove sensitive fields entirely from *metadata*.

    Returns ``(new_dict, summary)`` where *new_dict* has sensitive keys and
    values omitted.  Used by ``ProcessingProfile.to_api_dict()`` for API
    response payloads.
    """
    result, acc, _paths = _sanitize_metadata_impl(metadata, mode="remove", max_depth=max_depth)
    return result, acc.to_summary()


def redact_state(
    state: dict[str, Any],
    metadata_key: str = "metadata_json",
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> dict[str, Any]:
    """Redact sensitive fields from a state dict for audit logging.

    Top-level sensitive keys are redacted.  The *metadata_key* field (default
    ``"metadata_json"``) is recursively redacted via ``redact_metadata``.
    When any redactions happened, a ``_redaction`` key is added with
    ``count`` and ``paths``.  A ``_sanitization_summary`` key is always added
    with the structured summary.
    """
    sanitized: dict[str, Any] = {}
    redaction_count = 0
    redacted_paths: list[str] = []
    summary = _SummaryAccumulator()

    for key, value in state.items():
        if is_sensitive_key(key):
            sanitized[key] = REDACTED
            redaction_count += 1
            summary.redacted_count += 1
            redacted_paths.append(str(key))
        elif key == metadata_key and isinstance(value, dict):
            sub, sub_count, sub_paths, sub_summary = redact_metadata(
                value, prefix=metadata_key, max_depth=max_depth
            )
            sanitized[key] = sub
            redaction_count += sub_count
            redacted_paths.extend(sub_paths)
            # Merge sub-summary into top-level summary
            summary.redacted_count += sub_summary.redacted_count
            summary.removed_count += sub_summary.removed_count
            summary.degraded_count += sub_summary.degraded_count
            summary.non_string_key_count += sub_summary.non_string_key_count
            summary.max_depth_exceeded = (
                summary.max_depth_exceeded or sub_summary.max_depth_exceeded
            )
        else:
            sanitized[key] = value

    if redaction_count > 0:
        sanitized["_redaction"] = {
            "count": redaction_count,
            "paths": redacted_paths,
        }

    # Always attach the structured summary for observability
    sanitized["_sanitization_summary"] = summary.to_summary().to_dict()

    return sanitized


__all__ = [
    "REDACTED",
    "DEGRADED",
    "DEFAULT_MAX_DEPTH",
    "SENSITIVE_KEY_PARTS",
    "SENSITIVE_VALUE_PREFIXES",
    "SanitizationSummary",
    "is_sensitive_key",
    "is_sensitive_value",
    "redact_metadata",
    "redact_state",
    "remove_metadata",
]
