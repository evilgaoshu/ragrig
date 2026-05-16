# RAGRig Cost and Latency Tracking Spec

Status: implemented
Date: 2026-05-16

## Scope

RAGRig records deterministic cost and latency telemetry for pipeline/model changes without requiring a database migration. The first implemented surfaces are indexing, retrieval, answer generation, pipeline run summaries, and a deterministic offline smoke artifact.

## Metrics

Each tracked model operation records:

- `operation`
- `provider`
- `model`
- estimated input/output/total tokens
- estimated input/output/total cost in USD
- `rate_source`
- `latency_ms`
- optional safe metadata

Token counts are estimated with a deterministic character heuristic. Built-in local providers (`deterministic-local`, BGE, fake reranker) use a zero-cost rate source. Unknown cloud rates are tracked with `missing_rate` so operators can still compare token and latency movement without pretending to have billing truth.

## Storage

No schema migration is required:

- Indexing stores per-embedding telemetry in `embeddings.metadata_json.cost_latency`.
- Indexing stores document and run aggregates in pipeline run item metadata and `pipeline_runs.config_snapshot_json.cost_latency_summary`.
- Retrieval and answer APIs include `cost_latency` in response payloads.
- Pipeline run listing and detail include duration and any stored `cost_latency_summary`.

## API

```text
GET /observability/cost-latency?knowledge_base=<name>&limit=<n>
```

The endpoint returns recent pipeline run duration, stored cost/latency summaries, and aggregate token/cost/latency totals across tracked runs.

## Evidence

```bash
make cost-latency-check
```

The deterministic smoke creates an ephemeral SQLite knowledge base, ingests and indexes a local fixture, runs retrieval and answer generation, and verifies that all surfaces contain cost/latency telemetry.
