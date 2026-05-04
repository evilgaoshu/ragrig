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

<p align="center">
  <a href="./README.zh-CN.md">中文</a>
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
- **Plugin-first:** keep the core small, then extend sources, sinks, models, vector stores, preview tools, and workflow nodes through explicit contracts.

## Project Status

RAGRig is in early project design and scaffolding.

Current implementation status:

1. Phase 0 docs and project framing are committed.
2. Phase 1a scaffold provides a FastAPI service, local Docker Compose stack, pgvector-enabled PostgreSQL, and verification commands.
3. Phase 1a metadata DB adds SQLAlchemy models, Alembic migrations, and DB smoke commands for the MVP metadata boundary.
4. Phase 1b now supports local Markdown/Text ingestion into the metadata DB, including `document_versions` and pipeline-run tracking.
5. Phase 1c now supports deterministic local chunking and embedding into `chunks` and `embeddings` for the latest ingested document versions.
6. Retrieval APIs, semantic embeddings, and richer source types remain intentionally unimplemented in this repository state.

Authoritative specs:

- [MVP spec](./docs/specs/ragrig-mvp-spec.md)
- [Phase 1a scaffold spec](./docs/specs/ragrig-phase-1a-scaffold-spec.md)
- [Phase 1a metadata DB spec](./docs/specs/ragrig-phase-1a-metadata-db-spec.md)
- [Phase 1b local ingestion spec](./docs/specs/ragrig-phase-1b-local-ingestion-spec.md)
- [Phase 1c chunking and embedding spec](./docs/specs/ragrig-phase-1c-chunking-embedding-spec.md)
- [Web Console spec](./docs/specs/ragrig-web-console-spec.md)
- [Web Console prototype](./docs/prototypes/web-console/index.html)

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

Phase 1b and Phase 1c add these implemented boundaries:

- `src/ragrig/ingestion`
- `src/ragrig/parsers`
- `src/ragrig/repositories`
- `src/ragrig/chunkers`
- `src/ragrig/embeddings`
- `src/ragrig/indexing`

Still reserved for later phases:

- `src/ragrig/cleaners`
- `src/ragrig/vectorstore`

The current repository state supports local Markdown/Text parsing, character-window chunking, and deterministic local embeddings for pgvector-backed smoke validation. Retrieval and production embedding providers are still deferred.

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

8. Preview the local ingestion fixture without writing to the database:

   ```bash
   make ingest-local-dry-run
   ```

9. Ingest the local Markdown/Text fixture into the database:

   ```bash
   make ingest-local
   ```

10. Query the latest local-ingestion run summary:

   ```bash
   make ingest-check
   ```

   Expected output shape:

   ```json
   {
     "counts": {
       "document_versions": 4,
       "documents": 5,
       "pipeline_run_items": 5,
       "sources": 1
     },
     "knowledge_base": {
       "name": "fixture-local"
     },
     "latest_pipeline_run": {
       "failure_count": 0,
       "status": "completed",
       "success_count": 4,
       "total_items": 5
     }
   }
   ```

11. Chunk and embed the latest ingested document versions:

    ```bash
    make index-local
    ```

12. Query the latest chunking and embedding run summary:

    ```bash
    make index-check
    ```

    Expected output shape:

    ```json
    {
      "counts": {
        "chunks": 4,
        "embeddings": 4
      },
      "embedding_dimensions": [
        {
          "count": 4,
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
      }
    }
    ```

13. Start the full local development stack when you also want the API service:

    ```bash
    docker compose up --build
    ```

14. Verify the service and pgvector bootstrap:

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
- `make ingest-local-dry-run`: preview scanned files and skip reasons without DB writes
- `make ingest-local`: ingest the local fixture corpus or an overridden root path into the metadata DB
- `make ingest-check`: query the latest local-ingestion run and document-version evidence
- `make index-local`: chunk and embed the latest ingested document versions for the chosen knowledge base
- `make index-check`: query the latest chunk and embedding run, counts, spans, and embedding dimensions

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

Host-side migration and smoke commands (`make migrate`, `make db-check`) connect through `localhost:${DB_HOST_PORT}` so they work from the machine that launched Docker Compose, even though the application container still uses `DATABASE_URL=postgresql://ragrig:ragrig_dev@db:5432/ragrig` internally.

The same host-side runtime URL rule also applies to `make ingest-local` and `make ingest-check`, so shared-host verification can use alternate mapped DB ports without rewriting the app container path.

## Local Ingestion

Phase 1b currently implements the smallest reproducible local ingestion loop for Markdown and plain text files.

What it does:

