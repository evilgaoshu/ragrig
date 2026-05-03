# RAGRig Phase 1a Scaffold Spec

Issue: EVI-28
Date: 2026-05-03
Status: DEV implementation spec

## Scope

This document constrains the first implementation step for RAGRig Phase 1a to project scaffolding only.

Included in this scope:

- Python 3.11+ service scaffold with FastAPI and `uv`-managed dependencies.
- A minimal API service exposing `GET /health`.
- Typed settings via `pydantic-settings` and a committed `.env.example`.
- Docker Compose development stack for the app and PostgreSQL with pgvector.
- Reproducible pgvector initialization via SQL bootstrap.
- `ruff` lint/format commands, `pytest` test command, and a minimal automated health test.
- Documentation updates covering setup, commands, verification, and spec links.

Explicitly out of scope for this scaffold PR:

- ingestion pipelines
- PDF parsing
- chunking
- embedding generation
- pgvector writes beyond extension bootstrap
- retrieval APIs
- Qdrant support
- Web UI
- ACL, audit, connectors, or LLM-assisted cleaning

## Technical Choices

- Runtime: Python 3.11+
- Service framework: FastAPI
- Dependency management: `uv` with `pyproject.toml`
- Settings: `pydantic-settings`
- Test stack: `pytest` + `httpx`/FastAPI test client path
- Lint and format: `ruff`
- Database container: `pgvector/pgvector:pg16`

## Project Boundaries

The repository should reserve package locations for later ingestion and retrieval work without freezing the implementation details too early.

Reserved packages in this phase:

- `src/ragrig/parsers`
- `src/ragrig/cleaners`
- `src/ragrig/chunkers`
- `src/ragrig/embeddings`
- `src/ragrig/vectorstore`

These packages stay as explicit placeholders only. They do not define abstract base classes, provider contracts, or fake business logic in this phase.

## Health Endpoint Contract

`GET /health` is the only required API in this scaffold.

Expected success response:

```json
{
  "status": "healthy",
  "app": "ok",
  "db": "connected",
  "version": "0.1.0"
}
```

Expected database failure response:

```json
{
  "status": "unhealthy",
  "app": "ok",
  "db": "error",
  "detail": "database unavailable",
  "version": "0.1.0"
}
```

The unhealthy path must return `503` or an equivalent explicit service-unavailable status.

## Local Development Stack

The Compose stack must boot these services:

- `app`: FastAPI service container
- `db`: PostgreSQL 16 with pgvector extension available

Initialization requirement:

- `scripts/init-db.sql` runs `CREATE EXTENSION IF NOT EXISTS vector;`

Verification commands to document and keep working:

- `docker compose up --build`
- `curl http://localhost:8000/health`
- `docker compose exec db psql -U ragrig -d ragrig -c "SELECT extname FROM pg_extension WHERE extname = 'vector';"`

## Verification Plan

Repository checks for this phase:

- `make format`
- `make lint`
- `make test`

Runtime checks for this phase:

- local Docker Compose boot
- `/health` success with database connected
- pgvector extension query succeeds

Shared environment requirement:

- run the runtime verification on `192.168.3.100`
- if the environment is unreachable or credentials are missing, record the blocker with the attempted command and observed failure

## Documentation Requirements

The PR must update repository docs so a fresh clone can:

- install dependencies
- copy `.env.example` into `.env`
- run format/lint/test commands
- start the Docker Compose stack
- verify the health endpoint and pgvector extension

README must link both specs:

- `docs/specs/ragrig-mvp-spec.md`
- `docs/specs/ragrig-phase-1a-scaffold-spec.md`
