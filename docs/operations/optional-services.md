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

File logs are deliberately opt-in. In containers, stdout/stderr remains the
portable default because most orchestrators own log collection and rotation. If
you want compose-managed rotating log files, copy this block into `.env`:

```
RAGRIG_METRICS_ENABLED=true
RAGRIG_LOG_FORMAT=json
RAGRIG_LOG_LEVEL=INFO
RAGRIG_LOG_FILE=/app/logs/ragrig.jsonl
RAGRIG_LOG_MAX_BYTES=10485760
RAGRIG_LOG_BACKUP_COUNT=5
```

`docker-compose.yml` mounts `/app/logs` to the `ragrig_logs` volume. The
application creates the parent directory and rotates the file according to
`RAGRIG_LOG_MAX_BYTES` and `RAGRIG_LOG_BACKUP_COUNT`.

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
