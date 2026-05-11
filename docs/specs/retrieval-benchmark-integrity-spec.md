# Retrieval Benchmark Integrity Badge & CI Artifact SPEC

**Version:** 1.0  
**Status:** Draft  
**Issue:** EVI-91

---

## 1. Goal

Provide a visible, machine-readable health indicator for the retrieval benchmark baseline. Reviewers and operators should be able to determine at a glance whether the baseline is fresh, structurally consistent, and schema-compatible.

---

## 2. Badge Fields

The Web Console badge / status card displays the following fields, sourced from `docs/benchmarks/retrieval-benchmark-baseline.manifest.json`:

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | `string` | Manifest schema version (e.g., `"1.0"`) |
| `baseline_age` | `float\|null` | Days since `created_at` in the manifest |
| `fixture_id` | `string\|null` | Stable fixture identifier |
| `iteration_count` | `int\|null` | Number of iterations per query |
| `metrics_hash_status` | `"match" \| "mismatch" \| null` | Whether the recomputed baseline hash matches the manifest |
| `overall_status` | `"pass" \| "degraded" \| "failure"` | Aggregate health verdict |

---

## 3. Artifact Schema

The CI artifact is written to `docs/operations/artifacts/retrieval-benchmark-integrity.json`.

```json
{
  "artifact": "retrieval-benchmark-integrity",
  "generated_at": "2026-05-11T12:00:00+00:00",
  "schema_version": "1.0",
  "baseline_age": 12.34,
  "fixture_id": "eb323cc73a16db53",
  "iteration_count": 5,
  "metrics_hash_status": "match",
  "overall_status": "pass",
  "reasons": [],
  "manifest_present": true,
  "baseline_present": true
}
```

### Field definitions

| Field | Type | Description |
|-------|------|-------------|
| `artifact` | `string` | Fixed value `"retrieval-benchmark-integrity"` |
| `generated_at` | `string` | ISO 8601 timestamp when the check ran |
| `schema_version` | `string\|null` | Manifest schema version |
| `baseline_age` | `float\|null` | Days since `created_at` |
| `fixture_id` | `string\|null` | Fixture identifier |
| `iteration_count` | `int\|null` | Iterations per query |
| `metrics_hash_status` | `string\|null` | `"match"`, `"mismatch"`, or `null` |
| `overall_status` | `string` | `"pass"`, `"degraded"`, or `"failure"` |
| `reasons` | `list[string]` | Human-readable reason strings for degraded/failure |
| `manifest_present` | `bool` | Whether the manifest file was found |
| `baseline_present` | `bool` | Whether the baseline file was found |

---

## 4. Degraded / Failure Reason Enumeration

### Failure reasons (non-recoverable)

| Reason code | Trigger | Example message |
|-------------|---------|-----------------|
| `manifest_missing` | Manifest file does not exist | `manifest_missing: manifest file not found` |
| `manifest_corrupt` | Manifest is invalid JSON or not an object | `manifest_corrupt: invalid JSON (...)` |
| `baseline_missing` | Baseline file does not exist | `baseline_missing: baseline file not found` |
| `baseline_corrupt` | Baseline is invalid JSON or not an object | `baseline_corrupt: invalid JSON (...)` |
| `schema_incompatible` | `schema_version` != supported version | `schema_incompatible: expected 1.0, got 2.0` |

### Degraded reasons (recoverable / actionable)

| Reason code | Trigger | Example message |
|-------------|---------|-----------------|
| `baseline_stale` | Age exceeds threshold | `baseline_stale: age 45.2 days exceeds threshold 30 days` |
| `baseline_age_invalid` | `created_at` missing or unparsable | `baseline_age_invalid: created_at is missing or unparsable` |
| `metrics_hash_mismatch` | Recomputed hash != manifest hash | `metrics_hash_mismatch: manifest says abc123, computed def456` |
| `metrics_hash_missing` | `metrics_hash` field absent from manifest | `metrics_hash_missing: metrics_hash not in manifest` |

### Status precedence

1. If any **failure** reason exists → `overall_status = "failure"`
2. Else if any **degraded** reason exists → `overall_status = "degraded"`
3. Else → `overall_status = "pass"`

---

## 5. Desensitization (Secret Redaction) Boundary

The integrity checker must **never** emit raw secret values in its output.

### Redaction rules

- Keys containing any of the following substrings are redacted to `"[redacted]"`:
  - `api_key`, `access_key`, `secret`, `password`, `token`, `credential`, `private_key`, `dsn`, `service_account`, `session_token`
- Redaction is applied recursively to nested dicts and lists.
- Redaction happens **before** the result is returned or written to disk.

### Test coverage

- Unit tests verify that injecting secret-like keys into manifest or baseline does not leak them in the output.

---

## 6. Configuration

| Environment variable | Default | Description |
|----------------------|---------|-------------|
| `BENCHMARK_BASELINE_MAX_AGE_DAYS` | `30` | Maximum acceptable baseline age in days |
| `BENCHMARK_INTEGRITY_ARTIFACT_PATH` | `docs/operations/artifacts/retrieval-benchmark-integrity.json` | Default artifact output path (used by Makefile) |

---

## 7. Makefile Targets

```makefile
retrieval-benchmark-integrity-artifact:
	$(UV) run python -m ragrig.retrieval_benchmark_integrity \
		--pretty --output $(ARTIFACTS_DIR)/retrieval-benchmark-integrity.json
```

- Exit code `0` when `overall_status != "failure"`
- Exit code `1` when `overall_status == "failure"`
- This is **not** a required CI gate; it is informational.

---

## 8. Web Console Integration

### Endpoint

- `GET /retrieval/benchmark/integrity`
- Returns a lightweight JSON summary safe for browser rendering.

### UI

- A new status card appears in the top status strip labeled **"Baseline Integrity"**.
- A new panel **"Retrieval Baseline Integrity"** appears below the existing **"Retrieval Benchmark"** panel.
- The panel shows:
  - Overall status pill (pass/degraded/failure)
  - Fact grid with schema version, baseline age, fixture ID, iteration count, metrics hash status, and checked-at timestamp (with tooltip for raw ISO time)
  - Reason cards when degraded/failure reasons exist

---

## 9. Out of Scope

- CI required gate (exit code is advisory)
- Cloud storage / BI integration
- Real BGE/GPU/torch execution
- Production alerting

---

## 10. Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-05-11 | Initial SPEC for EVI-91 |
