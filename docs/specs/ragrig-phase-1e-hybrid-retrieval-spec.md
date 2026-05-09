# RAGRig Phase 1e Hybrid Retrieval and Reranking Spec

Issue: EVI-76
Date: 2026-05-09
Status: DEV implementation spec

## Scope

This document constrains Phase 1e to the hybrid retrieval (lexical + vector fusion) and reranking capabilities built on top of Phase 1d's dense vector retrieval.

Included in scope:

- deterministic local lexical scorer (BM25-lite token overlap) with no external dependencies
- hybrid retrieval mode combining dense vector and lexical scores via configurable fusion weights
- rerank mode that reorders dense/hybrid candidates using a pluggable reranker
- fake reranker for CI/testing that reorders by query token match ratio
- provider-based reranker integration with graceful degradation on unavailability
- per-result `rank_stage_trace` documenting each scoring stage and its semantics
- ACL filtering executed *before* rerank to prevent unauthorized content from entering the reranker
- Web Console Retrieval Lab controls for mode selection, weight configuration, reranker options, and stage trace display
- `degraded` flag and reason in the response when reranker service is unavailable

Explicitly out of scope:

- answer generation, prompt assembly, or conversation memory
- external lexical indices (Elastic/OpenSearch)
- mandatory heavy ML dependencies (`torch`/`FlagEmbedding` are optional extras)
- query rewriting or multi-hop retrieval
- production embedding provider selection policy changes

## Authority

This specification is subordinate to:

- `docs/specs/ragrig-mvp-spec.md`
- `docs/specs/ragrig-phase-1a-metadata-db-spec.md`
- `docs/specs/ragrig-phase-1b-local-ingestion-spec.md`
- `docs/specs/ragrig-phase-1c-chunking-embedding-spec.md`
- `docs/specs/ragrig-phase-1d-retrieval-api-spec.md`

If this file conflicts with an authority document, the authority documents win.

## Technical Shape

### New Modules

| Module | Purpose |
|--------|---------|
| `src/ragrig/lexical.py` | Deterministic BM25-lite token overlap scorer |
| `src/ragrig/reranker.py` | Fake reranker (CI) + provider-based reranker with degrade logic |

### Modified Modules

| Module | Change |
|--------|--------|
| `src/ragrig/main.py` | `RetrievalSearchRequest` extended with `mode`, weights, `candidate_k`, reranker config |
| `src/ragrig/retrieval.py` | `search_knowledge_base` supports four modes; `RetrievalResult` gains `rank_stage_trace`; `RetrievalReport` gains `degraded`/`degraded_reason` |
| `src/ragrig/web_console.html` | Retrieval Lab gains mode selector, hybrid weights, rerank config, stage trace display, degraded banner |

## Retrieval Modes

`POST /retrieval/search` accepts a `mode` field:

| Mode | Behavior |
|------|----------|
| `dense` (default) | Vector-only retrieval; backward-compatible with Phase 1d |
| `hybrid` | Dense candidates + lexical scorer → fusion → re-ranked by combined score |
| `rerank` | Dense candidates → reranker → re-ranked |
| `hybrid_rerank` | Dense candidates → lexical fusion → reranker → re-ranked |

### New Request Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `mode` | `string` | `"dense"` | One of `dense`, `hybrid`, `rerank`, `hybrid_rerank` |
| `lexical_weight` | `float` | `0.3` | Weight for lexical score in hybrid fusion (0–1) |
| `vector_weight` | `float` | `0.7` | Weight for vector score in hybrid fusion (0–1) |
| `candidate_k` | `int` | `20` | Number of dense candidates to consider for rerank/hybrid (1–200) |
| `reranker_provider` | `string` | `null` | Provider name for reranking; defaults to `reranker.bge` when mode uses rerank |
| `reranker_model` | `string` | `null` | Model name passed to the reranker provider |

All new fields are optional with sensible defaults; old request payloads are fully backward-compatible.

### New Response Fields

Each `result` entry includes a `rank_stage_trace` dict:

```json
{
  "stages": [
    {"stage": "vector", "distance": 0.12, "score": 0.88, "provider": "...", "model": "...", "dimensions": 8},
    {"stage": "lexical", "score": 0.45, "method": "token_overlap_bm25_lite"},
    {"stage": "rerank", "score": 0.72, "original_rank": 2, "new_rank": 1, "reranker": "fake", "model": ""}
  ],
  "final_source": "rerank",
  "weights": {"lexical_weight": 0.3, "vector_weight": 0.7}
}
```

When the reranker is unavailable and the mode requires it, the response includes:

- `degraded`: `true`
- `degraded_reason`: human-readable explanation
- The rerank stage in trace shows `status: "degraded"` with the reason

## Lexical Scorer

`token_overlap_score(chunk_text, query, corpus_texts) → float`

- Tokenizes text into lower-case word-character runs
- When `corpus_texts` is non-empty: uses BM25-lite (BM25 formula with local IDF computation)
- When `corpus_texts` is empty: falls back to pure token overlap ratio
- Returns 0 when query or chunk produce no tokens
- Fully deterministic, no external services or indices required

## Reranker

### Fake Reranker

`fake_rerank(query, candidates) → list[RerankResult]`

- Ranks candidates by ratio of matching query tokens
- Ties broken by original index (stable sort)
- Deterministic, no randomness
- Used by default when no explicit `reranker_provider` is specified and mode is `rerank`/`hybrid_rerank`

### Provider Reranker

`provider_rerank(query, candidates, provider_name, model_name) → list[RerankResult] | None`

- Attempts to use a registered provider (default: `reranker.bge`)
- Returns `None` when provider is not registered or raises `ProviderError`
- Caller must handle degrade: set `degraded=true` and return results in original order

## ACL Filtering

ACL filtering runs in Phase 1 (dense retrieval) **before** reranking:

- Protected chunks are excluded from dense results before candidates are selected for fusion/rerank
- Unauthorized content never enters `rank_stage_trace`
- The reranker never receives texts from chunks the caller is not authorized to see

## Web Console

The Retrieval Lab panel includes:

- **Mode selector**: dropdown with dense/hybrid/rerank/hybrid_rerank
- **Hybrid weights**: visible when mode is hybrid or hybrid_rerank
- **Reranker config**: candidate_k, provider, model fields visible for rerank modes
- **Stage trace**: per-result render of vector/lexical/rerank stages with scores and metadata
- **Degraded banner**: yellow warning when degraded=true in response

## Error Contract

Existing errors unchanged. New behavior:

- Invalid `mode` value → `422` (FastAPI validation)
- Provider unavailable during rerank → `200` with `degraded: true`

## Verification

- `make lint` — `ruff check .` must pass
- `make test` — all tests must pass (including `tests/test_qa_coverage.py`)
- `make coverage` — lexical.py and reranker.py must reach 100% line coverage
- `make web-check` — all web console tests must pass

## Follow-on Work

This slice intentionally prepares, but does not implement:

- Production BM25/ElasticSearch index
- Real BGE reranker deployment (requires optional `torch`/`FlagEmbedding` packages)
- Query rewriting or multi-hop/agentic retrieval
- Answer generation with RAG pipeline
