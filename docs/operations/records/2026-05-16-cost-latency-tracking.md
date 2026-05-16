# Cost and Latency Tracking Across Pipeline and Model Changes

Date: 2026-05-16

## Summary

Implemented deterministic cost/latency tracking for model-facing pipeline stages:

- Indexing now records per-embedding token estimates, cost estimates, and latency in embedding metadata.
- Pipeline run items and indexing run snapshots now include aggregate cost/latency summaries.
- Retrieval reports include query embedding latency, dense/hybrid/rerank phase latencies, model operation usage, and aggregate totals.
- Answer reports include retrieval and answer generation phase latencies plus combined operation usage.
- `GET /observability/cost-latency` summarizes recent pipeline runs and tracked operation totals.
- Web Console pipeline run cards surface stored latency, token, and cost summaries.
- `make cost-latency-check` produces deterministic offline evidence.

## Evidence

Primary commands:

```bash
make cost-latency-check
uv run pytest tests/test_cost_latency_tracking.py -q
make lint
make test
```

Primary artifact:

```text
docs/operations/artifacts/cost-latency-check.json
```

## Notes

Cost values are estimates, not billing records. Local deterministic providers use a zero-cost rate card; unknown cloud model rates are represented with `missing_rate` while still recording comparable token and latency movement.
