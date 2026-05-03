<p align="center">
  <img src="./assets/ragrig-icon.svg" alt="RAGRig logo" width="160" height="160">
</p>

<h1 align="center">RAGRig</h1>

<p align="center">
  <strong>Open-source RAG governance and pipeline platform for enterprise knowledge.</strong>
</p>

<p align="center">
  <em>源栈: from scattered enterprise sources to traceable, permission-aware, model-ready knowledge.</em>
</p>

---

## About

RAGRig is an open-source platform for building lightweight, governable RAG systems for small and medium-sized teams.

It helps organizations connect scattered knowledge sources, clean and structure documents with LLM-assisted pipelines, index them into vector stores such as Qdrant and pgvector, and serve retrieval results through traceable, permission-aware APIs.

RAGRig is not meant to be another generic chatbot wrapper. Its focus is the hard operational layer around RAG:

- source connectors for documents, wikis, shared drives, databases, object storage, and enterprise document hubs
- customizable ingestion and cleaning workflows
- model registry for LLMs, embedding models, rerankers, OCR, and parsers
- Qdrant and Postgres/pgvector as first-class vector backends
- document, chunk, and metadata versioning
- permission-aware retrieval with pre-retrieval access filtering
- RAG evaluation, observability, and regression checks
- source traceability from answer to document, version, chunk, and pipeline run
- Markdown and document preview/editing integrations for knowledge review workflows

The goal is to make enterprise knowledge usable by AI systems without losing control over source provenance, permissions, quality, or deployment cost.

## Why RAGRig

Many RAG tools make it easy to upload files and chat with them. Production RAG inside a company needs more than that.

Teams need to know where each answer came from, whether the source is still valid, which model created the embedding, who is allowed to retrieve the content, and whether a pipeline change made retrieval better or worse.

RAGRig treats RAG as an operational system:

- **Source-first:** every generated answer should point back to inspectable source material.
- **Governed by default:** access control, metadata, versions, and audit events are part of the core model.
- **Model-flexible:** bring local or hosted LLMs, embedding models, rerankers, OCR, and parsers.
- **Vector-store portable:** start with pgvector, scale to Qdrant, and keep migration paths explicit.
- **Ops-friendly:** designed for Docker Compose first, with a path to Kubernetes later.

## Project Status

RAGRig is in early project design and scaffolding.

Current implementation status:

1. Phase 0 docs and project framing are committed.
2. Phase 1a scaffold provides a FastAPI service, local Docker Compose stack, pgvector-enabled PostgreSQL, and verification commands.
3. Phase 1a metadata DB adds SQLAlchemy models, Alembic migrations, and DB smoke commands for the MVP metadata boundary.
4. Ingestion, parsing, chunking, embedding, indexing, and retrieval remain intentionally unimplemented in this repository state.

Authoritative specs:

- [MVP spec](./docs/specs/ragrig-mvp-spec.md)
- [Phase 1a scaffold spec](./docs/specs/ragrig-phase-1a-scaffold-spec.md)
- [Phase 1a metadata DB spec](./docs/specs/ragrig-phase-1a-metadata-db-spec.md)

## Phase 1a Foundation

Phase 1a currently ships the engineering scaffold and metadata database foundation required for follow-on ingestion and retrieval work:

- Python 3.11+ service with FastAPI
- typed settings via `pydantic-settings`
- `GET /health` with explicit app and database status
- SQLAlchemy 2.x models for the metadata boundary from MVP Section 12
- Alembic migrations rooted at `alembic/`
- pgvector-backed `embeddings` table with dynamic dimensions metadata
- `uv`-managed dependencies in `pyproject.toml`
- `ruff` format/lint commands and `pytest` tests
- Docker Compose for the app and PostgreSQL with pgvector
- smoke commands for migration and schema validation

Reserved but intentionally empty package boundaries:

- `src/ragrig/parsers`
- `src/ragrig/cleaners`
- `src/ragrig/chunkers`
- `src/ragrig/embeddings`
- `src/ragrig/vectorstore`

These directories are placeholders only. They do not imply that parsing, cleaning, chunking, embedding, or vector indexing are implemented yet.

