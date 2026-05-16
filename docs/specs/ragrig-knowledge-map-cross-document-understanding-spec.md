# RAGRig Knowledge Map / Cross-document Understanding Spec

Status: implemented initial read path, May 2026.

## Goal

Provide a deterministic knowledge-map layer that turns completed document
understanding output into a cross-document graph for operator review and external
pilot demos.

## Scope

- Build the graph from the latest document version in a knowledge base.
- Use only `completed` understanding records whose input hash still matches the
  current document text.
- Expose a JSON graph at `GET /knowledge-bases/{kb_id}/knowledge-map`.
- Render a read-only Knowledge Map panel in the Web Console.
- Provide `make knowledge-map-check` as deterministic fixture evidence.

Out of scope for this first increment:

- Persisting graph snapshots as a new database table.
- LLM relationship classification beyond extracted-entity overlap.
- Interactive D3 layout, export to PNG/SVG, and manual relationship editing.

## API

`GET /knowledge-bases/{kb_id}/knowledge-map?profile_id=*.understand.default`

Returns:

- `status`: `empty_kb`, `no_understanding`, `limited`, or `ready`.
- `nodes`: document and entity nodes.
- `edges`:
  - `mentions`: document to entity.
  - `shares_entities`: document to document.
  - `co_mentioned`: entity to entity.
- `topic_coverage`: entity-derived topic coverage by document count.
- `stats`: graph and freshness counters.
- `limitations`: missing, stale, failed, or low-coverage caveats.

The endpoint returns `404 {"error": "knowledge_base_not_found"}` for an unknown
or invalid knowledge base ID.

## Freshness Contract

The builder recomputes the understanding input hash from:

```text
profile_id + provider + model + extracted_text
```

If the stored hash does not match, that understanding record is counted as
`stale` and excluded from the graph. This keeps the map aligned with the same
freshness behavior used by understanding coverage.

## Graph Semantics

Document nodes represent latest document versions. Entity nodes are normalized
case-insensitively and deduplicated across documents.

Document relationship strength is:

```text
shared_entity_count / unique_entity_union_count
```

This is intentionally explainable and deterministic. Later P2 work can replace
or augment it with embedding similarity, clustering, and LLM relationship labels
without changing the public graph envelope.

## Verification

Primary checks:

```bash
make knowledge-map-check
uv run pytest tests/test_knowledge_map.py
```

The smoke uses an ephemeral SQLite database, ingests three fixture documents,
runs deterministic understanding, builds the graph, and verifies that
cross-document entities and document relationship edges are present.
