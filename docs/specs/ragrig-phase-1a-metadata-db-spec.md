# RAGRig Phase 1a Metadata DB Spec

Issue: EVI-29
Date: 2026-05-03
Status: DEV implementation spec

## Scope

This document constrains the Phase 1a metadata database implementation to the minimum schema and migration foundation required by `docs/specs/ragrig-mvp-spec.md` Section 12.

Included in this scope:

- SQLAlchemy 2.x sync models backed by the existing `psycopg` sync path.
- Root-level Alembic configuration and an initial migration covering the Phase 1a metadata tables.
- `pgvector` extension bootstrap in migration via `CREATE EXTENSION IF NOT EXISTS vector`.
- Minimal engine, session, and FastAPI-ready DB dependency boundaries for follow-on ingestion and retrieval work.
- A reproducible smoke script and Makefile commands for migration and schema verification.
- README and operations records updates covering local and `192.168.3.100` verification.

Explicitly out of scope:

- local file ingestion
- parser, cleaner, or chunker business logic
- embedding generation or retrieval APIs
- vector indexes such as HNSW or IVFFlat
- Web UI, ACL enforcement, audit enforcement, connectors, rerank, or answer generation

## Technical Choices

- ORM and migration stack: SQLAlchemy 2.x + Alembic
- Driver path: `psycopg` sync, no `asyncpg`
- Alembic location: repo root `alembic/`
- Primary keys: UUID for all core entities
- Vector storage: pgvector `vector` without fixed dimensions, plus explicit `dimensions INT NOT NULL`
- Compose compatibility: keep `APP_HOST_PORT` and `DB_HOST_PORT` host overrides from EVI-28

## Schema Boundary

The initial migration must create these tables:

- `knowledge_bases`
- `sources`
- `documents`
- `document_versions`
- `chunks`
- `embeddings`
- `pipeline_runs`
- `pipeline_run_items`

Key data-model rules:

- `documents` tracks discovered source files and stable identity.
- `document_versions` stores extracted content versions, parser metadata, and content hash snapshots.
- `chunks` belongs to `document_versions`, not directly to `documents`.
- `embeddings` belongs to `chunks` and allows one chunk to hold multiple embeddings from different providers or models.
- `pipeline_run_items` points to `documents` so a run can track file-level success, skip, or failure regardless of how many versions were produced.

## Table Summary

| Table | Purpose | Key relationships |
| --- | --- | --- |
| `knowledge_bases` | Named collection boundary for documents and retrieval | parent of `sources`, `documents`, `pipeline_runs` |
| `sources` | Source identity and config snapshot | belongs to `knowledge_bases` |
| `documents` | Discovered file identity, path/URI, and latest source hash | belongs to `knowledge_bases`, `sources` |
| `document_versions` | Parsed content versions and parser metadata | belongs to `documents` |
| `chunks` | Chunk text and citation spans | belongs to `document_versions` |
| `embeddings` | Provider/model metadata and vector payload | belongs to `chunks` |
| `pipeline_runs` | Run-level status, counts, and config snapshot | belongs to `knowledge_bases`, optional `sources` |
| `pipeline_run_items` | Per-document run status and errors | belongs to `pipeline_runs`, `documents` |

## Migration Requirements

- `alembic upgrade head` must succeed against a fresh PostgreSQL + pgvector database started with Docker Compose.
- The migration also runs `CREATE EXTENSION IF NOT EXISTS vector` so fresh-clone migration works even if the Docker init script has not run yet.
- The existing `scripts/init-db.sql` stays in place; both paths are idempotent and must not conflict.
- The first migration supports `alembic downgrade -1` for clean rollback of the initial schema.

## Verification Requirements

Repository commands:

- `make format`
- `make lint`
- `make test`
- `make migrate`
- `make db-check`

Expected DB smoke evidence:

- `SELECT extname FROM pg_extension WHERE extname = 'vector';`
- core table presence in `pg_tables`
- successful `alembic current`

## Fresh Clone Flow

1. `make sync`
2. `cp .env.example .env`
3. set `APP_HOST_PORT` or `DB_HOST_PORT` in `.env` if host ports conflict
4. `docker compose up --build -d db`
5. `make migrate`
6. `make db-check`

## Follow-on Work Enabled By This Spec

This schema leaves a clear next slice for local ingestion and Markdown/text parsing work:

- source scanning can create or update `documents`
- parsing can append `document_versions`
- chunking can append `chunks`
- embedding generation can append `embeddings`
- ingestion orchestration can create `pipeline_runs` and `pipeline_run_items`

That follow-on issue should stay focused on file discovery, Markdown/text parsing, and deterministic version creation without changing the Phase 1a metadata table boundaries.