## Quick Start

1. Install `uv` if it is not already available.
2. Sync dependencies:

   ```bash
   make sync
   ```

3. Create a local env file:

   ```bash
   cp .env.example .env
   ```

   If `8000` or `5432` are already in use on the host, set alternate values in `.env`, for example `APP_HOST_PORT=18000` or `DB_HOST_PORT=15433`.

4. Run code quality checks:

   ```bash
   make format
   make lint
   make test
   ```

5. Start the database service:

   ```bash
   docker compose up --build -d db
   ```

6. Run the initial migration:

   ```bash
   make migrate
   ```

7. Verify the extension and schema:

   ```bash
   make db-check
   ```

   Expected output shape:

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

8. Start the full local development stack when you also want the API service:

   ```bash
    docker compose up --build
   ```

9. Verify the service and pgvector bootstrap:

   ```bash
   curl http://localhost:8000/health
   docker compose exec db psql -U ragrig -d ragrig -c "SELECT extname FROM pg_extension WHERE extname = 'vector';"
   docker compose exec db psql -U ragrig -d ragrig -c "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;"
   ```

    If you changed `APP_HOST_PORT`, use that port in the `curl` command.
    If you changed `DB_HOST_PORT`, keep using `docker compose exec db ...`; no command change is required.

Expected healthy response:

```json
{
  "status": "healthy",
  "app": "ok",
  "db": "connected",
  "version": "0.1.0"
}
```

If PostgreSQL is unavailable, `/health` returns `503` with a clear error payload.

## Database Commands

Repository-level DB commands:

- `make migrate`: apply Alembic migrations to head
- `make migrate-down`: roll back one migration step
- `make db-check`: verify `pgvector` extension, required Phase 1a tables, and Alembic head revision
- `make db-shell`: open `psql` in the Compose database container
- `make test-db`: alias for the DB smoke check

Fresh-clone schema verification path:

```bash
make sync
cp .env.example .env
docker compose up --build -d db
make migrate
make db-check
```

The Compose file still supports shared-machine port overrides through `.env`, for example:

```bash
APP_HOST_PORT=18000
DB_HOST_PORT=15433
```

This override path must remain available for `192.168.3.100` and other shared hosts where default ports are already in use.

## Planned Integrations

Input sources:

- local files and folders
- SMB/NFS
- S3-compatible storage, including Cloudflare R2
- Cloudflare D1, KV, and other platform data sources
- Google Docs / Google Drive
- wiki systems such as Confluence or MediaWiki
- databases
- WPS document middle platform
- OnlyOffice-compatible document services

Output targets:

- Qdrant
- Postgres/pgvector
- S3-compatible storage
- NFS
- relational databases
- Markdown, JSONL, and Parquet exports

Model providers:

- OpenAI-compatible APIs
- Ollama
- llama.cpp
- vLLM
- local embedding and reranker models such as BAAI BGE

## Repository Layout

```text
.
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 20260503_0001_phase_1a_metadata_schema.py
├── assets/
│   ├── ragrig-icon.png
│   └── ragrig-icon.svg
├── docs/
│   ├── roadmap.md
│   └── specs/
│       ├── ragrig-mvp-spec.md
│       └── ragrig-phase-1a-scaffold-spec.md
├── scripts/
│   ├── db_check.py
│   └── init-db.sql
├── src/
│   └── ragrig/
│       ├── db/
│       │   ├── engine.py
│       │   ├── models/
│       │   └── session.py
│       ├── main.py
│       ├── config.py
│       ├── chunkers/
│       ├── cleaners/
│       ├── embeddings/
│       ├── parsers/
│       └── vectorstore/
├── tests/
│   ├── test_db_check.py
│   ├── test_db_config.py
│   ├── test_db_models.py
│   ├── test_db_session.py
│   └── test_health.py
├── .env.example
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── Makefile
├── pyproject.toml
├── CONTRIBUTING.md
├── LICENSE
├── README.md
└── SECURITY.md
```

## License

RAGRig is licensed under the Apache License 2.0. See [LICENSE](./LICENSE).
