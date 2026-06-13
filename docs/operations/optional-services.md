# Optional services — env reference

The `.env.example` shipped at the repo root only documents the variables most
users need for `docker compose up`. The optional services below stay quiet
unless their compose profile is activated; if you opt in, copy the matching
block into your `.env`.

## S3-compatible object storage (`--profile minio` or external S3)

```
AWS_ACCESS_KEY_ID=minioadmin
AWS_SECRET_ACCESS_KEY=minioadmin123
AWS_SESSION_TOKEN=
S3_BUCKET=ragrig-smoke
S3_PREFIX=ragrig-smoke
S3_ENDPOINT_URL=http://127.0.0.1:9000
S3_REGION=us-east-1
S3_USE_PATH_STYLE=true
S3_VERIFY_TLS=false
MINIO_API_HOST_PORT=9000
MINIO_CONSOLE_HOST_PORT=9001
```

Activate the local MinIO sidecar with `docker compose --profile minio up -d`.

## Qdrant vector backend (`--profile qdrant`)

```
VECTOR_BACKEND=qdrant
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=
QDRANT_HOST_PORT=6333
QDRANT_GRPC_PORT=6334
```

Bring it up with `docker compose --profile qdrant up -d qdrant`.

## Production hardening

Production mode rejects a missing auth pepper. Set an environment-specific
secret before running with `APP_ENV=production`:

```
APP_ENV=production
RAGRIG_AUTH_SECRET_PEPPER=replace-with-a-long-random-secret
```

Password login brute-force throttling is enabled by default. The limiter uses
an in-process IP + normalized-email hash and never labels metrics with raw
email, IP, user, or session identifiers.

```
RAGRIG_AUTH_LOGIN_RATE_LIMIT_ENABLED=true
RAGRIG_AUTH_LOGIN_MAX_FAILURES=5
RAGRIG_AUTH_LOGIN_WINDOW_SECONDS=300
RAGRIG_AUTH_LOGIN_LOCKOUT_SECONDS=900
```

The default compose file adds `restart: unless-stopped` to services and applies
resource limits to the primary app and database containers. Override these
defaults in `.env` when the host capacity differs:

```
RAGRIG_APP_MEM_LIMIT=2g
RAGRIG_APP_CPUS=2.0
RAGRIG_DB_MEM_LIMIT=2g
RAGRIG_DB_CPUS=2.0
```

Health probes are split by purpose:
- `/health/live` checks only that the API process is alive.
- `/health/ready` checks database and task backend readiness.
- `/health` is kept as a readiness-compatible alias for existing deployments.

## Production observability

Prometheus metrics are enabled by default and exposed at `/metrics`.
Application-level metrics include HTTP request latency/status, retrieval
hit/zero/degraded counts, retrieval result counts, and estimated model
operation token/cost/latency totals.
Database pool metrics are also exposed as low-cardinality process metrics:
`ragrig_db_pool_size`, `ragrig_db_pool_checked_in`,
`ragrig_db_pool_checked_out`, `ragrig_db_pool_overflow`,
`ragrig_db_pool_checkouts_total`, `ragrig_db_pool_checkins_total`, and
`ragrig_db_pool_invalidations_total`.

Workspace-hash business metrics are available as a separate optional series.
Keep them disabled unless the Prometheus cardinality is acceptable for your
deployment. When enabled, RAGRig emits `*_by_workspace` metrics with
`workspace="ws_<sha256-prefix>"` labels instead of raw workspace IDs.

When OpenTelemetry is enabled, RAGRig emits business spans for retrieval and
indexing phases, including query embedding, vector search, rerank, chunking,
embedding batches, and vector upsert. Span attributes use counts, backend
names, provider/model metadata, and hashed workspace/knowledge-base labels
only.
HTTPX client instrumentation is also enabled with OpenTelemetry so OIDC,
webhook, connector, web import, and provider calls appear as outbound spans.
Install the OTel SDKs with `uv sync --extra otel` before setting
`RAGRIG_OTEL_ENABLED=true`; without the extra, tracing is skipped with a
startup warning.

Langfuse trace export is also opt-in and separate from OpenTelemetry. It emits
high-level summaries for retrieval search, answer generation, and evaluation
runs; query text, answer text, and hidden provider configs are not sent by the
adapter.

```bash
uv sync --extra observability-langfuse
export RAGRIG_LANGFUSE_ENABLED=true
export RAGRIG_LANGFUSE_HOST=https://cloud.langfuse.com
export RAGRIG_LANGFUSE_PUBLIC_KEY=pk-lf-...
export RAGRIG_LANGFUSE_SECRET_KEY=sk-lf-...
```

