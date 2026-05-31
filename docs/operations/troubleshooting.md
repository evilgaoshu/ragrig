# RAGRig Troubleshooting Runbook

This runbook is for production and staging operators investigating API,
retrieval, indexing, task-queue, and database issues.

## First Checks

1. Check `/health`.
   - `status=healthy` means the API process, database check, reranker policy,
     and task backend health are acceptable.
   - `db=error` means the app cannot complete `SELECT 1` against the configured
     database URL.
   - `redis.status=skipped` is expected when `RAGRIG_TASK_BACKEND=threadpool`.
   - `redis.status=error` with `RAGRIG_TASK_BACKEND=arq` means Redis or the ARQ
     dependency is unavailable and the response is HTTP 503.
2. Check `/metrics`.
   - HTTP latency and status metrics confirm whether failures are route-local
     or process-wide.
   - Retrieval metrics show hit, zero-result, degraded, and error counts.
   - DB pool metrics show connection pressure and invalidation events.
3. Check logs by request ID.
   - Every API response includes `X-Request-ID`.
   - JSON logs include request context plus OpenTelemetry trace/span IDs when
     tracing is enabled.

## API 500s

Symptoms:
- `/metrics` shows `ragrig_http_requests_total{status_code="500"}` increasing.
- Clients receive `{"error":{"code":"internal_server_error"}}`.

Actions:
- Use the response `X-Request-ID` to find `api.request.failed` in logs.
- Check the matching trace for route, SQLAlchemy spans, and business spans.
- Confirm the global handler did not expose the traceback to clients; traceback
  detail should remain in server logs only.

## Database Pressure

Metrics:
- `ragrig_db_pool_checked_out`
- `ragrig_db_pool_checked_in`
- `ragrig_db_pool_overflow`
- `ragrig_db_pool_invalidations_total`

Actions:
- If checked-out connections stay near pool size, inspect slow API routes and
  long indexing tasks.
- If overflow rises steadily, increase database pool capacity only after
  confirming PostgreSQL can accept the extra connections.
- If invalidations rise, inspect database restarts, network interruptions, and
  connection lifetime settings.

## Redis / ARQ Tasks

Symptoms:
- `/health` returns HTTP 503 with `redis.status=error`.
- `POST /sources/run-ingest` or upload routes enqueue tasks but workers do not
  make progress.

Actions:
- Confirm `RAGRIG_TASK_BACKEND=arq` is intentional.
- Check `RAGRIG_REDIS_URL` from the app and worker environments.
- Start or restart the worker with `arq ragrig.worker.WorkerSettings`.
- If Redis is not required for the deployment, switch back to
  `RAGRIG_TASK_BACKEND=threadpool`.

## Retrieval Problems

Symptoms:
- zero-result spikes in `ragrig_retrieval_requests_total`.
- degraded spikes in `ragrig_retrieval_degraded_total`.
- user-visible retrieval answers without evidence.

Actions:
- Compare `mode`, `backend`, and optional hashed workspace series in metrics.
- Check business spans:
  - `ragrig.retrieval.search`
  - `ragrig.retrieval.embed_query`
  - `ragrig.retrieval.vector_search`
  - `ragrig.retrieval.rerank`
- If vector search is fast but results are zero, confirm the knowledge base is
  indexed with the same embedding provider/model/dimensions as the request.
- If rerank is degraded in production, configure a real reranker or explicitly
  allow the fake reranker fallback only for accepted demos.

## Indexing Problems

Symptoms:
- pipeline runs finish with failures.
- retrieval is healthy but new documents never appear.

Actions:
- Check pipeline run items for parser, chunking, embedding, or upsert failures.
- Check business spans:
  - `ragrig.indexing.knowledge_base`
  - `ragrig.indexing.chunk`
  - `ragrig.indexing.embed`
  - `ragrig.indexing.upsert`
- If embedding spans dominate latency, reduce batch pressure or inspect provider
  health and rate limits.
- If upsert spans fail, inspect vector backend health and DB pool metrics.

## Workflow Retries

Workflow steps support exponential retry backoff with:
- `max_retries`
- `retry_backoff_seconds`
- `retry_backoff_multiplier`

Actions:
- Use small backoff values for deterministic local workflows.
- Use non-zero backoff for remote connectors and model-dependent steps.
- If every retry fails immediately, inspect credentials and network reachability
  before increasing retry counts.

## Useful PromQL

```
sum by (path, status_code) (rate(ragrig_http_requests_total[5m]))
histogram_quantile(0.95, sum by (le, path) (rate(ragrig_http_request_duration_seconds_bucket[5m])))
sum by (endpoint, mode, backend, status) (rate(ragrig_retrieval_requests_total[5m]))
ragrig_db_pool_checked_out
increase(ragrig_db_pool_invalidations_total[15m])
```
