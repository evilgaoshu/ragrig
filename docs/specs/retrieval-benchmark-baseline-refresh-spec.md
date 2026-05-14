# SPEC: Retrieval Benchmark Baseline Refresh & Drift Calibration

**Version**: 1.2  
**Schema Version**: `1.0`  
**Date**: 2026-05-11  
**Status**: Approved

---

## 1. Objective

Provide a reproducible, versioned baseline mechanism for the retrieval benchmark so that:

- Baselines can be refreshed deterministically from offline fixture data.
- Drift reports are trustworthy (no false positives caused by fixture or iteration changes).
- Every baseline carries a manifest that makes compatibility checks explicit.

---

## 2. Baseline Refresh Flow

```
make retrieval-benchmark-baseline-refresh
```

1. Run `scripts.retrieval_benchmark.run_benchmarks()` against the offline fixture `tests/fixtures/local_ingestion`.
2. Compute a manifest (see §3) from the resulting benchmark data.
3. Embed the manifest under `_manifest` in the baseline JSON.
4. Write the baseline JSON to `docs/benchmarks/retrieval-benchmark-baseline.json`.
5. Write the standalone manifest to `docs/benchmarks/retrieval-benchmark-baseline.manifest.json`.
6. Sanitize both outputs with `_sanitize_summary()` to strip secret-like values.

No network, GPU, torch, or BGE dependency is required.

---

## 3. Manifest Schema

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | `string` | Manifest schema version. Current: `"1.0"`. |
| `baseline_id` | `string` | UUID v4 generated at refresh time. |
| `fixture_id` | `string` | SHA-256 truncated to 16 chars. Covers relative fixture file paths plus file bytes, and excludes checkout absolute paths. Known snapshot-only legacy IDs are rejected for active baseline reuse. |
| `iteration_count` | `integer` | `iterations_per_query` used when the baseline was generated. |
| `modes` | `list[string]` | Ordered list of mode names present in the baseline (e.g. `["dense", "hybrid", "rerank", "hybrid_rerank"]`). |
| `metrics_hash` | `string` | SHA-256 truncated to 16 chars of the canonical metrics structure (modes, top_k, candidate_k, iterations, result_count, degraded flags). **Latency values are intentionally excluded** because they are volatile. |
| `created_at` | `string` | ISO-8601 UTC timestamp (`YYYY-MM-DDTHH:MM:SSZ`). |
| `generator_version` | `string` | RAGRig package version (falls back to `"0.1.0"`). |

---

## 4. Compatibility Rules

When `make retrieval-benchmark-compare` runs, the compare script performs a manifest compatibility check **before** any latency drift analysis.

A baseline is **incompatible** if any of the following is true:

| Check | Failure Reason |
|-------|----------------|
| Baseline has no `_manifest` | `baseline missing _manifest: run baseline refresh first` |
| `schema_version` ≠ expected (`1.0`) | `schema_version mismatch: baseline 'X' != expected '1.0'` |
| Baseline `fixture_id` is a known snapshot-only legacy ID | `legacy path-derived fixture_id detected: 'X'; this snapshot-only artifact must be refreshed via make retrieval-benchmark-baseline-refresh before reuse as an active baseline` |
| `fixture_id` ≠ current fixture | `fixture_id mismatch: baseline 'X' != current 'Y' (refresh baseline: older manifests may have path-derived fixture IDs)` |
| `iteration_count` ≠ current run | `iteration_count mismatch: baseline N != current M` |
| `metrics_hash` ≠ recomputed hash | `metrics_hash mismatch: baseline 'X' != current 'Y' (metrics structure changed)` |

When incompatibility is detected:
- `overall_status` = `"failure"`
- `overall_reason` = the specific mismatch reason
- Exit code = `1`
- No per-mode latency drift comparison is performed.

This guarantees that fixture/iteration/schema changes never produce a misleading `pass`.

Guard coverage note:

- `scripts.retrieval_benchmark_baseline_refresh._compute_fixture_id()` hashes only relative fixture paths plus file bytes; checkout absolute paths are excluded.
- `scripts.retrieval_benchmark_compare._check_manifest_compatibility()` rejects known legacy path-derived snapshot IDs before normal fixture compatibility checks.
- The guard is read-only and does not rewrite historical snapshot artifacts already stored in `docs/benchmarks/` or `docs/operations/artifacts/`.

