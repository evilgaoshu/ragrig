# RAGRig Retrieval Benchmark and BGE Smoke Spec

Issue: EVI-81
Date: 2026-05-10
Status: Implementation spec for DEV

## Scope

This document defines the retrieval performance benchmark command and optional BGE reranker smoke test. The benchmark provides reproducible latency measurements across all retrieval modes (dense, hybrid, rerank, hybrid_rerank) using the deterministic-local embedding provider on a fixture knowledge base.

Included in scope:

- `make retrieval-benchmark` CLI command producing JSON summary
- `make bge-rerank-smoke` optional command with explicit skip-on-missing-deps
- Unit tests for summary schema validation, degraded behavior, and secret-like config filtering
- Web Console "Retrieval Benchmark" panel showing most recent benchmark artifact
- Versioned SPEC document (this file)

Explicitly out of scope:

- Production-scale load/stress testing
- Heavy ML dependency (torch, FlagEmbedding, sentence-transformers) as default
- BGE smoke as a required CI gate
- EVI-77 evaluation quality gates
- Answer generation or prompt assembly

## Authority

This specification is subordinate to:

- `docs/specs/ragrig-mvp-spec.md`
- `docs/specs/ragrig-phase-1d-retrieval-api-spec.md`
- `docs/specs/ragrig-phase-1e-hybrid-retrieval-spec.md`

If this file conflicts with an authority document, the authority documents win.

## Benchmark Design

### Data Source

The benchmark uses the `fixture-local` knowledge base seeded by `tests/fixtures/local_ingestion/`. This directory contains:

- `guide.md` — Markdown document with retrieval-relevant content
- `notes.txt` — Plain text document
- `empty.txt` — Edge case empty document
- `nested/` — Subdirectory for path traversal tests

The fixture is indexed using the `deterministic-local` embedding provider with 8 dimensions, chunk size 500.

### Modes Covered

| Mode | Description | Pipeline |
|------|-------------|----------|
| `dense` | Vector-only retrieval | Embed → cosine distance → top-k |
| `hybrid` | Vector + lexical fusion | Embed → cosine distance → lexical fusion → top-k |
| `rerank` | Dense candidates → reranker | Embed → cosine distance → fake reranker → top-k |
| `hybrid_rerank` | Hybrid → reranker | Embed → cosine distance → lexical fusion → fake reranker → top-k |

All modes use the deterministic `fake_rerank` for reranking. No real BGE model, network, or GPU is required.

### Queries

Five retrieval queries are used to exercise the fixture KB:

1. "retrieval configuration guide"
2. "embedding dimensions"
3. "chunking pipeline"
4. "knowledge base setup"
5. "vector search backend"

Each query is run `iterations` times (default 5) per mode, yielding 25 samples per mode.

### Metrics

| Metric | Description |
|--------|-------------|
| `p50_latency_ms` | 50th percentile (median) of all execution latencies in milliseconds |
| `p95_latency_ms` | 95th percentile latency |
| `min_latency_ms` | Minimum observed latency |
| `max_latency_ms` | Maximum observed latency |
| `mean_latency_ms` | Arithmetic mean latency |
| `result_count` | Total number of results returned across all queries × iterations |
| `degraded` | Boolean: whether any iteration reported degraded state |
| `degraded_reason` | Reason string if degraded |

### Output Schema

```json
{
  "knowledge_base": "fixture-local",
  "queries": ["..."],
  "iterations_per_query": 5,
  "database": "sqlite:///:memory: (temp)",
  "modes": [
    {
      "mode": "dense",
      "top_k": 5,
      "candidate_k": 20,
      "iterations": 25,
      "p50_latency_ms": 1.234,
      "p95_latency_ms": 2.345,
      "min_latency_ms": 0.987,
      "max_latency_ms": 3.456,
      "mean_latency_ms": 1.500,
      "result_count": 125,
      "degraded": false,
      "degraded_reason": ""
    }
  ]
}
```

### Threshold Guidance

These are non-blocking reference values for local development hardware (Apple M-series, 2024-2026). They are informational, not CI gates:

| Mode | p50 < | p95 < |
|------|-------|-------|
| dense | 100ms | 250ms |
| hybrid | 150ms | 350ms |
| rerank | 200ms | 500ms |
| hybrid_rerank | 250ms | 600ms |

