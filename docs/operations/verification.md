# Verification commands

Day-to-day checks contributors and CI run. The README only lists `make test`
and `make lint`; everything below is for deeper validation.

## Default suite

```bash
make format
make lint
make test
make coverage
make web-check
make local-pilot-smoke
make dependency-inventory
```

These run in CI on every PR. `make web-check` covers the FastAPI Web Console
contract; `make local-pilot-smoke` runs the API-level Local Pilot smoke.

## Smoke Test Catalog

| Command | Run when | Dependencies | Typical duration | Artifact |
| --- | --- | --- | --- | --- |
| `make web-check` | Frontend serving, root routing, or console contract changes | `uv`, built-in test fixtures | < 1 min | pytest output |
| `make local-pilot-preflight` | Local setup docs or preflight logic changes | `uv` | < 1 min | `docs/operations/artifacts/local-pilot-preflight.json` |
| `make pilot-docker-preflight` | Docker quickstart or Compose changes | `uv`, Docker | < 1 min | `docs/operations/artifacts/pilot-docker-preflight.json` |
| `make local-pilot-smoke` | Ingestion, indexing, retrieval, or answer path changes | `uv`, local SQLite/test fixtures | 1-3 min | `docs/operations/artifacts/local-pilot-smoke.json` |
| `make pilot-docker-smoke` | Running app container or Compose behavior changes | Running `pilot-up` stack | < 1 min | `docs/operations/artifacts/pilot-docker-smoke.json` |
| `make vercel-preview-smoke` | Vercel/Supabase deployment changes | `VERCEL_PREVIEW_URL` | < 1 min | `docs/operations/artifacts/vercel-preview-smoke.json` |
| `make pipeline-dag-smoke` | Task DAG, retry, or pipeline orchestration changes | `uv` | < 1 min | `docs/operations/artifacts/pipeline-dag-smoke.json` |
| `make answer-live-smoke` | Local LLM answer integration changes | Optional local LLM/OpenAI-compatible endpoint | varies | `docs/operations/artifacts/answer-live-smoke.json` |
| `make reranker-policy-smoke` | Reranker fallback or production policy changes | `uv` | < 1 min | `docs/operations/artifacts/reranker-policy-smoke.json` |
| `make bge-rerank-smoke` | BGE reranker integration changes | Optional `local-ml` extras | varies | stdout |
| `make advanced-parser-corpus-check` | Parser quality or fixture changes | `uv`, advanced document fixtures | 1-3 min | `docs/operations/artifacts/advanced-parser-corpus.*` |
| `make database-source-check` | Database source connector changes | `uv`, fixture DB setup | < 1 min | `docs/operations/artifacts/database-source-check.json` |
| `make cost-latency-check` | Provider cost/latency accounting changes | `uv` | < 1 min | `docs/operations/artifacts/cost-latency-check.json` |
| `make knowledge-map-check` | Understanding or knowledge-map changes | `uv` | < 1 min | `docs/operations/artifacts/knowledge-map-check.json` |
| `make ops-deploy-smoke` | Operations deploy command changes | `uv` | < 1 min | `docs/operations/artifacts/ops-deploy-summary.json` |
| `make ops-backup-smoke` | Backup behavior changes | `uv`, local backup dir | < 1 min | `docs/operations/artifacts/ops-backup-summary.json` |
| `make ops-restore-smoke` | Restore behavior changes | `uv`, local backup dir | < 1 min | `docs/operations/artifacts/ops-restore-summary.json` |
| `make nightly-evidence-smoke` | Release readiness or nightly evidence validation | Docker-backed smoke availability | varies | command summary |

## Nightly evidence pack

```bash
make nightly-evidence-smoke
```

Automated in GitHub Actions; can be run locally when Docker-backed live
smoke is available.

## Browser-level Local Pilot Console check

```bash
make local-pilot-console-e2e
```

Starts an ephemeral SQLite-backed app, verifies a failed upload/retry path,
uploads Markdown/PDF/DOCX through the Web Console, checks pipeline/chunk UI,
and asks one grounded Playground question. Requires `npm` and a local
Chrome/Chromium browser; set
`RAGRIG_CONSOLE_E2E_BROWSER_CHANNEL=chromium` if Chrome is not available.

## Supply-chain checks

```bash
make licenses
make sbom
make audit
```

`make audit` needs network access to vulnerability services. Offline
environments should run `make audit-dry-run` and record the missing live
audit as a release blocker.

## Vercel Preview deployment smoke

```bash
VERCEL_PREVIEW_URL='https://your-preview-url.vercel.app' make vercel-preview-smoke
```

See [EVI-130](../specs/EVI-130-vercel-preview-supabase.md) for the full
contract and Supabase migration boundary.

## Optional live-provider smokes

Off by default — they need real credentials and incur cost. See
[optional-services.md](./optional-services.md) for env-var wiring of S3 /
MinIO, Qdrant, fileshare, and the answer live smoke against a local LLM.
