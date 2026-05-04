# RAGRig Phase 1d Retrieval API and Vector Search Spec

Issue: EVI-32
Date: 2026-05-04
Status: DEV implementation spec

## Scope

This document constrains Phase 1d to the minimum retrieval loop that turns Phase 1c indexed `chunks` and `embeddings` into a queryable API and smokeable CLI path.

Included in scope:

- query-time deterministic-local embedding generation with no external secret
- top-k retrieval over real `chunks` and `embeddings` rows
- latest-document-version filtering so stale chunk versions are not returned by default
- a FastAPI `POST /retrieval/search` contract for developer use
- a CLI smoke command that exercises query -> embedding -> retrieval -> citation output
- automated tests for ranking, top-k, empty query, missing knowledge base, and embedding profile mismatch
- README and operations-record updates for local and `192.168.3.100` verification

Explicitly out of scope:

- answer generation, prompt assembly, or conversation memory
- reranking, hybrid ranking, ACL enforcement, or source filtering
- external embedding providers as a default requirement
- Web UI or background jobs

## Authority

This implementation is subordinate to:

- `docs/specs/ragrig-mvp-spec.md`
- `docs/specs/ragrig-phase-1a-metadata-db-spec.md`
- `docs/specs/ragrig-phase-1b-local-ingestion-spec.md`
- `docs/specs/ragrig-phase-1c-chunking-embedding-spec.md`

If this file conflicts with an authority document, the authority documents win.

## Technical Shape

- FastAPI boundary: `src/ragrig/main.py`
- Retrieval service: `src/ragrig/retrieval.py`
- Existing indexed inputs: `chunks`, `embeddings`, `documents`, `document_versions`, `sources`
- Smoke CLI: `scripts/retrieve_check.py`
- Make wrapper: `make retrieve-check`

The retrieval implementation must sit directly on the existing metadata/indexing schema. It must not hardcode fixture answers or bypass the indexed embeddings path.

## Query Contract

`POST /retrieval/search`

Request body:

- `knowledge_base` (required string)
- `query` (required string, non-empty after trim)
- `top_k` (optional integer, default `5`, allowed range `1..50`)
- `provider` (optional string, current supported value: `deterministic-local`)
- `model` (optional string, current supported value pattern: `hash-<dimensions>d`)
- `dimensions` (optional integer)

Default query embedding profile:

- `provider=deterministic-local`
- `model=hash-8d`
- `dimensions=8`

Phase 1d supports only the deterministic-local profile family produced by Phase 1c. If the caller requests provider/model/dimensions that do not match the indexed deterministic-local rows for the knowledge base, the API returns a structured mismatch error.

## Result Contract

Successful responses return:

- `knowledge_base`
- `query`
- `top_k`
- `provider`
- `model`
- `dimensions`
- `distance_metric=cosine_distance`
- `total_results`
- `results`

Each result row contains:

- `document_id`
- `document_version_id`
- `chunk_id`
- `chunk_index`
- `document_uri`
- `source_uri`
- `text`
- `text_preview`
- `distance`
- `score`
- `chunk_metadata`

`distance` is cosine distance where lower is better. `score` is the simple derived value `1.0 - distance` where higher is better. Phase 1d must not rename or blur these semantics.

## Search Rules

- Retrieval only searches chunks from the latest `document_versions` row per document inside the requested knowledge base.
- If the knowledge base exists but has no indexed embeddings yet, retrieval returns `total_results=0` and an empty `results` array.
- PostgreSQL runtime uses pgvector cosine-distance ordering.
- Non-PostgreSQL test environments may compute the same ranking in Python over persisted vectors so the contract remains testable without pgvector runtime support.

## Error Contract

Structured error payload shape:

```json
{
  "error": {
    "code": "...",
    "message": "...",
    "details": {}
  }
}
```

Required cases:

- missing knowledge base -> `404` / `knowledge_base_not_found`
- empty query -> `400` / `empty_query`
- non-positive `top_k` -> `400` / `invalid_top_k`
- embedding profile mismatch -> `400` / `embedding_profile_mismatch`

Phase 1d does not require a separate error for "not indexed yet" because an empty result set is sufficient and observable.

## CLI Smoke Contract

`scripts/retrieve_check.py` supports:

- `--knowledge-base`
- `--query`
- `--top-k`
- `--dimensions`

Make wrapper:

- `make retrieve-check QUERY="..."`

The CLI must use the host-side runtime DB URL so it respects `DB_HOST_PORT` overrides on `192.168.3.100` and other shared hosts.

## Verification

Repository commands:

- `make format`
- `make lint`
- `make test`
- `make migrate`
- `make ingest-local`
- `make index-local`
- `make retrieve-check QUERY="RAGRig Guide"`

Fresh clone flow:

1. `make sync`
2. `cp .env.example .env`
3. set `DB_HOST_PORT` if host `5432` is occupied
4. `docker compose up --build -d db`
5. `make migrate`
6. `make ingest-local`
7. `make index-local`
8. `make retrieve-check QUERY="RAGRig Guide"`

Required shared-host evidence on `192.168.3.100`:

- migration succeeds after any required port override
- fixture ingestion succeeds before retrieval
- indexing succeeds before retrieval
- retrieval command returns at least one real chunk result
- returned result includes document/document_version/chunk identifiers, chunk index, citation URIs, and provider/model/dimensions
- top-k behavior is visible in command output

## Follow-on Work

This slice intentionally prepares, but does not implement:

- rerankers or lexical fallback
- metadata filters or ACL filters
- answer generation and final citation rendering
- production embedding provider selection policy
