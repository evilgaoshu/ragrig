# EVI-129 — Fake Reranker Production Guard

## Goal

Prevent RAGRig from silently using the deterministic fake reranker in production
when a real reranker provider has not been configured.

## Behavior

- Non-production environments keep the existing local/demo behavior: rerank modes
  may use the deterministic fake reranker when no explicit provider is configured.
- Production environments block that fallback by default.
- Operators can explicitly allow the fallback with:

```text
RAGRIG_ALLOW_FAKE_RERANKER=true
```

This override is intended only for demos or explicitly accepted degraded
environments.

## Runtime Contract

When `APP_ENV=production` and `RAGRIG_ALLOW_FAKE_RERANKER` is not true:

- `mode=rerank` without an explicit real reranker raises `fake_reranker_disabled`.
- `/retrieval/search` returns HTTP 503 with the structured retrieval error.
- `/retrieval/answer` returns HTTP 503 before answer generation if retrieval needs
  the blocked fake reranker.
- `/health` includes a `reranker` policy object showing that fake fallback is
  blocked.

Explicit reranker provider failures remain a degraded retrieval path for now. This
issue only prevents the implicit fake fallback from being mistaken for production
reranking.

## Health Payload

`/health` includes:

```json
{
  "reranker": {
    "status": "blocked",
    "provider": "reranker.bge",
    "fake_reranker_allowed": false,
    "policy": "production_requires_real_reranker",
    "detail": "Fake reranker fallback is disabled in production; configure a real reranker or set RAGRIG_ALLOW_FAKE_RERANKER=true.",
    "app_env": "production"
  }
}
```

## Verification

```bash
uv run pytest tests/test_db_config.py tests/test_health.py tests/test_health_unit.py tests/test_retrieval.py -q
uv run ruff check src/ragrig/config.py src/ragrig/health.py src/ragrig/reranker.py src/ragrig/retrieval.py src/ragrig/main.py tests/test_db_config.py tests/test_health.py tests/test_health_unit.py tests/test_retrieval.py
```
