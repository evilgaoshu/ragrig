# EVI-93: Sanitizer Cross-Layer Contract Specification

**Version:** 1.0  
**Date:** 2026-05-11  
**Status:** Approved  
**Scope:** `ragrig.processing_profile.sanitizer` and all downstream callers

---

## 1. Goal

Prevent thin-wrapper drift and summary-field inconsistencies between the canonical sanitizer and its callers in the repository, model, and API layers.

---

## 2. Cross-Layer Contract

### 2.1 Layer Map

| Layer | Module | Role | Allowed Mode |
|-------|--------|------|--------------|
| **sanitizer** | `ragrig.processing_profile.sanitizer` | Canonical implementation | redact, remove |
| **repository** | `ragrig.repositories.processing_profile` | Thin wrappers for audit/diff/rollback | redact |
| **model** | `ragrig.processing_profile.models` | Thin wrapper for `to_api_dict()` | remove |
| **API** | `ProcessingProfile.to_api_dict()` | Serialization boundary | remove (via model) |

### 2.2 Wrapper Boundary Rules

1. **Repository layer** MUST only call `redact_metadata` and `redact_state` from the canonical module. No local re-implementation of recursion logic is permitted.
2. **Model layer** MUST only call `remove_metadata` from the canonical module. The old `_sanitize_metadata` duplicate implementation has been removed and now delegates to `remove_metadata`.
3. **API layer** MUST obtain sanitization results exclusively through `ProcessingProfile.to_api_dict()`, which delegates to `_sanitize_metadata`.
4. **No new sanitizer copy** may be introduced without registration in `scripts/sanitizer_contract_check.py`.

### 2.3 Registered Call Sites

The following function names are the explicitly registered sanitization call sites:

- `_sanitize_metadata_json`
- `_sanitize_state`
- `_is_sensitive_key`
- `_is_sensitive_value`
- `_sanitize_metadata`
- `to_api_dict`
- `build_api_profile_list`
- `build_matrix`

Any additional call site must be added to `REGISTERED_CALL_SITES` in `scripts/sanitizer_contract_check.py`.

---

## 3. Summary Schema

`SanitizationSummary` is the single schema for all layers. It is safe to log or return via APIs because it never includes raw secret values, full original text, large field values, or reprs of non-serializable keys.

### 3.1 Fields

| Field | Type | Meaning |
|-------|------|---------|
| `schema_version` | `str` | Fixed at `"1.0"` |
| `redacted_count` | `int` | Fields replaced with `[REDACTED]` |
| `removed_count` | `int` | Fields omitted entirely |
| `degraded_count` | `int` | Subtrees truncated due to depth limit |
| `non_string_key_count` | `int` | Dict keys that are not `str` |
| `max_depth_exceeded` | `bool` | `True` if any subtree hit the depth ceiling |

### 3.2 Invariants

- `redacted_count > 0` implies the caller used **redact** mode.
- `removed_count > 0` implies the caller used **remove** mode.
- For a given fixture, all remove-mode layers MUST agree on `removed_count`, `degraded_count`, `non_string_key_count`, and `max_depth_exceeded`.
- For a given fixture, all redact-mode layers MUST agree on `redacted_count`, `degraded_count`, `non_string_key_count`, and `max_depth_exceeded`.
- `schema_version` MUST be identical across all layers.

---

## 4. Fixture Contract

The same canonical fixtures MUST produce identical summary counts across all layers.

### 4.1 Fixture Definitions

| Fixture | Description |
|---------|-------------|
| `no_op` | Clean metadata with no sensitive keys or values |
| `non_string_key` | Dict containing `int`, `None`, and `tuple` keys |
| `depth_truncation` | Nested dict deep enough to trigger `max_depth_exceeded` when `max_depth=2` |
| `secret_like` | Mix of `api_key`, `token`, `password`, `Bearer` header, PEM block |
| `remove_redact_mixed` | Mixed nested dicts and lists with both sensitive keys and values |

### 4.2 Test Coverage

All five fixtures are exercised in `tests/test_sanitizer_cross_layer_contract.py` against:

- `redact_metadata` / `remove_metadata` (sanitizer)
- `_sanitize_metadata_json` / `_sanitize_state` (repository)
- `_sanitize_metadata` / `to_api_dict()` (model / API)

---

## 5. De-Sanitization Limits

The contract explicitly defines what outputs MUST NOT contain:

1. **No complete secret values** – e.g. `sk-proj-deadbeef` must never appear in output.
2. **No complete original text** – the original value of a sensitive field must not be preserved.
3. **No large field values** – truncated or redacted; never echoed in full.
4. **No raw repr of non-serializable keys** – `int`, `None`, `tuple` keys are preserved as-is in the sanitized dict but their repr must never leak into the summary.

---

## 6. Depth Safety

- `DEFAULT_MAX_DEPTH = 100`
- Inputs with >1000 nesting levels MUST NOT raise `RecursionError`.
- When depth is exceeded:
  - **redact** mode replaces the subtree with `[DEGRADED: depth limit exceeded]`.
  - **remove** mode omits the subtree entirely.
  - `degraded_count` is incremented and `max_depth_exceeded` is set to `True`.

---

## 7. Executable Contract Check

### 7.1 Command

```bash
make sanitizer-contract-check
```

### 7.2 What It Verifies

1. `SanitizationSummary` exposes all required fields.
2. No unregistered duplicate implementations exist in the source tree.
3. All sanitizer call sites are registered.
4. A fixture smoke contract confirms cross-layer count agreement.

### 7.3 Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All contracts pass |
| 1 | Unregistered copy, missing field, or fixture mismatch |
| 2 | Import / AST error |

---

## 8. CI Integration

The contract matrix can be emitted as a CI artifact by running:

```bash
uv run pytest tests/test_sanitizer_cross_layer_contract.py -s
```

The `-s` flag prints the human-readable contract matrix to stdout.

---

## 9. Change Log

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-05-11 | Initial spec. Fixed `models._sanitize_metadata` to delegate to shared `remove_metadata`. Added cross-layer contract tests and executable checker. |