- scans an explicit local root path
- applies include and exclude glob filters
- skips excluded, oversized, unsupported, and binary files with recorded reasons
- parses UTF-8 Markdown and text files
- computes SHA-256 file hashes
- writes `sources`, `documents`, `document_versions`, `pipeline_runs`, and `pipeline_run_items`
- avoids duplicate `document_versions` when the file content hash has not changed

What it does not do yet:

- chunking
- embeddings or pgvector writes
- retrieval APIs
- deletion cleanup or tombstones

Default fixture path:

```bash
tests/fixtures/local_ingestion
```

Custom run example:

```bash
uv run python -m scripts.ingest_local \
  --knowledge-base demo \
  --root-path tests/fixtures/local_ingestion \
  --include "*.md" \
  --include "*.txt" \
  --exclude "nested/*"
```

Dry-run example:

```bash
uv run python -m scripts.ingest_local \
  --knowledge-base demo \
  --root-path tests/fixtures/local_ingestion \
  --dry-run
```

## Plugin Architecture

RAGRig is designed as a small core with plugin-first extension points. The core owns workspace state, knowledge bases, documents, versions, chunks, embeddings, pipeline runs, metadata, access boundaries, audit events, and plugin contracts. Integrations live behind typed plugin interfaces.

The goal is not to build a plugin marketplace first. The goal is to make every integration explicit, testable, observable, and replaceable.

Plugin families:

| Family | Purpose | Examples |
| --- | --- | --- |
| Source connectors | Read enterprise knowledge from external systems | local files, SMB/NFS, S3-compatible storage, Google Drive, SharePoint, Confluence, databases |
| Parsers and OCR | Convert raw files into extracted text and structure | Markdown, plain text, PDF, DOCX, XLSX, Docling, MinerU, Tesseract, PaddleOCR |
| Cleaning nodes | Normalize, redact, classify, dedupe, and enrich content | deterministic cleaners, LLM-assisted cleaners, PII redaction, metadata extraction |
| Chunkers | Split document versions into traceable chunks | character windows, Markdown heading chunks, recursive text chunks, table-aware chunks |
| Model providers | Supply LLMs, embedding models, rerankers, OCR, and parsing models | OpenAI-compatible APIs, Ollama, vLLM, llama.cpp, BGE, Jina, Cohere, Voyage |
| Vector backends | Store and search vectors with backend-specific capability reporting | pgvector, Qdrant, Milvus/Zilliz, Weaviate, OpenSearch/Elasticsearch, Redis/Valkey |
| Output sinks | Write governed knowledge or retrieval artifacts elsewhere | S3/R2/MinIO, NFS, relational databases, JSONL, Parquet, Markdown, webhooks, MCP |
| Preview/edit integrations | Let operators inspect or edit source and cleaned knowledge | Markdown editor, WPS, OnlyOffice, Collabora, source-system deep links |
| Evaluation plugins | Measure retrieval and answer quality | golden questions, citation coverage, latency/cost, regression checks |
| Workflow nodes | Compose ingestion, indexing, export, and evaluation pipelines | scan, parse, clean, chunk, embed, index, retrieve, evaluate, export, notify |

### Plugin Tiers

RAGRig separates plugins by stability, priority, and maintenance ownership.

| Tier | Meaning | Ships with core | Extension policy |
| --- | --- | --- | --- |
| Built-in core plugins | Minimal local-first path required for a reproducible RAG pipeline | Yes | Maintained in this repository, no optional external service dependency |
| Official plugins | High-demand integrations maintained by the RAGRig project | Usually optional | May live in this repository first, then move to separate packages as APIs stabilize |
| Community plugins | Third-party integrations built against public contracts | No | Installed through Python packages or plugin manifests once the contract is stable |

Initial built-in core plugins:

| Plugin | Family | Read/write | Why it is core |
| --- | --- | --- | --- |
| `source.local` | Source connector | Read | Fresh-clone demo, fixture validation, shared-host smoke testing |
| `parser.markdown` | Parser | Read | Common documentation format, deterministic tests |
| `parser.text` | Parser | Read | Smallest plain-text ingestion path |
| `chunker.character_window` | Chunker | Write chunks | Reproducible chunking before semantic chunkers exist |
| `embedding.deterministic_local` | Model provider | Write embeddings | Secret-free development and CI validation |
| `vector.pgvector` | Vector backend | Read/write | Default lightweight backend on Postgres |
| `sink.jsonl` | Output sink | Write | Portable debug/export format |
| `preview.markdown` | Preview/edit | Read/write draft | Operator review without needing an office suite |

Priority official plugins:

