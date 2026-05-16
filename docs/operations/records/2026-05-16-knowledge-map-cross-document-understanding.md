# Knowledge Map / Cross-document Understanding

Date: 2026-05-16

## Summary

Implemented the initial knowledge-map read path for cross-document
understanding. The map is derived from fresh `document_understandings` records,
links documents through shared extracted entities, and exposes graph data to the
API and Web Console.

## Scope

- Added `ragrig.understanding.knowledge_map` graph builder.
- Added `GET /knowledge-bases/{kb_id}/knowledge-map`.
- Added Web Console Knowledge Map summary panel.
- Added deterministic smoke script and Make target:

```bash
make knowledge-map-check
```

Primary artifact:

```text
docs/operations/artifacts/knowledge-map-check.json
```

## Verification Plan

Required before merge:

```bash
uv run pytest tests/test_knowledge_map.py tests/test_understanding.py -q
make knowledge-map-check
make lint
make test
```

## Notes

The first implementation does not add a graph persistence table. It computes
the map from the latest document versions and excludes stale understanding
records by recomputing the same input hash used by understanding coverage.
