# Phase 1a Metadata DB Validation Record

Date: 2026-05-03
Issue: EVI-29

## Local Verification

Successful local commands on the development machine:

```bash
make format
make lint
make test
```

Observed result:

- `ruff format` completed successfully after normalizing the new DB, Alembic, and docs files
- `ruff check` returned no findings
- `pytest` passed the health contract tests plus DB config, model, session, and smoke-script tests

## Local Runtime Verification

Attempted local database bootstrap commands:

```bash
cp .env.example .env
docker compose up --build -d db
make migrate
make db-check
```

Observed blocker on this development machine:

```text
failed to connect to the docker API at unix:///Users/yue/.orbstack/run/docker.sock: connect: no such file or directory
```

Impact:

- local Compose-backed migration replay could not be completed on this machine
- local `make db-check` against a live container is blocked by unavailable Docker daemon access
- Alembic SQL rendering was still verified locally with:

```bash
uv run alembic upgrade head --sql > /tmp/ragrig-alembic-upgrade.sql
uv run alembic downgrade 20260503_0001:base --sql > /tmp/ragrig-alembic-downgrade.sql
```

Observed result:

- upgrade SQL rendered successfully and includes `CREATE EXTENSION IF NOT EXISTS vector`
- downgrade SQL rendered successfully and includes teardown for all Phase 1a tables

Recommended local retry path once Docker is available:

```bash
cp .env.example .env
docker compose up --build -d db
make migrate
make db-check
docker compose exec db psql -U ragrig -d ragrig -c "SELECT extname FROM pg_extension WHERE extname = 'vector';"
```

## Shared Environment 192.168.3.100

Shared environment validation is complete in this run using `root@192.168.3.100`.

Validated checkout:

- Host: `192.168.3.100`
- User: `root`
- Path: `/root/ragrig-phase1a-evi29`
- Tested source commit synced from local branch head during validation: `ee7753f953693a846a250adca23f022d042c2f8f`
- Effective host DB port: `35433`

Commands run:

```bash
export PATH="/root/.local/bin:$PATH"
/root/.local/bin/uv sync --dev
cp .env.example .env
# auto-selected an unused host port and wrote DB_HOST_PORT=35433 into .env
docker compose up --build -d db
make UV=/root/.local/bin/uv migrate
make UV=/root/.local/bin/uv db-check
docker compose exec db psql -U ragrig -d ragrig -c "SELECT extname FROM pg_extension WHERE extname = 'vector';"
docker compose exec db psql -U ragrig -d ragrig -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;"
docker compose exec db psql -U ragrig -d ragrig -c "SELECT version_num FROM alembic_version;"
docker compose ps
```

Observed result:

- `make migrate` completed successfully and applied revision `20260503_0001`
- `make db-check` returned:

```json
{
  "current_revision": "20260503_0001",
  "extension": "vector",
  "missing_tables": [],
  "present_tables": [
    "chunks",
    "document_versions",
    "documents",
    "embeddings",
    "knowledge_bases",
    "pipeline_run_items",
    "pipeline_runs",
    "sources"
  ],
  "revision_matches_head": true
}
```

- `pg_extension` query returned `vector`
- `pg_tables` query returned `alembic_version` plus all eight required Phase 1a tables
- `alembic_version` query returned `20260503_0001`
- `docker compose ps` showed `db` healthy on `0.0.0.0:35433->5432/tcp`

Notes:

- `15433` and `25433` were already occupied on the host, so this run used `DB_HOST_PORT=35433`
- This run exposed and fixed a real host-side verification bug: `make migrate` and `make db-check` originally used `DATABASE_URL` with host `db`, which only resolves inside Compose networking. The implementation now derives host-side verification URLs from `localhost:${DB_HOST_PORT}` while keeping the app container path unchanged.

## Downgrade Check

The first Alembic revision includes `downgrade()` and local SQL rendering verification for `uv run alembic downgrade 20260503_0001:base --sql` succeeded during this run.

Live downgrade replay against the shared DB was not executed because the acceptance path for this issue only required proving `upgrade head`, table presence, `pgvector` availability, and current revision at the validated commit. The downgrade implementation remains present and SQL-renderable.
