# RAGRig Qdrant Vector Backend Spec

## Goal

Add a unified vector backend contract for RAGRig so `pgvector` remains the default fresh-clone path while `qdrant` becomes an explicit optional backend that can be enabled without changing the core runtime dependency set.

## Contract

The vector backend boundary lives under `src/ragrig/vectorstore/` and uses a `Protocol` plus dataclasses instead of an ABC. The contract covers:

- deterministic collection naming via `build_vector_collection()`
- collection lifecycle through `ensure_collection()`
- vector upsert through `upsert_embeddings()`
- vector delete/tombstone through `delete_embeddings()`
- search/top-k through `search()`
- backend health and capability reporting through `health()`

The shared DTOs are:

- `VectorCollection`
- `VectorEmbeddingRecord`
- `VectorSearchResult`
- `VectorCollectionStatus`
- `VectorBackendHealth`

## Backend Semantics

### pgvector

- PostgreSQL remains the authority for knowledge base metadata, document/chunk lineage, and embeddings rows.
- Default runtime backend is `pgvector`.
- Existing indexing persists embeddings into the `embeddings` table exactly as before.
- Retrieval still uses SQL cosine distance on PostgreSQL and Python cosine distance on SQLite tests.

### Qdrant

- Qdrant stores vectors plus payload needed for retrieval and metadata round-tripping.
- Qdrant is opt-in via `VECTOR_BACKEND=qdrant`.
- `qdrant-client` is installed only through the `vectorstores` extra.
- If `qdrant-client` is not installed, core imports, health, tests, and the default pgvector path continue to work.

## Score And Distance Semantics

Cross-backend ranking is normalized on `score`, descending.

- pgvector cosine path:
  - raw DB value is cosine distance
  - `distance = cosine_distance`
  - `score = 1 - distance`
  - report `distance_metric = cosine_distance`

- Qdrant cosine path:
  - raw backend value is cosine similarity
  - `score = cosine_similarity`
  - `distance = 1 - score`
  - report `distance_metric = cosine_similarity`

This prevents mixed backend result ordering ambiguity while preserving raw distance/similarity interpretation in the response.

## Collection Naming

Collection names must be deterministic, traceable, legal, and bounded.

Current rule:

- prefix with `ragrig_`
- include slugged knowledge base, provider, model, and dimensions
- suffix with a short stable hash
- bound total length to 63 characters

This keeps names safe for Qdrant and predictable for debugging.

## Configuration

New settings:

- `VECTOR_BACKEND=pgvector|qdrant`
- `QDRANT_URL=http://localhost:6333`
- `QDRANT_API_KEY=` optional

Default remains:

```env
VECTOR_BACKEND=pgvector
```

## Retrieval Contract

Retrieval API returns the same base shape across backends:

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

Report-level metadata now also exposes:

- `backend`
- `backend_metadata`

Default pgvector shape is preserved and extended without removing existing fields.

## Health And Status

`/system/status` includes a `vector` section that reports:

- configured backend
- healthy/degraded status
- distance metric
- backend details

The Web Console can consume the same service boundary without hardcoding a specific vector store.

## Verification

Required checks:

- `make format`
- `make lint`
- `make test`
- `make coverage`

Optional Qdrant smoke is explicit only:

- `docker compose --profile qdrant up -d qdrant`
- `make qdrant-check`
- `make vector-check QUERY="..."`

Default fresh clone must not require:

- a running Qdrant process
- network access to Qdrant Cloud
- extra secrets

## Limitations

- pgvector remains the write-path source of truth in PostgreSQL.
- The current implementation mirrors embeddings to Qdrant only when an explicit backend is injected or configured.
- No online migration tool is provided.
- No other vector backends are added in this spec.
- Shared-environment `192.168.3.100` live smoke is still required for final runtime verification when Qdrant deployment validation is requested by PM.

## Future Extension Points

- capability matrix for Milvus / Weaviate / OpenSearch
- standardized backend contract test kit
- rebuild/export tooling from PostgreSQL embeddings into alternate backends
