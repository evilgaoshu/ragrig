# Phase 1c Chunking and Embedding Validation Record

Date: 2026-05-03
Issue: EVI-31

## Local Verification

Successful repository commands on the development machine:

```bash
make format
make lint
make test
```

- `make format` completed successfully
- `make lint` returned no findings
- `make test` passed `27` tests, including new chunking and indexing coverage in `tests/test_indexing_pipeline.py`

Local runtime note for this implementation run:

- Compose-backed runtime validation was executed on `192.168.3.100` for the required DB and pipeline evidence

## Shared Environment 192.168.3.100

Shared-environment validation is complete in this run using `root@192.168.3.100`.

Validated checkout:

- Host: `192.168.3.100`
- User: `root`
- Path: `/root/ragrig-phase1c-evi31`
- Effective host DB port: `35435`

Commands run:

```bash
cd /root/ragrig-phase1c-evi31
cp .env.example .env
sed -i 's/^DB_HOST_PORT=5432/DB_HOST_PORT=35435/' .env
uv sync --dev
docker compose up --build -d db
make UV=/root/.local/bin/uv migrate
make UV=/root/.local/bin/uv ingest-local
make UV=/root/.local/bin/uv index-local
make UV=/root/.local/bin/uv ingest-check
make UV=/root/.local/bin/uv index-check
docker compose exec -T db psql -U ragrig -d ragrig -c "SELECT COUNT(*) AS chunks FROM chunks;"
docker compose exec -T db psql -U ragrig -d ragrig -c "SELECT COUNT(*) AS embeddings FROM embeddings;"
docker compose exec -T db psql -U ragrig -d ragrig -c "SELECT provider, model, dimensions, COUNT(*) FROM embeddings GROUP BY provider, model, dimensions ORDER BY provider, model, dimensions;"
docker compose exec -T db psql -U ragrig -d ragrig -c "SELECT status, total_items, success_count, failure_count FROM pipeline_runs WHERE run_type = 'chunk_embedding' ORDER BY started_at DESC LIMIT 1;"
docker compose exec -T db psql -U ragrig -d ragrig -c "SELECT chunk_index, char_start, char_end, LEFT(text, 80) FROM chunks ORDER BY created_at DESC, chunk_index LIMIT 8;"
```

Observed result:

- `make migrate` completed successfully against the Compose-backed database on `0.0.0.0:35435->5432/tcp`
- `make ingest-local` completed successfully and wrote one `sources` row, five `documents`, four `document_versions`, and five `pipeline_run_items`
- `make index-local` completed successfully and wrote three `chunks`, three `embeddings`, and one `chunk_embedding` pipeline run
- `make ingest-check` returned a `completed` local-ingestion run with `total_items=5`, `success_count=4`, `failure_count=0`
- `make index-check` returned a `completed` chunk-embedding run with `total_items=4`, `success_count=3`, `failure_count=0`
- the empty fixture document version was recorded as a skipped indexing item, so `pipeline_run_item_status_counts` showed `success=3` and `skipped=1`
- SQL queries confirmed `provider=deterministic-local`, `model=hash-8d`, and `dimensions=8`
- SQL chunk preview queries showed persisted chunk spans and text previews for Markdown and plain text fixtures

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

Observed `make index-check` summary:

```json
{
  "counts": {
    "chunks": 3,
    "embeddings": 3
  },
  "embedding_dimensions": [
    {
      "count": 3,
      "dimensions": 8,
      "model": "hash-8d",
      "provider": "deterministic-local"
    }
  ],
  "latest_pipeline_run": {
    "failure_count": 0,
    "status": "completed",
    "success_count": 3,
    "total_items": 4
  },
  "pipeline_run_item_status_counts": {
    "skipped": 1,
    "success": 3
  }
}
```

Observed SQL evidence:

```text
chunks=3
embeddings=3
deterministic-local | hash-8d | 8 | 3
chunk_embedding latest: completed | 4 | 3 | 0
chunk preview rows:
0 | 0 | 62 | # RAGRig Guide ...
0 | 0 | 44 | ## Nested Fixture ...
0 | 0 | 48 | Local ingestion fixture for plain text parsing.
```

Shared-host note:

- the Phase 1c smoke path required no external secret or network embedding provider
- current fixture content is short enough that each non-empty document version produced one chunk under the default `chunk_size=500`

Remote log locations:

- `/tmp/ragrig-phase1c-compose-down.log`
- `/tmp/ragrig-phase1c-compose-up.log`
- `/tmp/ragrig-phase1c-uv-sync.log`
- `/tmp/ragrig-phase1c-migrate.log`
- `/tmp/ragrig-phase1c-ingest.log`
- `/tmp/ragrig-phase1c-index.log`
- `/tmp/ragrig-phase1c-ingest-check.log`
- `/tmp/ragrig-phase1c-index-check.log`
- `/tmp/ragrig-phase1c-chunks.log`
- `/tmp/ragrig-phase1c-embeddings.log`
- `/tmp/ragrig-phase1c-dimensions.log`

- shared-host raw SQL probes for pipeline status and chunk preview were re-run after an initial shell-quoting mistake in the command wrapper; the validated outputs above reflect the corrected successful queries
