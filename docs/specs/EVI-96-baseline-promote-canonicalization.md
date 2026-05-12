# SPEC: Baseline Promote JSON Canonicalization

## Issue

[EVI-96](mention://issue/4b1718b8-ddee-458b-b75f-73daa09e4cce)

## Goal

Eliminate false `hash_mismatch` errors caused by missing default metric fields when `promote_run_to_baseline` writes a baseline JSON and computes its integrity hash. The disk representation of metrics must match the canonical form used for hash computation, and the API surface must never leak raw prompts, `config_snapshot`, `items`, or secret-like values.

## Canonicalization Rules

1. **Canonical metrics dict** — All metrics input is normalized through `EvaluationMetrics.model_validate().model_dump()` (Pydantic v2). This ensures every field (including those with default values such as `0.0`, `None`, or factory-produced dicts) is present in the output.
2. **Extra fields** — Fields present in the input that are not defined on `EvaluationMetrics` are silently dropped (Pydantic v2 default `extra="ignore"`).
3. **JSON serialization** — The canonical dict is serialized with:
   - `sort_keys=True`
   - `ensure_ascii=False`
   - `separators=(",", ":")` (compact, no spaces)
4. **Hash algorithm** — SHA-256, hex-encoded, prefixed with `sha256:`.

### Canonical vs. non-canonical example

```python
# Non-canonical input (missing default fields like latency_ms_mean, zero_result_count, etc.)
{"total_questions": 5, "hit_at_1": 0.5}

# Canonical output after model_validate().model_dump()
{
  "total_questions": 5,
  "hit_at_1": 0.5,
  "hit_at_3": 0.0,
  "hit_at_5": 0.0,
  "mrr": 0.0,
  "mean_rank_of_expected": None,
  "citation_coverage_mean": 0.0,
  "zero_result_count": 0,
  "zero_result_rate": 0.0,
  "latency_ms_mean": 0.0,
  "latency_ms_p50": 0.0,
  "latency_ms_p95": 0.0,
  "latency_ms_p99": 0.0,
  "answer_skipped": True,
  "answer_degraded_reason": None,
  "regression_delta_vs_baseline": {
    "hit_at_1": None, "hit_at_3": None, "hit_at_5": None,
    "mrr": None, "mean_rank_of_expected": None,
    "citation_coverage_mean": None, "zero_result_rate": None
  },
  "baseline_label": None
}
```

## Hash Input

The hash is computed from the **canonical metrics dict** alone — never from items, config_snapshot, raw prompts, or other fields. The input to `_compute_metrics_hash` is always the metrics sub-object of the baseline JSON.

### Hash computation flow

```
           ┌─────────────────────────┐
           │  EvaluationMetrics      │
           │  (Pydantic model)       │
           └─────┬───────────────────┘
                 │ model_dump()
                 ▼
           ┌─────────────────────────┐
           │  Canonical dict         │
           │  (all fields present)   │
           └─────┬───────────────────┘
                 │ json.dumps(sort_keys=True, separators=(",", ":"))
                 ▼
           ┌─────────────────────────┐
           │  Compact JSON string    │
           └─────┬───────────────────┘
                 │ sha256().hexdigest()
                 ▼
           ┌─────────────────────────┐
           │  "sha256:<64-hex-chars>" │
           └─────────────────────────┘
```

## Legacy / Backfill Behavior

### Auto-backfill on validation

When `validate_baseline_manifest` is called with `auto_backfill=True` (the default), a missing manifest is auto-generated:
1. The baseline JSON file is read and its `metrics` sub-object extracted.
2. `_compute_metrics_hash` is called on the raw dict → canonicalizes through the model → produces the correct hash.
3. The manifest is written to disk.

Existing baselines promoted before this change may have a non-canonical metrics dict on disk. The auto-backfill path now computes the hash from the canonical dict, producing a valid manifest even if the file's metrics are missing default fields.

### Promote produces canonical file

After this change, `promote_run_to_baseline` replaces `raw["metrics"]` with `run.metrics.model_dump()` before writing the baseline JSON. New baselines always have a canonical metrics dict on disk, matching the hash in the manifest.

### Dry-run backfill command

The `make eval-baseline-backfill-canonical DRY_RUN=1` command scans all existing baselines and reports which ones have non-canonical metrics. Without `DRY_RUN=1`, it rewrites the metrics and regenerates the manifest.

## Secret Boundary

The following guarantees apply to all baseline-related API output:

| Field | Status | Mechanism |
|---|---|---|
| `config_snapshot` | **Stripped** from API responses | `list_baselines()` pops `config_snapshot` before returning |
| `items` | **Stripped** from API responses | `list_baselines()` pops `items` before returning |
| `manifest` | **Stripped** from API responses (integrity_status only) | `list_baselines()` pops `manifest` before returning |
| Secret-like values | **Redacted** at persistence time | `_serialize_run_for_persistence` → `_sanitize_dict` redacts keys matching `api_key`, `password`, `token`, etc. |
| Raw prompts | **Never in baseline** | Baseline only stores metrics, not per-question prompts/items |
| Registry metadata | **Safe** | Registry stores metrics dict (no secrets), golden_set_name, knowledge_base name only |

## Validation

### Integrity check

```
make eval-baseline RUN_ID=<id> BASELINE_ID=<id>
make eval-local --baseline <id>
```

Expected: Exit 0, `integrity_status.status == "valid"`.

### Tamper detection

Manually modifying `hit_at_1` in the baseline JSON file causes:

Expected: Exit 2, `baseline_status.reason == "hash_mismatch"`.

### API output sanitization

```
GET /evaluations/baselines
```

Expected: Response JSON contains no `config_snapshot`, `items`, `manifest`, or secret-like values.

## CLI & Make Entrypoint

```bash
# Promote a run to baseline (with canonical metrics)
make eval-baseline RUN_ID=<uuid> BASELINE_ID=<id>

# Run local evaluation against baseline
make eval-local --baseline <id>

# Dry-run backfill (reports non-canonical baselines only)
make eval-baseline-backfill-canonical DRY_RUN=1

# Apply backfill (rewrites metrics + regenerates manifests)
make eval-baseline-backfill-canonical
```

## Out of Scope

- Cryptographic signing of baselines (not needed for integrity).
- Required CI gate (canonicalization is transparent, no CI changes needed).
- Cloud storage or BI pipeline integration.
- Schema version upgrade (schema stays at `1.0.0`).
- Encryption (secrets are redacted, not encrypted).

## Changelog

| Version | Date | Author | Change |
|---|---|---|---|
| 1.0 | 2026-05-12 | DEV-opencode-gpt5.4 | Initial SPEC for EVI-96. |
