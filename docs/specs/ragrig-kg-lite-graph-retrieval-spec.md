# RAGRig Graph-RAG P0 Spec

## Scope

This spec covers the first production path for source-backed graph retrieval:

- P0: demo stability, answer citation trust, explainable retrieval traces, and a golden demo gate.
- P1: persistent KG-lite entities, mentions, relations, relation evidence, and claims.
- P2: graph-aware retrieval modes that augment dense/hybrid/rerank retrieval without replacing them.
- P0 Graph-RAG: optional `kg_extract` indexing stage, provider seam, entity-level and
  relationship-level retrieval, stable degradation codes, and an auditable eval gate.

## Non-goals

- KG-lite is not the default retrieval path.
- KG facts are not treated as final answer evidence by themselves.
- Graph extraction is intentionally conservative and can run deterministically for local/CI use.
- Native Neo4j, community detection, and LLM entity-resolution workflows are later GraphRAG phases.
- Apache AGE may be added behind an adapter later; it is not required and cannot replace
  the Postgres source-of-truth or chunk/document citation contract.

## Data Model

KG-lite uses these persisted tables:

- `kg_entities`: canonical entity records scoped to a knowledge base and workspace.
- `kg_entity_mentions`: chunk-level entity mentions with span offsets when available.
- `kg_relations`: subject-predicate-object entity edges.
- `kg_relation_evidence`: source chunks supporting relation edges.
- `kg_claims`: source-backed claims anchored to one chunk.

Every relation and claim must resolve back to a source chunk. Graph answers must still cite chunks,
not graph rows alone.

## Extraction Pipeline

`index_knowledge_base(..., kg_extract=True)` runs the optional sequence:

`chunk -> embed -> index -> optional kg_extract`

The extraction stage uses the same `PipelineRun` as indexing. Its configuration and result are
stored in `PipelineRun.config_snapshot_json`; every persisted graph row receives the trace ID,
pipeline run ID, extractor name/version, and profile ID in metadata. A `kg_extract` audit event
records successful or failed extraction without storing chunk text.
The KB build trace stores source document-version and chunk-ID fingerprints so a same-version force
reindex is reported as `graph_stale` instead of silently using incomplete graph evidence.

The default path is deterministic and understanding-aware for CI/local use.
`KnowledgeGraphExtractor` is the provider seam for future LLM extractors. Provider output must
include source-backed entities, relationships, and claims with confidence and metadata. Output
whose source chunk is not in the current indexed corpus is ignored.

## API

- `GET /knowledge-bases/{kb_id}/knowledge-graph`
  returns KG-lite stats, entities, relation evidence, claims, and limitations.

- `POST /knowledge-bases/{kb_id}/knowledge-graph/rebuild`
  rebuilds KG-lite rows from latest indexed chunks and fresh understanding output when available.

- `POST /knowledge-bases/{kb_id}/knowledge-graph/relations/{relation_id}/feedback`
  records correct, incorrect, or needs-review feedback on a relation edge.

- `GET /knowledge-bases/{kb_id}/retrieval-preferences`
  returns the KB-level Console retrieval mode preference.

- `PUT /knowledge-bases/{kb_id}/retrieval-preferences`
  stores the KB-level Console retrieval mode preference without changing API defaults.

- `POST /retrieval/search`
  accepts these additional modes:
  - `graph`
  - `hybrid_graph`
  - `graph_rerank`
  - `hybrid_graph_rerank`

- `POST /retrieval/answer`
  accepts the same graph-aware modes and returns `retrieval_trace.result_traces` plus
  `retrieval_trace.graph_context`.

## Retrieval Behavior

Graph-aware retrieval performs:

1. Dense retrieval as the base candidate set.
2. KG entity linking against the query, including stored aliases and compact
   CamelCase / spaced-name variants.
3. One-hop relation expansion by default, with relation feedback suppressing
   edges marked incorrect before chunk boosting.
4. Chunk rehydration through the same latest-version embedding statement used by dense retrieval.
5. ACL filtering before graph-expanded chunks reach reranking or answer generation.
6. Score fusion with a configurable `graph_weight`.

`graph_context` separates:

- `matched_entities`: entity/alias-level matches.
- `matched_relationships`: relation-level matches with chunk, document, and document-version
  evidence.
- `relation_paths`: explainable path expansion and feedback weighting.
- `chunk_scores`: graph evidence score by chunk.
- `rank_movement`: before/after rank and score changes caused by graph expansion.

If graph evidence is unavailable, graph modes degrade without breaking dense/hybrid retrieval.
Stable reason codes are:

- `graph_no_data`
- `graph_stale`
- `graph_extraction_failed`
- `graph_acl_no_evidence`
- `graph_no_match`
- `graph_unavailable`

Relation paths in `retrieval_trace.graph_context` include predicate weight,
feedback weight, feedback summary, evidence score, and diagnostics describing
suppressed relations. This keeps graph boosts explainable during console
strategy comparison and eval review.

The Web Console exposes a Graph Explorer for entities, relations, claims, source
evidence, and relation feedback. Retrieval Lab can load/save KB-level mode
preferences so an external demo can keep `hybrid_graph` selected without
changing default API behavior for other callers.

## Demo Gate

The fixture `tests/fixtures/evaluation_golden_demo_graph.yaml` covers:

- single-hop factual questions
- citation trust
- cross-document multi-hop questions
- global synthesis
- conflict-sensitive credential behavior
- X/Y relationship questions and cross-document relationships
- relation feedback suppression and graph score changes
- chunk/document-backed citation contracts

These categories should remain represented before an external demo.

## Verification

Required checks for this feature:

- KG-lite model/API tests: `tests/test_knowledge_graph.py`
- Graph-RAG eval gate and artifact: `make graph-eval-compare`
- Golden fixture validation: `tests/test_evaluation_golden_fixtures.py`
- Retrieval and answer regressions: `tests/test_retrieval.py`, `tests/test_answer.py`
- Knowledge map regression: `tests/test_knowledge_map.py`
- Alembic SQL rendering: `tests/test_alembic_sql.py`
- Local pilot/demo stability: local pilot and nightly evidence smoke tests
- External demo runbook: `make demo-graph-console-runbook` for evidence and
  `make demo-graph-console` to prepare the demo DB and start the React Console root `/`
- Frontend build and lint
