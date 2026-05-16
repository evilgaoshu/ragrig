# EVI-141 — Reranker Policy Observability Validation

Date: 2026-05-16

## Scope

Added offline validation and documentation for the production reranker fallback
policy. This preserves EVI-129 semantics: production must not silently use the
deterministic fake reranker unless `RAGRIG_ALLOW_FAKE_RERANKER=true` is set.

## Evidence

Primary command:

```bash
make reranker-policy-smoke
```

Expected artifact:

```text
docs/operations/artifacts/reranker-policy-smoke.json
```

The smoke covers:

- `APP_ENV=production` with no explicit fake allowance reports fake fallback
  blocked.
- local development allows deterministic fake fallback.
- `APP_ENV=test` with `RAGRIG_ALLOW_FAKE_RERANKER=true` reports explicit
  override.
- an injected real BGE reranker provider contract scores documents and is not
  reported degraded.

Focused test command:

```bash
uv run pytest tests/test_reranker_policy_smoke.py -q
```

Lint command:

```bash
uv run ruff check scripts/reranker_policy_smoke.py tests/test_reranker_policy_smoke.py
```

## Operator Notes

`/health.reranker` reports fake fallback policy. In production,
`reranker.status=blocked` is expected when fake fallback is disabled; it does not
mean the app is unhealthy and it does not prove whether a real reranker is
reachable. Use the policy smoke, BGE smoke, or an explicit retrieval smoke for
provider availability.

The smoke artifact redacts secret-like keys before output.
