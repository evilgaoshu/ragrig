# RAGRig Phase 1b Local Ingestion Spec

Issue: EVI-30
Date: 2026-05-03
Status: DEV implementation spec

## Scope

This document constrains the Phase 1b local ingestion slice to the minimum Markdown/Text pipeline that can create real `document_versions` on top of the Phase 1a metadata DB foundation.

Included in scope:

- Local directory scanning driven by CLI arguments or Makefile variables.
- Markdown and plain text parsing with UTF-8 decoding, SHA-256 content hashing, and basic file metadata.
- Persistent writes for `knowledge_bases`, `sources`, `documents`, `document_versions`, `pipeline_runs`, and `pipeline_run_items`.
- Explicit skip and failure tracking for unsupported extensions, excluded files, binary files, oversized files, unchanged content, and parse failures.
- A minimal CLI entrypoint and DB check script for local and `192.168.3.100` smoke validation.
- Fixture data, automated tests, README updates, and an operations record for the shared environment.

Explicitly out of scope:

- chunking
- embeddings or pgvector writes
- retrieval APIs
- answer generation
- PDF, DOCX, PPTX, XLSX, crawler, connector, watch mode, Web UI, ACL, or cleanup of deleted files

## Authority

This implementation is subordinate to:

- `docs/specs/ragrig-mvp-spec.md`
- `docs/specs/ragrig-phase-1a-metadata-db-spec.md`

If this file conflicts with either authority document, the authority documents win.

## Technical Shape

- Scanner entrypoint: `src/ragrig/ingestion/scanner.py`
- Pipeline entrypoint: `src/ragrig/ingestion/pipeline.py`
- Parser boundary: `src/ragrig/parsers/base.py`, `markdown.py`, `plaintext.py`
- Repository boundary: `src/ragrig/repositories/`
- CLI entrypoint: `scripts/ingest_local.py`
- Smoke query entrypoint: `scripts/ingest_check.py`

The pipeline remains CLI-first. FastAPI ingestion endpoints are deferred.

## Scanner Rules

Defaults:

- include patterns: `*.md`, `*.markdown`, `*.txt`, `*.text`
- excluded directories: `.git`, `__pycache__`, `.venv`, `.tox`, `node_modules`
- max file size: `10 MiB`

Skip reasons tracked in `pipeline_run_items.metadata_json`:

- `unsupported_extension`
- `excluded`
- `file_too_large`
- `binary_file`
- `unchanged`

Files are never discovered from a home directory or arbitrary large path by default. The operator must pass `--root-path` or `INGEST_ROOT` explicitly.

## Parser Contract

Each parser returns:

- `extracted_text`
- `content_hash` as SHA-256 hex digest of raw bytes
- `mime_type`
- `parser_name`
- metadata containing at least `encoding`, `extension`, `line_count`, and `char_count`

Phase 1b does not extract Markdown headings, front matter, page references, or semantic structure. The stored extracted text is the raw decoded file content.

## Persistence Rules

- `knowledge_bases` is created or reused by name.
- A single local root path maps to one `sources` row with `kind=local_directory`.
- Every discovered or tracked file maps to one `documents` row by `(knowledge_base_id, uri)`.
- Successful parse writes create `document_versions` rows.
- Unsupported, excluded, binary, oversized, or failed files may still create or update `documents` rows so `pipeline_run_items` can point to a durable file identity.

## Versioning And Idempotency

- First successful ingest of a file creates `document_versions.version_number = 1`.
- Re-ingesting identical file bytes does not create a new `document_versions` row.
- Content changes create the next sequential version number.
- Deleted files are not handled in Phase 1b. Existing `documents` rows remain and no tombstone state is introduced in this slice.

## Run Recording

One CLI invocation produces one `pipeline_runs` row with:

- `run_type=local_ingestion`
- `status` in `running`, `completed`, or `completed_with_failures`
- total item count
- success count based on new versions written
- failure count based on per-file parse/write failures
- config snapshot including root path, include/exclude patterns, max file size, and dry-run flag

Each tracked file produces one `pipeline_run_items` row for that run with:

- `status` in `success`, `skipped`, or `failed`
- `error_message` for failures
- `metadata_json` containing at least `file_name` and any skip reason or version number

File-level failures must not roll back the whole run. Per-file nested transaction boundaries are used so a bad file still records failure while good files continue.

## CLI Contract

`scripts/ingest_local.py` supports:

- `--knowledge-base`
- `--root-path`
- repeatable `--include`
- repeatable `--exclude`
- `--max-file-size-bytes`
- `--dry-run`

Makefile wrappers:

- `make ingest-local`
- `make ingest-local-dry-run`
- `make ingest-check`

The CLI uses the host-side runtime DB URL path so it works with `DB_HOST_PORT` overrides on shared hosts such as `192.168.3.100`.

## Fixture Corpus

Fixture directory: `tests/fixtures/local_ingestion`

Required contents:

- one Markdown file
- one text file
- one nested Markdown file
- one empty text file
- one unsupported binary-like fixture for skip behavior

These fixtures are test-only data and must remain reproducible.

## Verification

Repository commands:

- `make format`
- `make lint`
- `make test`
- `make migrate`
- `make ingest-local-dry-run`
- `make ingest-local`
- `make ingest-check`

Fresh clone flow:

1. `make sync`
2. `cp .env.example .env`
3. set `DB_HOST_PORT` if host `5432` is occupied
4. `docker compose up --build -d db`
5. `make migrate`
6. `make ingest-local`
7. `make ingest-check`

Required shared-host evidence on `192.168.3.100`:

- migration replay succeeds after any necessary `DB_HOST_PORT` override
- fixture ingestion succeeds
- latest `pipeline_runs` row shows expected status and counts
- counts for `sources`, `documents`, `document_versions`, and `pipeline_run_items` are queryable
- at least one `document_versions` row shows `content_hash` and extracted content preview

## Follow-on Work

This slice intentionally prepares, but does not implement:

- cleaner normalization before chunking
- chunk creation from `document_versions`
- embeddings and pgvector writes from `chunks`
- retrieval APIs over chunk and embedding tables
- deleted-file cleanup or tombstoning
