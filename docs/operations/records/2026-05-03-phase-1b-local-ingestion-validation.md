# Phase 1b Local Ingestion Validation Record

Date: 2026-05-03
Issue: EVI-30

## Local Verification

Successful repository commands on the development machine:

```bash
make format
make lint
make test
make ingest-local-dry-run
```

Observed result in this implementation run:

- `make format` completed successfully
- `make lint` returned no findings
- `make test` passed `22` tests, including parser, scanner, and ingestion pipeline coverage
- `make ingest-local-dry-run` is documented and wired, but Compose-backed local ingestion remains blocked on this machine by unavailable Docker daemon access

Local runtime blocker on this machine:

```text
unable to get image 'pgvector/pgvector:pg16': failed to connect to the docker API at unix:///Users/yue/.orbstack/run/docker.sock: connect: no such file or directory
```

## Shared Environment 192.168.3.100

Shared-environment validation is complete in this run using `root@192.168.3.100`.

Validated checkout:

- Host: `192.168.3.100`
- User: `root`
- Path: `/root/ragrig-phase1b-evi30`
- Effective host DB port: `35434`

Commands run:

```bash
cd /root/ragrig-phase1b-evi30
cp .env.example .env
sed -i 's/^DB_HOST_PORT=5432/DB_HOST_PORT=35434/' .env
export PATH="/root/.local/bin:$PATH"
uv sync --dev
docker compose up --build -d db
make UV=/root/.local/bin/uv migrate
make UV=/root/.local/bin/uv ingest-local
make UV=/root/.local/bin/uv ingest-check
docker compose exec -T db psql -U ragrig -d ragrig -c "SELECT COUNT(*) AS sources FROM sources;"
docker compose exec -T db psql -U ragrig -d ragrig -c "SELECT COUNT(*) AS documents FROM documents;"
docker compose exec -T db psql -U ragrig -d ragrig -c "SELECT COUNT(*) AS document_versions FROM document_versions;"
docker compose exec -T db psql -U ragrig -d ragrig -c "SELECT status, total_items, success_count, failure_count FROM pipeline_runs ORDER BY started_at DESC LIMIT 1;"
docker compose exec -T db psql -U ragrig -d ragrig -c "SELECT content_hash, LEFT(extracted_text, 80) FROM document_versions ORDER BY created_at DESC LIMIT 3;"
```

Observed result:

- `make migrate` completed successfully against the Compose-backed database on `0.0.0.0:35434->5432/tcp`
- `make ingest-local` completed successfully and wrote one `sources` row, five `documents`, four `document_versions`, and five `pipeline_run_items`
- `make ingest-check` returned a `completed` latest pipeline run with `total_items=5`, `success_count=4`, `failure_count=0`
- `pipeline_run_item_status_counts` showed `success=4` and `skipped=1`
- `document_versions` queries returned content hashes and extracted text previews for Markdown, nested Markdown, plain text, and empty text fixtures

Observed `make ingest-check` summary:

```json
{
  "counts": {
    "document_versions": 4,
    "documents": 5,
    "pipeline_run_items": 5,
    "sources": 1
  },
  "latest_pipeline_run": {
    "failure_count": 0,
    "status": "completed",
    "success_count": 4,
    "total_items": 5
  },
  "pipeline_run_item_status_counts": {
    "skipped": 1,
    "success": 4
  }
}
```

Observed SQL evidence:

```text
sources=1
documents=5
document_versions=4
pipeline_runs latest: completed | 5 | 4 | 0
```

Shared-host note:

- the first validation attempt failed on host port `5432` already being occupied, and the rerun succeeded after setting `DB_HOST_PORT=35434`
- this confirms the Compose host-port override path remains functional for Phase 1b

Remote log locations:

- `/tmp/ragrig-phase1b-compose-down.log`
- `/tmp/ragrig-phase1b-compose-up.log`
- `/tmp/ragrig-phase1b-uv-sync.log`
- `/tmp/ragrig-phase1b-migrate.log`
- `/tmp/ragrig-phase1b-ingest.log`
- `/tmp/ragrig-phase1b-ingest-check.log`
- `/tmp/ragrig-phase1b-sources.log`
- `/tmp/ragrig-phase1b-documents.log`
- `/tmp/ragrig-phase1b-document-versions.log`
- `/tmp/ragrig-phase1b-pipeline-run.log`
- `/tmp/ragrig-phase1b-document-preview.log`

## Notes

- `make ingest-local` and `make ingest-check` use the host-side runtime DB URL path and therefore should work with `DB_HOST_PORT` overrides exactly like `make migrate` and `make db-check`
- fixture root for reproducible smoke runs is `tests/fixtures/local_ingestion`
