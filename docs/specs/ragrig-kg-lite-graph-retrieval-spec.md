# RAGRig KG-lite and Graph-aware Retrieval Spec

## Scope

This spec covers the first production path for source-backed graph retrieval:

- P0: demo stability, answer citation trust, explainable retrieval traces, and a golden demo gate.
- P1: persistent KG-lite entities, mentions, relations, relation evidence, and claims.
- P2: graph-aware retrieval modes that augment dense/hybrid/rerank retrieval without replacing them.

## Non-goals

- KG-lite is not the default retrieval path.
- KG facts are not treated as final answer evidence by themselves.
- Graph extraction is intentionally conservative and can run deterministically for local/CI use.
- Native Neo4j, community detection, and LLM entity-resolution workflows are later GraphRAG phases.

## Data Model

KG-lite uses these persisted tables:

- `kg_entities`: canonical entity records scoped to a knowledge base and workspace.
- `kg_entity_mentions`: chunk-level entity mentions with span offsets when available.
- `kg_relations`: subject-predicate-object entity edges.
- `kg_relation_evidence`: source chunks supporting relation edges.
- `kg_claims`: source-backed claims anchored to one chunk.

Every relation and claim must resolve back to a source chunk. Graph answers must still cite chunks,
not graph rows alone.

## API

- `GET /knowledge-bases/{kb_id}/knowledge-graph`
  returns KG-lite stats, entities, relation evidence, claims, and limitations.

- `POST /knowledge-bases/{kb_id}/knowledge-graph/rebuild`
  rebuilds KG-lite rows from latest indexed chunks and fresh understanding output when available.

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

If KG-lite rows are missing, graph modes degrade without breaking dense retrieval.

Relation paths in `retrieval_trace.graph_context` include predicate weight,
feedback weight, feedback summary, evidence score, and diagnostics describing
suppressed relations. This keeps graph boosts explainable during console
strategy comparison and eval review.

## Demo Gate

The fixture `tests/fixtures/evaluation_golden_demo_graph.yaml` covers:

- single-hop factual questions
- citation trust
- cross-document multi-hop questions
- global synthesis
- conflict-sensitive credential behavior

These categories should remain represented before an external demo.

## Verification

Required checks for this feature:

- KG-lite model/API tests: `tests/test_knowledge_graph.py`
- Golden fixture validation: `tests/test_evaluation_golden_fixtures.py`
- Retrieval and answer regressions: `tests/test_retrieval.py`, `tests/test_answer.py`
- Knowledge map regression: `tests/test_knowledge_map.py`
- Alembic SQL rendering: `tests/test_alembic_sql.py`
- Local pilot/demo stability: local pilot and nightly evidence smoke tests
- Frontend build and lint
