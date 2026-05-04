# Web Console Validation Record

Date: 2026-05-04
Issue: EVI-33

## Local Verification

Repository verification commands:

```bash
uv run ruff check .
make test
make web-check
```

Observed result:

- `uv run ruff check .` returned no findings
- `make test` passed `41` tests, including new host-side runtime coverage in `tests/test_db_runtime_url.py` and Web Console coverage in `tests/test_web_console.py`
- `make web-check` passed `4` Web Console contract tests

## Local Runtime Verification

Local runtime setup:

```bash
cat > .env <<'EOF'
APP_NAME=ragrig
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=18001
APP_HOST_PORT=18001
DB_HOST_PORT=15439
DATABASE_URL=postgresql://ragrig:ragrig_dev@db:5432/ragrig
EOF
docker compose up --build -d db
make migrate
make ingest-local
make index-local
make run-web
curl http://127.0.0.1:18001/health
curl http://127.0.0.1:18001/system/status
curl http://127.0.0.1:18001/knowledge-bases
curl http://127.0.0.1:18001/pipeline-runs
```

Observed result:

- `/health` returned `{"status":"healthy","app":"ok","db":"connected","version":"0.1.0"}`
- `/system/status` returned `dialect=postgresql`, `alembic_revision=20260503_0001`, `extension.state=installed`
- `/knowledge-bases` returned one real `fixture-local` knowledge base with `document_count=10`, `chunk_count=6`
- `/pipeline-runs` returned persisted ingestion and chunk-embedding history
- Browser verification against `http://127.0.0.1:18001/console` showed all 8 MVP modules rendering without white screen
- Browser verification confirmed Retrieval Lab returned real ranked chunks from `guide.md`, `deep.md`, and `notes.txt`

Important implementation note:

- `make run-web` now uses `scripts.run_web` and host-side `runtime_database_url`, so the Web Console can run outside Docker while still reaching the Compose-mapped database port

## Shared Environment 192.168.3.100

Shared-environment validation is complete in this run using `root@192.168.3.100`.

Validated checkout:

- Host: `192.168.3.100`
- User: `root`
- Path: `/root/ragrig-evi33-web-console`
- App port: `18002`
- DB host port: `35439`

Commands run:

```bash
cat > .env <<'EOF'
APP_NAME=ragrig
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=18002
APP_HOST_PORT=18002
DB_HOST_PORT=35439
DATABASE_URL=postgresql://ragrig:ragrig_dev@db:5432/ragrig
EOF
/root/.local/bin/uv sync --dev
docker compose up --build -d db
make UV=/root/.local/bin/uv migrate
make UV=/root/.local/bin/uv ingest-local
make UV=/root/.local/bin/uv index-local
make UV=/root/.local/bin/uv run-web
curl http://127.0.0.1:18002/health
curl http://127.0.0.1:18002/system/status
curl http://127.0.0.1:18002/knowledge-bases
curl http://127.0.0.1:18002/pipeline-runs
curl http://127.0.0.1:18002/documents
curl -X POST http://127.0.0.1:18002/retrieval/search -H 'Content-Type: application/json' --data-binary '{"knowledge_base":"fixture-local","query":"RAGRig Guide","top_k":3}'
docker compose exec -T db psql -U ragrig -d ragrig -c "SELECT status, total_items, success_count, failure_count FROM pipeline_runs ORDER BY started_at DESC LIMIT 4;"
docker compose exec -T db psql -U ragrig -d ragrig -c "SELECT COUNT(*) AS documents FROM documents; SELECT COUNT(*) AS chunks FROM chunks; SELECT COUNT(*) AS embeddings FROM embeddings;"
```

Observed result:

- `/health` returned healthy on `192.168.3.100:18002`
- `/system/status` reported `postgresql`, `alembic_revision=20260503_0001`, and `vector=installed`
- `/knowledge-bases` returned one real `fixture-local` knowledge base with `document_count=5` and `chunk_count=3`
- `/pipeline-runs` returned one real `local_ingestion` run and one real `chunk_embedding` run
- `/documents` returned real fixture-backed document and latest-version metadata, including the empty-text document with zero chunks
- `POST /retrieval/search` returned three real ranked results from `nested/deep.md`, `guide.md`, and `notes.txt`
- SQL verification confirmed `documents=5`, `chunks=3`, and `embeddings=3`
- Browser verification against `http://192.168.3.100:18002/console` showed health/db state, knowledge base inventory, pipeline history, document preview, model shell, and Retrieval Lab results rendering successfully

Remote operational note:

- `root@192.168.3.100` has `/root/.local/bin/uv` installed but not on `PATH`, so shared-host validation must use the explicit path unless the environment is updated
