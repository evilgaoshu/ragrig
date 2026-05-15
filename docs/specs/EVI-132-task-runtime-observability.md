# EVI-132 Task Runtime Observability

## Scope

This document defines the current in-process task runtime contract and the compatibility boundary that a future Redis, Celery, ARQ, or equivalent external worker must preserve. The current runtime remains intentionally lightweight: FastAPI creates a `ThreadPoolTaskExecutor`, persists every accepted task in `task_records`, and exposes task state through `GET /tasks/{task_id}`.

## State Model

Task state is monotonic for one attempt:

```text
pending -> running -> completed
                  \-> failed
```

- `pending`: the task record has been committed, but the executor has not started the job.
- `running`: the job wrapper is executing. `started_at` is set on the first transition to this state and `attempt_count` is incremented.
- `completed`: the runner returned successfully. `result` stores the runner result and `finished_at` is set.
- `failed`: the runner raised. `error` stores a traceback summary capped at 2000 characters and `finished_at` is set.

Tasks are not retried automatically. Any future retry feature must create a new attempt boundary explicitly and keep `attempt_count` monotonic.

## TaskRecord Shape

`task_records` stores the durable task envelope:

- `id`: task UUID returned as `task_id`.
- `status`: one of `pending`, `running`, `completed`, or `failed`.
- `task_type`: stable runtime type, for example `web_upload_indexing` or `pipeline_dag_ingestion`.
- `payload_json`: request payload and correlation IDs. Payloads must be JSON serializable and must not contain raw secrets.
- `result_json`: JSON result for completed tasks, or `null`.
- `error`: traceback summary for failed tasks, or `null`; the API caps task failure summaries at 2000 characters.
- `started_at`: nullable timestamp set when execution starts.
- `finished_at`: nullable timestamp set on completed or failed.
- `progress`: nullable JSON progress object. Current runtime uses `{"current": N, "total": M, "message": "..."}`.
- `attempt_count`: integer reserved for retry observability; current first execution increments it from 0 to 1.

## API Contract

`GET /tasks/{task_id}` returns:

```json
{
  "task_id": "4db41a5f-0f67-4d58-95bf-4b8d54bf2a3c",
  "status": "completed",
  "result": {"pipeline_run_id": "589fb2ba-449e-44fa-81b1-a806efc74387"},
  "error": null,
  "started_at": "2026-05-15T15:30:00.123456+00:00",
  "finished_at": "2026-05-15T15:30:01.234567+00:00",
  "progress": {"current": 1, "total": 1, "message": "Task completed."}
}
```

Existing fields and status codes remain compatible. New fields are additive. `GET /tasks/{task_id}?include=pipeline_run` may include a `pipeline_run` summary when `payload_json.pipeline_run_id` points to an existing run.

## Failure Diagnosis

The task wrapper is responsible for failure capture:

- On exception, the task is marked `failed`.
- `TaskRecord.error` receives a bounded traceback summary, preserving the exception type and message.
- Upload indexing failures mark the associated `PipelineRun` as `failed` before the exception escapes the runner.
- DAG task execution stores node-level failures in the DAG snapshot. A task is marked failed only when the runner raises; partial DAG node failures that return a report remain a completed task with a failed or degraded pipeline report in `result`.
- Upload staging files are retained only when file-level ingestion failures require inspection. Successful runs and executor-level failures clean up staging files through the existing runner `finally` path.

## Concurrency

`ThreadPoolTaskExecutor` uses a process-local `ThreadPoolExecutor` with four workers by default. It provides no cross-process deduplication, distributed locking, or durability beyond `task_records`. Knowledge-base indexing is serialized per knowledge base with an in-process lock to avoid concurrent index writes for the same knowledge base.

Deployments that run multiple API processes may execute tasks in each process. Until an external worker is introduced, production deployments should prefer one API worker process for task-producing routes or route all task execution to one process.

## Shutdown

`TaskExecutor.shutdown(wait: bool = True)` is part of the runtime interface. FastAPI app shutdown calls it with `wait=True`, allowing accepted in-flight jobs to complete before process exit. `ThreadPoolTaskExecutor.shutdown(wait=False)` is available for forceful shutdown and cancels futures that have not yet started; running Python threads cannot be interrupted safely.

External workers must preserve this behavior at the API boundary:

- graceful shutdown waits for acknowledged in-flight work or safely requeues it;
- forceful shutdown must not silently report abandoned tasks as completed;
- after shutdown begins, new submissions should be rejected by the underlying executor.

## External Worker Migration Boundary

A Redis, Celery, ARQ, or similar runtime may replace the in-process executor if it preserves:

- `POST /knowledge-bases/{kb_name}/upload` returns `202` with `task_id` and `pipeline_run_id`.
- `POST /pipeline-dags/ingestion` returns `202` with `task_id` and `pipeline_run_id`.
- `GET /tasks/{task_id}` keeps existing fields and additive observability fields.
- State transitions remain `pending -> running -> completed/failed`.
- `TaskRecord.error` remains a bounded diagnostic string with exception type/message context.
- `PipelineRun.status` remains synchronized with failed task execution for upload indexing failures.
- Payload and result bodies remain JSON serializable and free of raw secrets.

Recommended migration path:

1. Keep `TaskExecutor.submit(job)` as the API-facing boundary.
2. Replace local callable execution with enqueueing a named task plus serialized payload.
3. Move runner lookup into worker code while writing the same `TaskRecord` lifecycle updates.
4. Keep the API read path backed by `task_records` so clients do not change.