On CI runners these thresholds are expected to vary. The benchmark output should be inspected for regressions relative to the baseline artifact committed with this feature, not absolute thresholds.

### Baseline Artifact

The initial benchmark run's JSON output is committed as `docs/benchmarks/retrieval-benchmark-baseline.json`.

Compatibility note: historical baseline snapshots created before EVI-111 may contain legacy `fixture_id` values derived from checkout absolute paths. Those snapshots remain useful for historical latency/result-count review, but they should not be treated as authoritative fixture identity evidence. Refresh with `make retrieval-benchmark-baseline-refresh` before using the baseline for new cross-workspace comparisons or downstream integrity checks.

### Secret-like Config Sanitization

Before output, the summary dict is recursively scanned. Any key containing `api_key`, `access_key`, `secret`, `password`, `token`, `credential`, `private_key`, `dsn`, `service_account`, or `session_token` has its value replaced with `"[redacted]"`. This is verified by unit tests.

## BGE Smoke Test

### Purpose

Verify that the optional BGE reranker model can be loaded and used when the `local-ml` extras are installed. This is NOT a quality benchmark — it only checks that the integration works end-to-end.

### Dependency Check

The smoke test checks for three packages:
- `FlagEmbedding` (provides `BAAI/bge-reranker-base` or similar)
- `sentence-transformers`
- `torch`

If any is missing, the test reports:
```json
{
  "test": "bge_rerank_smoke",
  "status": "skipped",
  "bge_dependencies": {
    "available": false,
    "reason": "Missing dependencies: FlagEmbedding, torch. Install with: uv sync --extra local-ml",
    "missing": ["FlagEmbedding", "torch"]
  },
  "details": {}
}
```

### Degrade During Run

If the BGE model fails to load at runtime (e.g., network required for first download, insufficient memory), `search_knowledge_base` reports `degraded=True`. The smoke test then reports:
```json
{
  "status": "skipped",
  "reason": "BGE reranker reported degraded: ..."
}
```

### Success Condition

The test only reports `status: "success"` when:
1. All dependencies are installed
2. The BGE reranker loads successfully
3. At least one retrieval returns non-degraded results

## Web Console Integration

### Endpoint: `GET /retrieval/benchmark/recent`

Returns the most recent benchmark result as JSON. If no benchmark has been run, returns `{"available": false}`.

The endpoint reads from `docs/benchmarks/retrieval-benchmark-baseline.json`.

### UI Panel

A "Retrieval Benchmark" section in the Web Console displays:
- Most recent benchmark timestamp (from file mtime)
- Per-mode latency summary table (p50, p95)
- Degraded status indicator
- Link to the baseline artifact path

## Unit Test Requirements

### Summary Schema Validation

Tests that the benchmark output JSON conforms to the expected schema:
- Top-level keys: `knowledge_base`, `queries`, `iterations_per_query`, `database`, `modes`
- Each mode entry has: `mode`, `p50_latency_ms`, `p95_latency_ms`, `result_count`, `degraded`
- All latency values are non-negative floats
- `degraded` is boolean
- Four modes present

### Degraded Behavior Tests

Tests that when reranker is configured with an unavailable provider:
- The benchmark still completes (does not crash)
- The `degraded` flag is set to `true`
- The `degraded_reason` is non-empty

### Secret-like Config Sanitization

Tests that the `_sanitize_summary` function:
- Redacts values whose key contains `api_key`, `password`, `token`, etc.
- Does NOT redact values whose key does NOT contain these patterns
- Handles nested dicts and lists

### BGE Smoke Skip Behavior

Tests that `_check_bge_dependencies`:
- Returns `available: false` when dependencies are not installed
- Returns descriptive `reason` and `missing` list
- The smoke test exits with status 0 (not failure) when skipped

## Delivery Checklist

- [x] `make retrieval-benchmark` target in Makefile
- [x] `make bge-rerank-smoke` target in Makefile
- [x] `scripts/retrieval_benchmark.py` implementation
- [x] `scripts/bge_rerank_smoke.py` implementation
- [x] Unit tests for schema, degraded, sanitization
- [x] Web Console endpoint and UI panel
- [x] Baseline artifact committed
- [x] Versioned SPEC document (this file)
- [x] `make lint && make test && make coverage && make web-check` all pass
