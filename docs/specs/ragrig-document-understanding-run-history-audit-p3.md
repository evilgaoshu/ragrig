# RAGRig Document Understanding Run History & Audit (P3)

**Spec Version**: 1.0
**Issue**: EVI-62
**Date**: 2026-05-09

## Objective

Enable `POST /knowledge-bases/{kb_id}/understand-all` executions to produce
persistent, queryable run history records for audit and traceability. Each run
records: who triggered it, with what parameters, when it started/finished,
what status it ended with, and a safe error summary (no secrets, full prompts,
or full source text).

## Scope

### In Scope

- `UnderstandingRun` database model and alembic migration
- Run record creation inside `understand_all_versions()` (one record per invocation)
- Deterministic run status: `success`, `partial_failure`, `all_failure`, `empty_kb`
- API endpoints:
  - `POST /knowledge-bases/{kb_id}/understand-all` — returns `run_id` in response
  - `GET /knowledge-bases/{kb_id}/understanding-runs` — list runs for a KB (with optional filters)
  - `GET /understanding-runs/{run_id}` — run detail with KB name
  - `GET /understanding-runs` — web console list endpoint (with optional `knowledge_base_id` query param)
- Web Console: "Understanding Runs" panel showing recent runs (status, counts, error summary)
- Web Console: rerun button using historical parameters
- Safe error summaries that never leak secrets or full source text
- Tests for all new functionality

### Best-effort

- Filtering by `provider`, `model`, `profile_id`, `status` on `GET /knowledge-bases/{kb_id}/understanding-runs`
- `trigger_source` and `operator` (via `X-Operator` header) for audit trail

### Out of Scope

- Distributed queue, long-task cancellation/scheduling
- Manual annotation platform
- Multi-tenant RBAC
- Cloud live smoke tests
- Export run JSON / run diff (left as future enhancement)

## Data Model

### UnderstandingRun

| Column | Type | Notes |
|--------|------|-------|
| `id` | UUID (PK) | Auto-generated |
| `knowledge_base_id` | UUID (FK) | References knowledge_bases.id, CASCADE delete |
| `provider` | VARCHAR(128) | Understanding provider name |
| `model` | VARCHAR(255) | Model identifier (empty string if n/a) |
| `profile_id` | VARCHAR(255) | Processing profile ID |
| `trigger_source` | VARCHAR(128) | "api", "web_console", etc. |
| `operator` | VARCHAR(255) | User/agent identifier (nullable) |
| `status` | VARCHAR(32) | success / partial_failure / all_failure / empty_kb |
| `total` | INTEGER | Total document versions processed |
| `created` | INTEGER | New understandings generated |
| `skipped` | INTEGER | Documents already up-to-date |
| `failed` | INTEGER | Documents that errored |
| `error_summary` | TEXT | Safe error summary (max 2000 chars) |
| `started_at` | TIMESTAMPTZ | Run start time |
| `finished_at` | TIMESTAMPTZ | Run end time (nullable) |
| `created_at` | TIMESTAMPTZ | Record creation (auto) |
| `updated_at` | TIMESTAMPTZ | Record update (auto) |

## Run Status Logic

```
total == 0                    → empty_kb
total > 0 && failed == 0     → success
total > 0 && failed == total → all_failure
total > 0 && 0 < failed < total → partial_failure
```

Each invocation always creates a new run record, even if all documents were
skipped (resulting in `success` with skipped = total).

## Security

- `error_summary` truncates individual error messages to 200 chars and the
  full summary to 2000 chars
- No provider secrets, full prompts, or full document text are included in
  API responses or error summaries
- `x-operator` header is the only mechanism for operator attribution; no
  authentication is required for backwards compatibility

## API Contract

### POST /knowledge-bases/{kb_id}/understand-all

**Request body**:
```json
{
  "provider": "deterministic-local",
  "model": null,
  "profile_id": "*.understand.default"
}
```

**Response** (200):
```json
{
  "run_id": "uuid-string",
  "total": 3,
  "created": 1,
  "skipped": 1,
  "failed": 1,
  "errors": [
    {"version_id": "uuid-string", "error": "safe error message"}
  ]
}
```

### GET /knowledge-bases/{kb_id}/understanding-runs

Query params: `provider`, `model`, `profile_id`, `status`, `limit` (default 50)

Response:
```json
{
  "runs": [
    {
      "id": "uuid",
      "knowledge_base_id": "uuid",
      "provider": "...",
      "model": "...",
      "profile_id": "...",
      "trigger_source": "api",
      "operator": null,
      "status": "success",
      "total": 3,
      "created": 2,
      "skipped": 1,
      "failed": 0,
      "error_summary": null,
      "started_at": "2026-05-09T...",
      "finished_at": "2026-05-09T..."
    }
  ]
}
```

### GET /understanding-runs/{run_id}

Response (404 if not found):
```json
{
  "id": "uuid",
  "knowledge_base_id": "uuid",
  "knowledge_base": "kb-name",
  "provider": "...",
  ...
}
```

### GET /understanding-runs

Query params: `knowledge_base_id` (optional), `limit` (default 20)

Response (web console format):
```json
{
  "items": [
    {
      "id": "uuid",
      "knowledge_base_id": "uuid",
      "knowledge_base": "kb-name",
      ...
    }
  ]
}
```

## Verification Commands

```bash
make lint        # ruff check — all pass
make test        # pytest — 462 pass, 9 skip
make coverage    # pytest --cov — 99.92% (required 90%)
make web-check   # pytest tests/test_web_console.py — 43 pass
```

## Files Changed

| File | Change |
|------|--------|
| `src/ragrig/db/models/entities.py` | Added `UnderstandingRun` model, `KnowledgeBase.understanding_runs` relationship |
| `src/ragrig/db/models/__init__.py` | Export `UnderstandingRun` |
| `alembic/versions/20260509_0003_add_understanding_runs.py` | New migration |
| `src/ragrig/understanding/schema.py` | Added `UnderstandingRunRecord`, `UnderstandingRunFilter` |
| `src/ragrig/understanding/__init__.py` | Export new types and functions |
| `src/ragrig/understanding/service.py` | Added `_run_status_from_result`, `_safe_error_summary`, `get_understanding_runs`, `get_understanding_run`; updated `understand_all_versions` to persist run records |
| `src/ragrig/main.py` | Added `GET /understanding-runs`, `GET /understanding-runs/{run_id}`, `GET /knowledge-bases/{kb_id}/understanding-runs`; updated `POST /.../understand-all` to return `run_id` and accept `X-Operator` header |
| `src/ragrig/web_console.py` | Added `_serialize_understanding_run`, `list_understanding_runs`, `get_understanding_run_detail` |
| `src/ragrig/web_console.html` | Added "Understanding Runs" panel with rerun capability |
| `tests/test_understanding.py` | Added 17 new tests covering run persistence, status derivation, filtering, API endpoints |
