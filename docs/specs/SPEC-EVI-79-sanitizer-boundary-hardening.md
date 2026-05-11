# SPEC-EVI-79: ProcessingProfile Sanitizer Boundary Hardening

**Version:** 1.0  
**Date:** 2026-05-11  
**Issue:** [EVI-79](mention://issue/70e7cda6-04a9-4c66-b08a-a5094b474f2e)

---

## 1. Objective

Make `ProcessingProfile` metadata sanitizer robust against two classes of boundary inputs:

1. **Non-string metadata keys** (`int`, `None`, `tuple`, etc.) — previously caused unhandled `AttributeError`.
2. **Abnormally deep nesting** — previously caused unhandled `RecursionError` when nesting exceeded Python's recursion limit.

---

## 2. Non-String Key Strategy

### Decision
Non-string keys are treated as **non-sensitive** (`is_sensitive_key` returns `False`).

### Rationale
- JSON/Python dicts allow arbitrary hashable keys. Coercing everything to `str` would risk false positives (e.g., integer `1` vs. string `"1"`).
- Sensitivity detection is inherently semantic and string-oriented (substring matching against key names like `api_key`).
- Silently ignoring non-string keys is the safest degradation: we preserve data availability and never accidentally redact legitimate fields.

### Impact on Callers
| Caller | Behavior |
|--------|----------|
| `redact_metadata` | Non-string keys are preserved; values under them are recursively sanitized normally. |
| `remove_metadata` | Non-string keys are preserved; values under them are recursively sanitized normally. |
| `redact_state` | Non-string top-level keys are preserved. |
| `_sanitize_metadata` (model) | Same as `remove_metadata`. |
| `_sanitize_metadata_json` (repository) | Same as `redact_metadata`. |

---

## 3. Recursion Depth Boundary

### Decision
A configurable `max_depth` parameter is added to all sanitizer functions with a **default of 100**.

### Rationale
- Python default recursion limit is 1000. A default of 100 provides a 10x safety margin while being far deeper than any realistic ProcessingProfile metadata structure (existing tests top out at ~4 levels).
- The limit is configurable so callers with legitimately deep structures can opt into a higher ceiling.

### Degraded Behavior When Exceeded

| Mode | Behavior | Path Marker |
|------|----------|-------------|
| **Redact** | The subtree is replaced with `[DEGRADED: depth limit exceeded]`. | The path to the exceeded node is recorded in `redacted_paths`. |
| **Remove** | The subtree is **omitted entirely** (key or list item is dropped). | No path is recorded (consistent with normal removal semantics). |

### Impact on Callers
All three call sites are updated:

1. **`ragrig.processing_profile.sanitizer`** — source of truth; `redact_metadata`, `remove_metadata`, `redact_state` accept `max_depth`.
2. **`ragrig.processing_profile.models._sanitize_metadata`** — added `max_depth` and `current_depth` parameters; defaults match sanitizer.
3. **`ragrig.repositories.processing_profile`** — thin wrappers already delegate to sanitizer; no code change needed.

---

## 4. Constants

| Constant | Value | Meaning |
|----------|-------|---------|
| `DEFAULT_MAX_DEPTH` | `100` | Default recursion ceiling for all sanitizer functions. |
| `DEGRADED` | `"[DEGRADED: depth limit exceeded]"` | Marker inserted when `max_depth` is hit in redact mode. |
| `REDACTED` | `"[REDACTED]"` | Unchanged. Marker for sensitive key/value redaction. |

---

## 5. Test Coverage

New tests are added in `tests/test_processing_profile_sanitizer.py`:

| Test | Validates |
|------|-----------|
| `test_is_sensitive_key_non_string_returns_false[...]` | `is_sensitive_key` does not raise on `int`, `None`, `tuple`, `float`, `bool`, `list`. |
| `test_redact_metadata_with_non_string_keys` | Non-string keys survive redaction; string sensitive keys are still redacted. |
| `test_remove_metadata_with_non_string_keys` | Same for removal mode. |
| `test_redact_metadata_nested_with_non_string_keys` | Non-string keys in nested dicts work correctly. |
| `test_remove_metadata_nested_with_non_string_keys` | Same for removal mode. |
| `test_redact_metadata_does_not_recurse_error_on_deep_input` | 1500-level nesting completes without `RecursionError`. |
| `test_remove_metadata_does_not_recurse_error_on_deep_input` | Same for removal mode. |
| `test_redact_metadata_custom_max_depth` | Low `max_depth` produces `DEGRADED` marker at expected path. |
| `test_remove_metadata_custom_max_depth` | Low `max_depth` omits subtrees beyond limit. |
| `test_redact_metadata_degraded_in_list` | Depth limit inside lists produces `DEGRADED` item. |
| `test_remove_metadata_degraded_in_list` | Depth limit inside lists omits the item. |
| `test_model_sanitize_metadata_does_not_recurse_error` | Model wrapper survives 1500-level nesting. |
| `test_repository_sanitize_metadata_json_does_not_recurse_error` | Repository wrapper survives 1500-level nesting. |
| `test_model_sanitize_metadata_non_string_keys` | Model wrapper handles non-string keys. |
| `test_repository_sanitize_metadata_json_non_string_keys` | Repository wrapper handles non-string keys. |

---

## 6. Out of Scope (as per issue)

- Full DLP/PII detection.
- API schema changes.
- Historical data migration.
- Real LLM execution.

---

## 7. Verification Commands

```bash
make lint      # ruff check — PASS
make test      # pytest — 887 passed, 9 skipped
make coverage  # pytest --cov — 98.95% total
make web-check # pytest tests/test_web_console.py — 90 passed
```
