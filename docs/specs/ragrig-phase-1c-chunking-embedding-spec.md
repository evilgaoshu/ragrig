# RAGRig Phase 1c Chunking, Embedding, and pgvector Indexing Spec

Issue: EVI-31
Date: 2026-05-03
Status: DEV implementation spec

## Scope

This document constrains Phase 1c to the minimum chunking and embedding loop that turns Phase 1b `document_versions` into durable `chunks` and `embeddings` rows in PostgreSQL with pgvector enabled.

Included in scope:

- chunk generation from the latest ingested `document_versions.extracted_text`
- deterministic local embeddings that require no external secret for default verification
- persistent writes for `chunks`, `embeddings`, `pipeline_runs`, and `pipeline_run_items`
- idempotent re-runs for unchanged document versions under the same chunking and embedding configuration
- a CLI entrypoint and DB check script for local and `192.168.3.100` smoke validation
- automated tests, README updates, and a validation record for the shared environment

Explicitly out of scope:

- retrieval APIs or vector search endpoints
- semantic chunkers, token-aware chunking, rerankers, or answer generation
- external embedding providers as a hard requirement
- ACL enforcement, source deletion cleanup, or background watch mode

## Authority

This implementation is subordinate to:

- `docs/specs/ragrig-mvp-spec.md`
- `docs/specs/ragrig-phase-1a-metadata-db-spec.md`
- `docs/specs/ragrig-phase-1b-local-ingestion-spec.md`

If this file conflicts with an authority document, the authority documents win.

## Technical Shape

- Chunker boundary: `src/ragrig/chunkers/__init__.py`
- Embedding boundary: `src/ragrig/embeddings/__init__.py`
- Indexing pipeline: `src/ragrig/indexing/pipeline.py`
- Repository queries: `src/ragrig/repositories/`
- CLI entrypoint: `scripts/index_local.py`
- Smoke query entrypoint: `scripts/index_check.py`

The pipeline remains CLI-first in this phase. FastAPI retrieval or indexing endpoints are deferred.

## Chunking Rules

- Chunk input is always the latest persisted `document_versions.extracted_text` for each document in a knowledge base.
- Default chunker is `char_window_v1` with `chunk_size=500` and `chunk_overlap=50`.
- If a caller passes `chunk_overlap >= chunk_size`, the pipeline normalizes overlap to `chunk_size - 1` so small custom chunk sizes remain valid.
- Empty extracted text is not chunked; the run item is recorded as `skipped` with `skip_reason=empty_extracted_text`.

Each chunk stores:

- `chunk_index`
- `text`
- `char_start`
- `char_end`
- `metadata_json` containing at least:
  - `chunker`
  - `chunk_size`
  - `chunk_overlap`
  - `config_hash`
  - `chunk_hash`
  - `text_length`
  - `content_hash`
  - `document_uri`
  - `parser_name`
  - `version_number`

Phase 1c does not add heading extraction, page references, sentence boundaries, or Markdown semantic sectioning.

## Embedding Provider Contract

Phase 1c hard-requires a deterministic local provider only.

Provider identity:

- `provider=deterministic-local`
- `model=hash-<dimensions>d`
- default `dimensions=8`

Provider rules:

- input text always produces the same vector for the same dimensions
- vectors are stored in `embeddings.embedding` using pgvector
- `metadata_json` includes at least `text_hash`, `config_hash`, and `document_version_id`

This provider is for reproducible development, testing, and smoke validation only. It must not be described as a semantic production embedding model.

## Idempotency And Reindexing

- The indexing command only targets the latest version per document in the chosen knowledge base.
- If a latest document version already has chunks with the same `config_hash` and embeddings with the same provider/model, the run item is recorded as `skipped` with `skip_reason=already_indexed`.
- If the latest version changes because Phase 1b ingestion writes a new `document_versions` row, Phase 1c indexes the new version and leaves prior-version chunks and embeddings intact for traceability.
- If a latest version already has chunks but the chunking config changes, the pipeline replaces the chunks and embeddings for that exact `document_version_id`.

## Run Recording

One indexing invocation produces one `pipeline_runs` row with:

- `run_type=chunk_embedding`
- `status` in `running`, `completed`, or `completed_with_failures`
- total item count equal to the number of latest document versions considered
- success count based on versions indexed in the run
- failure count based on per-document indexing failures
- config snapshot including chunker config and deterministic embedding provider/model/dimensions

Each considered document produces one `pipeline_run_items` row with:

- `status` in `success`, `skipped`, or `failed`
- `error_message` for failures
- `metadata_json` containing at least `document_version_id`, `version_number`, and either skip reason or chunk/embedding counts

Document-level failures must not roll back the whole run. Nested transaction boundaries continue to isolate failures.

## CLI Contract

`scripts/index_local.py` supports:

- `--knowledge-base`
- `--chunk-size`
- `--chunk-overlap`
- `--embedding-dimensions`

Makefile wrappers:

- `make index-local`
- `make index-check`

The CLI uses the host-side runtime DB URL path so it works with `DB_HOST_PORT` overrides on shared hosts such as `192.168.3.100`.

## Verification

Repository commands:

- `make format`
- `make lint`
- `make test`
- `make migrate`
- `make ingest-local`
- `make index-local`
- `make ingest-check`
- `make index-check`

Fresh clone flow:

1. `make sync`
2. `cp .env.example .env`
3. set `DB_HOST_PORT` if host `5432` is occupied
4. `docker compose up --build -d db`
5. `make migrate`
6. `make ingest-local`
7. `make index-local`
8. `make index-check`

Required shared-host evidence on `192.168.3.100`:

- migration replay succeeds after any necessary `DB_HOST_PORT` override
- fixture ingestion succeeds before indexing
- chunking and embedding command succeeds without external secrets
- counts for `chunks` and `embeddings` are queryable
- embedding provider, model, and dimensions are queryable
- latest `pipeline_runs` row for `chunk_embedding` shows expected status and counts
- at least one chunk row shows chunk index, span, and preview text

## Follow-on Work

This slice intentionally prepares, but does not implement:

- retrieval API and vector similarity queries
- lexical fallback or hybrid ranking
- external embedding providers and provider selection policy
- semantic chunking and content-aware document structure
