# EVI-139 Retry Multiprocess Idempotency

EVI-139 hardens `POST /tasks/{task_id}/retry` for more than one API process and for future
external workers. The public API remains compatible with EVI-136.

## Durable Retry Edge

Retry history is a linear task chain. The durable edge is represented in structured
`task_records` columns:

- `previous_task_id`: set on the retry child, unique when non-null.
- `next_task_id`: set on the previous task, unique when non-null.
- `retry_idempotency_key`: set on the retry child, unique when non-null.

The idempotency key source is deterministic:

```text
{task_type}:{previous_task_id}
```

It intentionally excludes the new pipeline run id because racing retry attempts would
otherwise generate different keys for the same user intent.

## Invariants

- One failed task can create at most one retry child.
- A retry child can be linked from at most one previous task.
- `previous_task_id` and `next_task_id` cannot point to the same task row.
- `attempt_count` is non-negative and monotonic: the child starts with the previous count
  and increments only when the child task transitions to `running`.
- The previous task and previous pipeline run keep their failure evidence. Retry may add
  recovery links, but must not rewrite previous `status`, `result_json`, `error`,
  `attempt_count`, timestamps, pipeline counters, DAG snapshots, or failure queue.

The JSON payload still mirrors retry links for existing response serialization and
diagnostics. The structured columns and unique constraints are the source of truth for
multi-process idempotency.

## Worker Compatibility

An external worker or queue adapter may enqueue or execute the retry child, but it must
create the child through the same database contract. If two processes race for the same
failed task, one insert wins and the other must surface the same duplicate retry rejection
used by the HTTP API; it must not create a sibling successor or overwrite failure history.