| Priority | Plugin area | Platforms and protocols to cover first |
| --- | --- | --- |
| P0 | `vector.qdrant` | Qdrant Cloud and self-hosted Qdrant |
| P0 | `model.openai_compatible` | OpenAI, Azure OpenAI-compatible endpoints, vLLM, Ollama, LM Studio, Xinference, llama.cpp servers |
| P0 | `embedding.bge` and `reranker.bge` | BAAI BGE embedding and reranker models, local or OpenAI-compatible serving |
| P1 | `source.s3` | AWS S3, Cloudflare R2, MinIO, Ceph RGW, Wasabi, Backblaze B2 S3 API, Tencent COS S3 API, Alibaba OSS S3-compatible mode when available |
| P1 | `sink.object_storage` | AWS S3, Cloudflare R2, MinIO, Ceph RGW, Wasabi, Backblaze B2, Google Cloud Storage, Azure Blob Storage |
| P1 | `source.fileshare` | SMB/CIFS, NFS, WebDAV, SFTP |
| P1 | `source.google_workspace` | Google Drive, Google Docs, Google Sheets, Google Slides |
| P1 | `source.microsoft_365` | SharePoint, OneDrive, Word, Excel, PowerPoint |
| P1 | `source.wiki` | Confluence, MediaWiki, GitBook, Docusaurus sites, MkDocs sites |
| P1 | `source.database` | PostgreSQL, MySQL/MariaDB, SQL Server, Oracle, SQLite, MongoDB, Elasticsearch/OpenSearch |
| P1 | `preview.office` | WPS document middle platform, OnlyOffice, Collabora Online |
| P2 | `source.collaboration` | Notion, Feishu/Lark Docs, DingTalk Docs, WeCom documents, Slack files, Teams files |
| P2 | `parser.advanced_documents` | PDF layout extraction, DOCX/PPTX/XLSX, Docling, MinerU, Unstructured |
| P2 | `ocr` | PaddleOCR, Tesseract, cloud OCR adapters |
| P2 | `vector.enterprise` | Milvus/Zilliz, Weaviate, OpenSearch/Elasticsearch vector, Redis/Valkey vector, Vespa |
| P2 | `sink.analytics` | Parquet, DuckDB, ClickHouse, BigQuery, Snowflake |
| P2 | `sink.agent_access` | MCP server, webhooks, retrieval API export adapters |

Every plugin should declare:

- plugin id, type, version, and owner
- supported read/write operations
- configuration schema
- secret requirements
- capability matrix
- cursor or incremental-sync support
- delete detection support
- permission mapping support
- failure and retry behavior
- emitted metrics and audit events

Example manifest shape:

```yaml
id: ragrig.source.s3
type: source
version: 0.1.0
capabilities:
  read: true
  write: false
  incremental_sync: true
  delete_detection: true
  permission_mapping: false
config_schema: schemas/s3-source.json
secrets:
  - access_key_id
  - secret_access_key
```

Plugin development will start with internal Python interfaces. Public third-party plugin packaging should wait until the core contracts, test kit, and capability matrix are stable.

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
│   ├── operations/
│   ├── prototypes/
│   ├── roadmap.md
│   └── specs/
│       ├── ragrig-mvp-spec.md
│       ├── ragrig-phase-1a-metadata-db-spec.md
│       ├── ragrig-phase-1a-scaffold-spec.md
│       ├── ragrig-phase-1b-local-ingestion-spec.md
│       ├── ragrig-phase-1c-chunking-embedding-spec.md
│       └── ragrig-web-console-spec.md
├── scripts/
│   ├── db_check.py
│   ├── index_check.py
│   ├── index_local.py
│   ├── ingest_check.py
│   ├── ingest_local.py
│   └── init-db.sql
├── src/
│   └── ragrig/
│       ├── db/
│       │   ├── engine.py
│       │   ├── models/
│       │   └── session.py
│       ├── chunkers/
│       ├── cleaners/
│       ├── embeddings/
│       ├── indexing/
│       ├── ingestion/
│       ├── parsers/
│       ├── repositories/
│       ├── vectorstore/
│       ├── config.py
│       └── main.py
├── tests/
│   ├── fixtures/
│   ├── test_alembic_sql.py
│   ├── test_db_check.py
│   ├── test_db_config.py
│   ├── test_db_models.py
│   ├── test_db_runtime_url.py
│   ├── test_db_session.py
│   ├── test_health.py
│   ├── test_indexing_pipeline.py
│   ├── test_ingestion_pipeline.py
│   ├── test_parsers.py
│   └── test_scanner.py
├── .env.example
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── Makefile
├── pyproject.toml
├── CONTRIBUTING.md
├── LICENSE
├── README.md
├── README.zh-CN.md
└── SECURITY.md
```

## License

RAGRig is licensed under the Apache License 2.0. See [LICENSE](./LICENSE).
