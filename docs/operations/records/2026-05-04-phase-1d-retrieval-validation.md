# Phase 1d Retrieval Validation Record

Date: 2026-05-04
Issue: EVI-32

## Local Verification

Repository verification commands for this implementation:

```bash
make format
make lint
make test
```

Local result summary:

- `make format` completed successfully
- `make lint` returned no findings
- `make test` passed `36` tests, including new retrieval coverage in `tests/test_retrieval.py`

## Shared Environment 192.168.3.100

Shared-environment validation is complete in this run using `root@192.168.3.100`.

Validated checkout:

- Host: `192.168.3.100`
- User: `root`
- Path: `/root/ragrig-phase1d-evi32`
- Effective host DB port: `35436`

Commands run:

```bash
cp .env.example .env
sed -i 's/^DB_HOST_PORT=5432/DB_HOST_PORT=35436/' .env
/root/.local/bin/uv sync --dev
docker compose up --build -d db
make UV=/root/.local/bin/uv migrate
make UV=/root/.local/bin/uv ingest-local
make UV=/root/.local/bin/uv index-local
make UV=/root/.local/bin/uv retrieve-check QUERY="RAGRig Guide"
docker compose exec -T db psql -U ragrig -d ragrig -c "SELECT provider, model, dimensions, COUNT(*) FROM embeddings GROUP BY provider, model, dimensions ORDER BY provider, model, dimensions;"
docker compose exec -T db psql -U ragrig -d ragrig -c "SELECT d.uri, dv.version_number, c.id, c.chunk_index, LEFT(c.text, 80) AS preview FROM chunks c JOIN document_versions dv ON dv.id = c.document_version_id JOIN documents d ON d.id = dv.document_id ORDER BY d.uri, dv.version_number DESC, c.chunk_index LIMIT 8;"
```

Observed result:

- `make migrate` completed successfully against the Compose-backed database on host port `35436`
- `make ingest-local` completed successfully and wrote five `documents`, four `document_versions`, and one skipped binary artifact item
- `make index-local` completed successfully and wrote three `chunks`, three `embeddings`, and one skipped empty-text version
- `make retrieve-check QUERY="RAGRig Guide"` returned three real indexed chunk matches with `document_id`, `document_version_id`, `chunk_id`, `chunk_index`, `document_uri`, `source_uri`, `distance`, and `score`
- SQL verification confirmed `provider=deterministic-local`, `model=hash-8d`, and `dimensions=8`
- SQL citation verification confirmed persisted chunk identifiers and previews for the indexed Markdown and plain-text fixtures

Observed retrieval summary:

```json
{
  "dimensions": 8,
  "distance_metric": "cosine_distance",
  "knowledge_base": "fixture-local",
  "model": "hash-8d",
  "provider": "deterministic-local",
  "query": "RAGRig Guide",
  "top_k": 3,
  "total_results": 3
}
```

Observed SQL evidence:

```text
deterministic-local | hash-8d | 8 | 3
/root/ragrig-phase1d-evi32/tests/fixtures/local_ingestion/guide.md       | 1 | 74ed8f0e-668c-4f18-835d-252ee1fcb0fd | 0 | # RAGRig Guide ...
/root/ragrig-phase1d-evi32/tests/fixtures/local_ingestion/nested/deep.md | 1 | 94f1c956-7bc2-43bc-bc0b-9f748d40803f | 0 | ## Nested Fixture ...
/root/ragrig-phase1d-evi32/tests/fixtures/local_ingestion/notes.txt      | 1 | d74406a1-7eee-4242-bc1e-7377f37e300b | 0 | Local ingestion fixture for plain text parsing.
```

Remote log locations:

- `/tmp/ragrig-phase1d-compose-up.log`
- `/tmp/ragrig-phase1d-uv-sync.log`
- `/tmp/ragrig-phase1d-migrate.log`
- `/tmp/ragrig-phase1d-ingest.log`
- `/tmp/ragrig-phase1d-index.log`
- `/tmp/ragrig-phase1d-retrieve.log`
- `/tmp/ragrig-phase1d-dimensions.log`
- `/tmp/ragrig-phase1d-citations.log`
