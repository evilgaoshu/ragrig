# EVI-106 Ingestion DAG Runner v1

## Scope

`ingestion-dag/v1` adds a local, persisted DAG summary over the existing ingestion and indexing
pipelines. It is not a generic workflow platform, distributed queue, or scheduler. Existing
secret-free local ingestion smoke remains unchanged.

## DAG Nodes

The node order is fixed:

1. `ingest`: scan the local source root and summarize discovered/skipped inputs.
2. `parse`: run the existing local ingestion parser path and persist document versions.
3. `chunk`: expose the explicit chunk planning boundary for the indexed knowledge base.
4. `embed`: expose the deterministic local embed provider boundary.
5. `index`: run the existing chunk/embedding/index persistence path.

Each node snapshot includes `node_id`, `status`, `duration_ms`, `input_summary`,
`output_summary`, and `error`. A pipeline run response includes `failed_node` when execution
halts.

## State Transitions

Node statuses are `pending`, `running`, `completed`, `failed`, or `skipped`. The v1 runner
executes in topological order and stops at the first failed node. Later nodes remain `pending`.

The owning `PipelineRun` uses:

- `running` while a DAG execution/resume is active.
- `completed` when all nodes are completed.
- `completed_with_failures` when the failure queue contains an open node failure.

Resume on a completed DAG, a running DAG, a non-DAG run, or a stale snapshot returns an explicit
`rejected` response with `degraded=true`; it never reports a silent success.

## Idempotency And Resume

The config snapshot stores a SHA-256 `idempotency_key` over the request fields. Resume reuses the
same snapshot and skips nodes already marked `completed`. Existing ingestion version hashing and
indexing `already_indexed` detection remain the artifact-level idempotence fences, so repeated
resume does not duplicate document versions, chunks, or embeddings already committed by a prior
completed node.

`snapshot_expired=true` marks the config stale and blocks resume with `reason=stale_snapshot`.

## Retry And Failure Queue

`dag.failure_queue` records `{node_id, reason, status, retryable, retry_count}`. A deterministic
fixture failure can be injected for `parse`, `embed`, or `index` for local tests and smoke. The
fixture is consumed on first failure, leaving resume able to exercise controlled retry. Resume
moves an open item through `retrying` and then `resolved`; a repeat resume after completion returns
`reason=duplicate_retry`.

The existing per-item retry API remains available for historical local/fileshare/S3 ingestion
pipeline items. DAG resume is deliberately run-level because node failures are run-level.

## API And Console

- `POST /pipeline-dags/ingestion` starts a local DAG run.
- `GET /pipeline-runs` and `GET /pipeline-runs/{id}` expose `dag` snapshots.
- `POST /pipeline-runs/{id}/dag-resume` resumes the first incomplete DAG node.

The console pipeline list shows the node statuses, failure queue reason/status, and a Resume DAG
entry point for failed DAG runs. Rejected resumes are displayed as rejected instead of success.

## Secret Boundary

The DAG request and output summaries reject raw values stored under secret-like keys (`api_key`,
`access_key`, `secret`, `token`, `password`, `private_key`, `credential`) unless the value is an
`env:` reference. Console-facing summaries redact known key and bearer/private-key fragments and
truncate errors. The DAG snapshot does not resolve or persist credential values.

## Acceptance Smoke

`make pipeline-dag-smoke` runs a deterministic local SQLite fixture, injects an `embed` failure,
resumes it, and writes `docs/operations/artifacts/pipeline-dag-smoke.json`.
