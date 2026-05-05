# RAGRig Vector Backend Status Console Spec

Date: 2026-05-05
Status: implemented in EVI-41

## Goal

Expose real vector backend readiness in both `/system/status` and the lightweight Web Console so operators can tell whether the runtime is using `pgvector` or `qdrant`, whether that backend is healthy, degraded, disabled, or missing a dependency, and what collection/index metadata is actually available from the current service boundary.

## Scope

This spec covers:

- the `/system/status.vector` response shape
- operator-facing vector readiness rendering in `GET /console`
- safe degraded and empty states for missing optional dependencies, unreachable services, missing collections, and unavailable metadata
- score and distance semantics text shown in the Retrieval Lab

This spec does not add:

- destructive vector admin actions
- new vector backends
- browser-triggered rebuild, delete, or migration flows
- fake readiness data that the runtime cannot derive

## `/system/status.vector` Contract

The status API exposes:

```json
{
  "vector": {
    "status": "healthy | degraded | error | disabled",
    "backend": "pgvector | qdrant",
    "health": {
      "healthy": true,
      "distance_metric": "cosine",
      "dependency_status": "ready | missing dependency | unreachable | not configured",
      "provider": "deterministic-local | Multiple profiles | Unavailable from status API",
      "model": "hash-8d | Multiple profiles | Unavailable from status API",
      "total_vectors": 42,
      "error": null,
      "score_semantics": "pgvector uses cosine distance; retrieval score is 1 - distance.",
      "collections": [
        {
          "name": "ragrig_fixture_local_deterministic_lo_hash_8d_8d_0cbfafa4",
          "exists": true,
          "dimensions": 8,
          "distance_metric": "cosine",
          "vector_count": 3,
          "backend": "pgvector",
          "metadata": {
            "provider": "deterministic-local",
            "model": "hash-8d",
            "knowledge_base": "fixture-local",
            "table": "embeddings",
            "index_type": "sql_cosine_distance"
          },
          "unavailable_reason": null
        }
      ],
      "details": {}
    },
    "plugin": {
      "plugin_id": "vector.qdrant",
      "status": "unavailable",
      "reason": "Missing optional dependencies: qdrant_client",
      "missing_dependencies": ["qdrant_client"]
    }
  }
}
```

## Data Derivation Rules

### pgvector

- Backend remains the default fresh-clone path.
- Collection rows are derived from real latest-version embedding profiles in PostgreSQL.
- Each row uses deterministic `build_vector_collection()` naming so the same knowledge-base/provider/model/dimensions tuple can be compared across backends.
- `vector_count` is the persisted embedding count for that profile.
- `provider`, `model`, and `total_vectors` are only reported when the status API can derive them from persisted embeddings. Otherwise the API returns `Unavailable from status API` or `null`.

### qdrant

- Backend remains opt-in through `VECTOR_BACKEND=qdrant`.
- Missing `qdrant-client` reports `status=degraded`, `dependency_status=missing dependency`, and `error="Missing dependency: qdrant-client is not installed."`.
- Expected collections are derived from the same persisted embedding profiles used by pgvector, then reconciled against live Qdrant collection metadata.
- Missing live collections produce `exists=false` plus `unavailable_reason="Collection not found: <name>."`.
- Dimension mismatches produce `status=degraded` plus `unavailable_reason="Dimension mismatch: expected <x>, got <y>."`.
- Collection URLs must be sanitized before display so credentials never appear in the payload.

## Console Layout

### Status Strip

- Add a `Vector Backend` summary card after `Database`.
- Use `repeat(auto-fit, minmax(150px, 1fr))` so six cards do not force horizontal overflow.
- Summary card shows backend name plus `status · dependency_status`.

### Vector Backend Readiness Panel

- Place a full-width panel directly under the status strip and before the main `.grid`.
- Panel head uses:
  - title: `Vector Backend Readiness`
  - meta: `GET /system/status · no secrets`
  - trailing pill: overall vector status
- Panel body uses a two-column desktop layout and collapses to one column at `<=1100px`.
- Left column: summary facts for backend, status, dependency readiness, metric, provider, model, total vectors, plus plugin readiness and full error detail when present.
- Right column: one compact card per collection/index row.

### Retrieval Lab Metadata

- Add a single explanatory line above the retrieval controls:
  - `Backend · metric · score semantics`
- This is descriptive only and does not change retrieval ordering logic.

## Visual Rules

- `healthy` and `ready` use the existing teal `.pill`.
- `degraded`, `warning`, `missing dependency`, and `dimension mismatch` use `.pill.warn`.
- `error`, `unhealthy`, and `unreachable` use `.pill.error`.
- `disabled`, unknown, and unavailable states use `.pill.neutral`.
- Empty collections render with the existing `.empty` block and the exact message `No collection stats returned by status API.`.

## Safety Rules

- Do not show secrets, API keys, credential-bearing URLs, real business payloads, or non-reproducible local filesystem paths.
- Error detail must wrap with `overflow-wrap: anywhere` or equivalent.
- The vector panel must degrade independently; vector errors must not white-screen the full console.

## Verification

Required checks:

- `make format`
- `make lint`
- `make test`
- `make coverage`
- `make web-check`

Runtime evidence should include:

- local or shared-host `/system/status` output showing vector readiness
- Web Console smoke confirmation that the new vector panel renders without horizontal overflow on desktop and mobile-width layouts
