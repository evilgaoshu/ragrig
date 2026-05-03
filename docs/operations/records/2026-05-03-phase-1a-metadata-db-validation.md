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

Status at handoff time: not yet validated for EVI-29 in this run.

Current blocker:

- this run has not yet produced `192.168.3.100` migration evidence for the EVI-29 schema changes
- prior EVI-28 evidence proves the host and port-override path can work, but it is not sufficient as EVI-29 acceptance evidence

Required follow-up validation on `192.168.3.100`:

```bash
cp .env.example .env
# if 5432 is occupied on the host, override DB_HOST_PORT in .env
docker compose up --build -d db
make migrate
make db-check
docker compose exec db psql -U ragrig -d ragrig -c "SELECT extname FROM pg_extension WHERE extname = 'vector';"
docker compose exec db psql -U ragrig -d ragrig -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;"
```

Expected evidence to record:

- active checkout path and tested commit SHA
- `make migrate` success output
- `make db-check` JSON showing `current_revision: 20260503_0001`, `revision_matches_head: true`, and empty `missing_tables`
- `pg_extension` query returning `vector`
- note whether `DB_HOST_PORT` override was required on the host

## Downgrade Check

The first Alembic revision includes `downgrade()` and is intended to support `make migrate-down` after an `upgrade head` run.

This downgrade path is implemented but not yet replay-verified in a live DB during this run because the same Docker availability blocker prevented local and shared-host migration execution.
