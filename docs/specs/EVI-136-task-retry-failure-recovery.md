# EVI-136 Task Retry and Failure Recovery

This spec extends the EVI-132 task observability contract from "visible failure" to
operator-triggered recovery. The current implementation remains in-process and does not
introduce Redis, Celery, ARQ, automatic backoff, a dead-letter queue, or background retry
scheduling.

## Retry vs Replay

- Retry is an explicit recovery action for a failed logical task attempt. It preserves
  the previous `TaskRecord` and `PipelineRun`, creates a new `TaskRecord`, and creates a
  new `PipelineRun` when the task owns pipeline-run state.
- Replay means starting the same business operation from the public API again, such as a
  new upload request or a new ingestion DAG request. Replay is not implemented by
  `POST /tasks/{task_id}/retry` because it would duplicate user intent and may require a
  fresh file upload.
- Retry history is linear. A task can have at most one `next_task_id`; subsequent recovery
  must target the latest failed retry task instead of branching from an older task.

## HTTP API

`POST /tasks/{task_id}/retry` is the minimal retry operation entrypoint.

Successful retry returns `202`:

```json
{
  "task_id": "new-task-id",
  "previous_task_id": "old-task-id",
  "pipeline_run_id": "new-pipeline-run-id",
  "status": "pending"
}
```

Rejected retry returns a structured error:

```json
{
  "error": "task_not_retryable",
  "message": "A retry task already exists for this task.",
  "retryable": false
}
```

`GET /tasks/{task_id}` remains backward compatible and adds these fields:

- `attempt_count`: logical attempt ordinal for this task chain. The first run increments
  from `0` to `1`; a retry child is created with the previous attempt count and increments
  when it starts, so the first retry becomes `2`.
- `retryable`: true when the task is in a supported failed state and has no successor.
- `last_error`: the bounded task traceback for hard failures, or the DAG failure reason for
  `completed_with_failures` DAG attempts.
- `previous_task_id`: the prior task in the retry chain, when this task is a retry.
- `next_task_id`: the retry child, once one has been created.

All fields are additive. Existing `task_id`, `status`, `result`, `error`, `started_at`,
`finished_at`, `progress`, and optional `pipeline_run` response shapes are preserved.

## Retryable Failures

Supported retry cases:

- `pipeline_dag_ingestion` tasks whose task status is `completed` and whose result status
  is `completed_with_failures`. Retry creates a fresh ingestion DAG `PipelineRun` from the
  stored normalized request and clears the test-only `failure_node` injection.
- `knowledge_base_upload` tasks whose task status is `failed` and whose staged upload files
  still exist on disk.

Rejected cases:

- unknown task id: `404 task_not_found`.
- unsupported task type: `409 task_not_retryable`.
- a task with any `next_task_id`: `409 task_not_retryable`.
- running or pending tasks: `409 task_not_retryable`.
- completed upload tasks, including `completed_with_failures` pipeline evidence: not
  retryable through task retry because the user-facing upload operation already completed.
- failed upload tasks whose staging files were already cleaned: not retryable through task
  retry; the operator must replay the upload with fresh files.

## Idempotency and Concurrency

The retry idempotency key is stored in the retry child payload as:

```text
{task_type}:{previous_task_id}:{new_pipeline_run_id}
```

The public idempotency boundary is the `previous_task_id` to `next_task_id` link on the
previous task. While the process is alive, retry creation is guarded by an in-process lock
keyed by the previous task id. The database payload link prevents a second retry after the
first retry has been created. This is sufficient for the current single-process executor.

A future external worker or multi-process API must preserve the same linear-chain contract
with a database-enforced compare-and-set or unique retry edge so two API processes cannot
create sibling retries for one task.

## TaskRecord and PipelineRun Synchronization

Retry never rewrites the historical failure evidence:

- the previous `TaskRecord.status`, `result_json`, `error`, `attempt_count`, `started_at`,
  and `finished_at` remain unchanged.
- the previous `PipelineRun.status`, counters, `error_message`, DAG snapshot, and failure
  queue remain unchanged.
- the previous task payload receives only additive recovery links: `next_task_id` and
  `next_pipeline_run_id`.
- the retry child payload receives `previous_task_id`, `previous_pipeline_run_id`, and
  `retry_idempotency_key`.

The retry child owns its own task lifecycle. Its `PipelineRun` is created before enqueue
and transitions independently when the retry job executes.

## Staging Files

Upload staging files are not deleted by the retry endpoint. Existing upload cleanup
behavior is preserved:

- successful upload parsing and indexing cleans staging files.
- upload parsing failures retain staging files for diagnosis.
- upload indexing failures may clean staging files after parsing succeeded, making task
  retry unavailable; the operator must replay the upload with fresh files.

The endpoint checks every stored staged file path before accepting upload retry. Missing
files make the task non-retryable.

## Executor Limits and Future Worker Contract

The current `ThreadPoolTaskExecutor` is process-local. It provides no cross-process locks,
durable queue, delayed scheduling, or cancellation. Retry is therefore an operator action
that submits another in-process job.

Future Redis, Celery, ARQ, or equivalent workers must preserve:

- additive task response fields.
- monotonic logical `attempt_count`.
- one retry successor per task.
- immutable historical `TaskRecord` and `PipelineRun` failure evidence.
- the same retry rejection semantics for unsupported, active, duplicate, and missing-input
  tasks.
