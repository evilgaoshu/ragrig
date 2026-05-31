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

## ARQ / Redis task queue

The default task backend is the in-process threadpool. Redis is only required
when `RAGRIG_TASK_BACKEND=arq` and a worker is running.

```
RAGRIG_TASK_BACKEND=arq
RAGRIG_REDIS_URL=redis://redis:6379
RAGRIG_TASK_QUEUE_MAX_JOBS=10
```

When the ARQ backend is active, `/health` pings Redis and reports
`redis.status="connected"` or returns HTTP 503 with `redis.status="error"`.
With the default threadpool backend, Redis health is reported as `skipped`.

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
