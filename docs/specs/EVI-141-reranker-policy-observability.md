# EVI-141 — Reranker Policy Observability Guard

## Goal

Make the production reranker fallback policy easy to validate and hard to
misread. EVI-129 blocks the deterministic fake reranker in production unless an
operator explicitly opts in; EVI-141 adds a reproducible smoke check and an
operator-facing interpretation matrix for `/health`.

## Deployment Matrix

`/health.reranker` is a policy object for fake fallback. It is not a live model
probe and must not be treated as proof that a real reranker is reachable.

| APP_ENV | RAGRIG_ALLOW_FAKE_RERANKER | Real reranker available | Expected fake fallback policy | `/health` interpretation |
| --- | --- | --- | --- | --- |
| `production` or `prod` | unset or `false` | no | blocked | Healthy app can still report `reranker.status=blocked`; rerank requests without an explicit real provider must fail instead of silently using fake rerank. |
| `production` or `prod` | unset or `false` | yes | blocked | The fake fallback remains blocked. Explicit real-provider rerank paths may be healthy; do not interpret `blocked` as model degradation. |
| `production` or `prod` | `true` | no | explicit override | Fake fallback is deliberately allowed for demos or accepted degraded environments. This should be rare and visible. |
| `production` or `prod` | `true` | yes | explicit override | Real reranker can be used, but fake fallback is also allowed by operator choice. Review before promoting. |
| `test` | unset or `false` | no | non-production fallback | Fake fallback is allowed for deterministic tests. |
| `test` | `true` | no or yes | explicit override | Explicit fake allowance is visible and should be confined to test setup. |
| local development | unset or `false` | no | non-production fallback | Local/demo rerank can use deterministic fake fallback. |
| local development | `true` | no or yes | explicit override | Explicit fake allowance is visible; keep it out of production unless accepted. |

## Runtime Contract

- Production without `RAGRIG_ALLOW_FAKE_RERANKER=true` must not silently use the
  deterministic fake reranker.
- `/health.reranker.status=blocked` means fake fallback is blocked, not that the
  app health endpoint is degraded.
- Real reranker availability is validated by an explicit provider probe or
  retrieval smoke, not by the fake fallback policy alone.
- Command output and artifacts must not include secrets.

## Verification

Run the offline smoke:

```bash
make reranker-policy-smoke
```

The target writes `docs/operations/artifacts/reranker-policy-smoke.json` and
passes only when all checks pass:

- production fake fallback blocked
- local fallback allowed
- test explicit fake fallback allowed
- injected real BGE reranker provider contract scores documents and is not
  marked degraded

Focused tests:

```bash
uv run pytest tests/test_reranker_policy_smoke.py -q
```

The smoke uses an injected deterministic runtime for the BGE reranker provider
contract, so it requires no network, GPU, model download, API key, or local-ml
extras.
