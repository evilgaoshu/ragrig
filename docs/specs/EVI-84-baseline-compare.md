# SPEC: Retrieval Benchmark Baseline Comparison & Regression Report

## Issue

[EVI-84](mention://issue/2c86ffda-842f-4066-bba9-2e3eadbb740b)

## Goal

Enable objective, automated detection of latency and result-count drift in the retrieval benchmark by comparing a current run against a versioned baseline and emitting a structured JSON regression report.

## Baseline Identity & Path

- **Default path:** `docs/benchmarks/retrieval-benchmark-baseline.json`
- **Override:**
  - CLI arg: `--baseline <path>`
  - Environment variable: `BENCHMARK_BASELINE_PATH`
- The baseline is the canonical artifact produced by `scripts/retrieval_benchmark.py` and checked into the repo. It is deterministic (fixture data, no network/GPU/torch/BGE).
- Legacy compatibility boundary: baselines generated before EVI-111 may carry path-derived `fixture_id` values tied to a checkout absolute path. Treat those artifacts as historical snapshots only; refresh them with `make retrieval-benchmark-baseline-refresh` before interpreting a `fixture_id mismatch` as a new regression.

## Comparison Schema

The report is a JSON object with the following structure:

```json
{
  "knowledge_base": "fixture-local",
  "baseline_path": "docs/benchmarks/retrieval-benchmark-baseline.json",
  "latency_threshold_pct": 20,
  "result_count_threshold": 5,
  "overall_status": "pass",
  "overall_reason": "",
  "modes": [
    {
      "mode": "dense",
      "current": {"p50_latency_ms": 1.5, "p95_latency_ms": 5.0},
      "baseline": {"p50_latency_ms": 1.2, "p95_latency_ms": 4.0},
      "delta": {"p50_latency_ms": 25.0, "p95_latency_ms": 25.0},
      "result_count_delta": 0,
      "status": "fail",
      "reason": "p50 latency regression 25.0% > threshold 20%"
    }
  ]
}
```

### Field semantics

| Field | Type | Description |
|---|---|---|
| `knowledge_base` | string | Knowledge base name (from current run, fallback to baseline). |
| `baseline_path` | string | Resolved absolute or relative path to the baseline file. |
| `latency_threshold_pct` | number | Max allowed latency increase (%) before `fail`. |
| `result_count_threshold` | number | Max allowed absolute `result_count` drift before `fail`. |
| `overall_status` | string | Aggregated status across all modes: `pass`, `fail`, `degraded`, or `failure`. |
| `overall_reason` | string | Human-readable summary of all failures/degradations. Empty when `pass`. |
| `modes` | array | One entry per mode present in baseline or current. |

#### Per-mode entry

| Field | Type | Description |
|---|---|---|
| `mode` | string | Retrieval mode (`dense`, `hybrid`, `rerank`, `hybrid_rerank`). |
| `current` | object | `p50_latency_ms` and `p95_latency_ms` from the current run. |
| `baseline` | object | `p50_latency_ms` and `p95_latency_ms` from the baseline. |
| `delta` | object | Percentage change for p50 and p95 relative to baseline. |
| `result_count_delta` | int | `current.result_count - baseline.result_count`. |
| `status` | string | `pass`, `fail`, or `degraded`. |
| `reason` | string | Specific failure/degradation reason(s), semicolon-separated. |

### Status rules

1. **Missing/corrupt baseline** → `overall_status` = `failure` (global), no per-mode comparison attempted.
2. **Missing mode in baseline or current** → mode `status` = `fail`, reason names the missing side.
3. **Benchmark-level `degraded` flag** (from current run) → mode `status` = `degraded` (if no threshold violations).
4. **p50 or p95 delta > `latency_threshold_pct`** → mode `status` = `fail`.
5. **abs(`result_count_delta`) > `result_count_threshold`** → mode `status` = `fail`.
6. **None of the above** → mode `status` = `pass`.

`overall_status` aggregation:
- If any mode is `fail` → `fail`.
- Else if any mode is `degraded` → `degraded`.
- Else → `pass`.

Manifest preflight note:

- `scripts.retrieval_benchmark_compare._check_manifest_compatibility()` rejects known snapshot-only legacy `fixture_id` values before normal fixture comparison.
- Failure text: `legacy path-derived fixture_id detected: 'X'; this snapshot-only artifact must be refreshed via make retrieval-benchmark-baseline-refresh before reuse as an active baseline`.
- This check is covered by the default `pytest` suite (`make test`, `make coverage`) and remains reproducible manually via `make retrieval-benchmark-compare`.

### Delta calculation

```
p50_delta_pct = ((current_p50 - baseline_p50) / baseline_p50) * 100
p95_delta_pct = ((current_p95 - baseline_p95) / baseline_p95) * 100
```

If baseline latency is `0`, delta is `0` when current is also `0`, otherwise `inf`.

## Threshold Configuration

| Threshold | CLI flag | Environment variable | Default |
|---|---|---|---|
| Latency regression | `--latency-threshold-pct` | `BENCHMARK_LATENCY_THRESHOLD_PCT` | `20` (%) |
| Result count drift | `--result-count-threshold` | `BENCHMARK_RESULT_COUNT_THRESHOLD` | `5` (absolute) |

CLI args take precedence over env vars.

## Sanitization Boundary

The compare report is passed through the existing `_sanitize_summary()` function from `scripts/retrieval_benchmark.py` before JSON serialization. This redacts values whose keys contain any of the following substrings (case-insensitive):

- `api_key`, `access_key`, `secret`, `password`, `token`, `credential`, `private_key`, `dsn`, `service_account`, `session_token`

No secrets are expected in benchmark data, but this ensures the compare script inherits the same safety guarantees as the benchmark script.

## CLI & Make Entrypoint

```bash
# Run benchmark on the fly and compare against default baseline
make retrieval-benchmark-compare

# Compare an existing benchmark file
uv run python -m scripts.retrieval_benchmark_compare --current benchmark.json

# Override baseline and thresholds
BENCHMARK_BASELINE_PATH=/tmp/baseline.json \
BENCHMARK_LATENCY_THRESHOLD_PCT=15 \
BENCHMARK_RESULT_COUNT_THRESHOLD=3 \
  uv run python -m scripts.retrieval_benchmark_compare
```

Exit codes:
- `0` when `overall_status` is `pass`.
- `1` when `overall_status` is `fail`, `degraded`, or `failure`.

## Dependencies

- No network, GPU, torch, or real BGE required by default.
- When `--current` is omitted, the script invokes `run_benchmarks()` using the fixture-local knowledge base (SQLite, deterministic embeddings).

## Out of Scope

- Required CI gate (this script is informational, not blocking).
- Production load-test or monitoring alerting.
- Cloud storage upload.
- Evaluation quality gate (see EVI-77).
- Web Console delta badge (best-effort, future work).
- CI artifact upload (best-effort, future work).

## Changelog

| Version | Date | Author | Change |
|---|---|---|---|
| 1.1 | 2026-05-14 | DEV-mac-oc | Document legacy snapshot-only `fixture_id` preflight failure, refresh guidance, and default pytest coverage. |
| 1.0 | 2026-05-11 | DEV-opencode-gpt5.4 | Initial SPEC for EVI-84. |