If the package or credentials are missing, requests continue normally and the
adapter records a stable degraded diagnostic.

Ingestion and indexing pipeline metrics are low-cardinality counters and
histograms:
`ragrig_pipeline_runs_total`, `ragrig_pipeline_items_total`,
`ragrig_pipeline_duration_seconds`, `ragrig_indexing_documents_total`,
`ragrig_indexing_chunks_total`, and `ragrig_indexing_embeddings_total`.
They use labels such as `pipeline_type`, `stage`, and `status`; document names,
knowledge-base names, user IDs, and file paths are intentionally excluded.

File logs are deliberately opt-in. In containers, stdout/stderr remains the
portable default because most orchestrators own log collection and rotation. If
you want compose-managed rotating log files, copy this block into `.env`:

```
RAGRIG_METRICS_ENABLED=true
RAGRIG_METRICS_WORKSPACE_LABELS_ENABLED=false
RAGRIG_LOG_FORMAT=json
RAGRIG_LOG_LEVEL=INFO
RAGRIG_LOG_FILE=/app/logs/ragrig.jsonl
RAGRIG_LOG_MAX_BYTES=10485760
RAGRIG_LOG_BACKUP_COUNT=5
```

`docker-compose.yml` mounts `/app/logs` to the `ragrig_logs` volume. The
application creates the parent directory and rotates the file according to
`RAGRIG_LOG_MAX_BYTES` and `RAGRIG_LOG_BACKUP_COUNT`.

PostgreSQL SQLAlchemy pool sizing is configurable and ignored for SQLite test
URLs:

```
RAGRIG_DB_POOL_SIZE=10
RAGRIG_DB_MAX_OVERFLOW=20
RAGRIG_DB_POOL_RECYCLE=1800
```

## ARQ / Redis task queue

The default task backend is the in-process threadpool. Redis is only required
when `RAGRIG_TASK_BACKEND=arq` and a worker is running.

```
RAGRIG_TASK_BACKEND=arq
RAGRIG_REDIS_URL=redis://redis:6379
RAGRIG_TASK_QUEUE_MAX_JOBS=10
```

When the ARQ backend is active, `/health/ready` and `/health` ping Redis and report
`redis.status="connected"` or returns HTTP 503 with `redis.status="error"`.
With the default threadpool backend, Redis health is reported as `skipped`.

ARQ/Redis only backs background task execution. It does not make the API request
rate limiter shared across workers or replicas; use an API gateway policy,
Redis-backed limiter, or equivalent shared limiter for multi-process
deployments.

## Fileshare live smoke (`--profile fileshare-live`)

```
SMB_HOST_PORT=1445
WEBDAV_HOST_PORT=8080
SFTP_HOST_PORT=2222
```

Used by `make fileshare-live-up` to spin up Samba/WebDAV/SFTP containers for
the live connector smoke. Off by default.

## Answer live smoke (local LLM diagnostics)

```
RAGRIG_ANSWER_LIVE_SMOKE=1
RAGRIG_ANSWER_PROVIDER=ollama
RAGRIG_ANSWER_MODEL=llama3.2:1b
RAGRIG_ANSWER_BASE_URL=http://localhost:11434/v1
```

Off by default — the deterministic-local provider answers requests without
any external runtime. Override when you want to validate against a real LLM
on the host.

## RAGAS evaluation adapter

RAGAS is optional because it pulls in a larger evaluation stack. Install it only
on runners where RAGAS metrics should be computed:

```bash
uv sync --extra eval-ragas
```

Then set `ragas_enabled=true` on `POST /evaluations/runs`. Per-question results
appear under `items[].evaluation_adapters.ragas` with metrics such as
`faithfulness`, `context_precision`, `context_recall`, and
`answer_relevancy` when the adapter can compute them. Missing packages or
runtime adapter errors are reported as `status="degraded"` and do not fail the
evaluation run.

## Discord source connector

The Discord source uses the Discord REST API through the existing `httpx`
dependency; no Discord SDK is required.

```json
{
  "bot_token": "env:DISCORD_BOT_TOKEN",
  "guild_id": "123456789012345678",
  "channel_ids": ["234567890123456789"],
  "include_threads": true,
  "oldest_days": 30,
  "page_size": 100,
  "max_messages_per_channel": 500
}
```

`bot_token` supports `env:VAR` references and should never be committed as a
literal secret. The bot needs access to the target channels and message history.
Messages are aggregated into one text file per channel or active thread before
they enter the normal ingestion pipeline.