---

## 5. Threshold Semantics

### 5.1 Latency Threshold

- Field: `latency_threshold_pct`
- Default (Makefile): `500 %`
- Rationale: Local sqlite benchmarks on shared development machines exhibit high p95 variance. The default is intentionally lenient to avoid false failures in local development. CI pipelines should override via `BENCHMARK_LATENCY_THRESHOLD_PCT` (e.g. `20` for stable hardware).
- A mode fails when **either** p50 or p95 delta exceeds this threshold.

### 5.2 Result-Count Threshold

- Field: `result_count_threshold`
- Default: `5` (absolute)
- A mode fails when `|current.result_count - baseline.result_count| > threshold`.

### 5.3 Degraded Propagation

- If the current benchmark sets `degraded: true` but latencies and result counts are within thresholds, the mode status is `"degraded"` (not `"fail"`).
- If degradation **and** a threshold violation coexist, the mode status is `"fail"`.

---

## 6. Sanitization Boundaries

Both refresh and compare pipelines call `scripts.retrieval_benchmark._sanitize_summary()` before JSON serialization.

### 6.1 Redaction Rules

Any dict key (case-insensitive) containing any of the following substrings is redacted to `"[redacted]"`:

- `api_key`
- `access_key`
- `secret`
- `password`
- `token`
- `credential`
- `private_key`
- `dsn`
- `service_account`
- `session_token`

### 6.2 Scope

- Redaction is **recursive** through nested dicts and lists.
- Values are redacted **in place**; the key names are preserved so consumers know a value was hidden.
- The baseline and compare outputs must never contain API keys, tokens, secrets, or complete private configs.

### 6.3 Verification

Unit tests verify that:
- Secret-like keys are redacted.
- Non-secret keys (e.g. `query`, `model`, `email`, `url`) remain visible.
- Nested lists are sanitized.
- Redaction is case-insensitive.

---

## 7. Makefile Targets

| Target | Purpose |
|--------|---------|
| `make retrieval-benchmark-baseline-refresh` | Generate a fresh baseline + manifest from offline fixtures. |
| `make retrieval-benchmark-compare` | Compare current fixture benchmark against the stored baseline. |

Environment overrides:
- `BENCHMARK_BASELINE_PATH` — custom baseline file path.
- `BENCHMARK_LATENCY_THRESHOLD_PCT` — override latency threshold.
- `BENCHMARK_RESULT_COUNT_THRESHOLD` — override result-count threshold.

Default verification coverage:

- `make test` and `make coverage` run the retrieval benchmark refresh/compare/integrity unit tests, including the legacy `fixture_id` guard regression cases.
- `make lint` does not execute the guard; it only validates source formatting and linting.
- `make web-check` validates the Web Console integrity consumer but does not directly execute the compare preflight failure path.
- `make retrieval-benchmark-compare` and `make retrieval-benchmark-integrity-artifact` remain the dedicated operator entrypoints for reproducing the failure and warning messages against real artifacts.

---

## 8. Out-of-Scope

The following are explicitly **not** required by this SPEC:

- Required CI gate enforcement.
- Cloud storage or BI integration.
- Real BGE / GPU / torch execution in the benchmark path.
- Production load testing or alerting.

---

## 9. Best-Effort Items

- **Web Console badge**: Display baseline `created_at` and an integrity indicator (green when manifest compatibility passes, red otherwise).
- **CI artifact upload**: Upload `docs/benchmarks/retrieval-benchmark-baseline.manifest.json` as a pipeline artifact so historical manifests can be audited.

---

## 10. Changelog

| Version | Date | Change |
|---------|------|--------|
| 1.2 | 2026-05-14 | EVI-117: document default verification coverage, clarify dedicated compare/integrity entrypoints, and note that legacy snapshot-only fixture IDs are rejected from active baseline reuse. |
| 1.1 | 2026-05-13 | EVI-111: redefine `fixture_id` as content-derived identity (relative paths + file bytes), excluding checkout absolute paths; add legacy baseline refresh guidance. |
| 1.0 | 2026-05-11 | Initial SPEC: manifest schema, compatibility rules, threshold semantics, sanitization boundaries. |
