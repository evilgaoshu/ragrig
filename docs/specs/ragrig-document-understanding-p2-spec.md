# RAGRig DocumentUnderstanding P2 Spec — Evaluation & Re-run Governance

Date: 2026-05-09
Status: Implemented
Parent: [EVI-58](mention://issue/88be5134-b8db-486a-aafd-318aae076619)

## 1. Goal

Extend DocumentUnderstanding from single-document generation (P1) to an
evaluable, re-runnable, governable capability: identify missing/stale/failed
results, batch-complete them, and surface structured quality signals in the Web
Console.

## 2. Scope

### In Scope (P2)

- **Batch understand endpoint** `POST /knowledge-bases/{kb_id}/understand-all`
  with `provider`/`model`/`profile_id` parameters. Processes all
  document_versions in a knowledge base:
  - missing (no understanding record) → generates new
  - fresh (input_hash matches, status=completed) → skips
  - stale (extracted_text or profile changed, input_hash mismatch) → regenerates
  - failed → regenerates
  - Returns structured batch result: `{ total, created, skipped, failed, errors }`
  - Partial failures do not block other versions.

- **Coverage endpoint** `GET /knowledge-bases/{kb_id}/understanding-coverage`:
  returns `{ total_versions, completed, missing, stale, failed,
  completeness_score, recent_errors }`. Staleness is defined by a mismatch
  between the stored `input_hash` and the current
  `hash(profile_id + provider + model + extracted_text)`.
  `completeness_score` = completed / total_versions.

- **Web Console Understanding Coverage panel**: shows missing/stale/failed/completed
  counts, completeness score, recent error summary, and a "Run All Understanding"
  button. No faked/mock states.

- **Traceability**: every result includes `document_version_id`, `profile_id`,
  provider, model, and `input_hash` in API responses.

- **Secrets safety**: API, logs, and console never expose provider secrets, full
  prompt text, or full source document text.

### Best-Effort

- `completeness_score` in the coverage endpoint.
- `--filter` parameter for selective re-run by provider/model/profile (not
  exposed as an API parameter in this iteration; modeled internally for future
  CLI use).

### Out of Scope

- Background queue / async workers.
- Cross-document knowledge graph.
- Cloud live smoke tests.
- Manual annotation platform.

## 3. API Contract

### POST /knowledge-bases/{kb_id}/understand-all

Request body:
```json
{
  "provider": "deterministic-local",
  "model": null,
  "profile_id": "*.understand.default"
}
```

Response (200):
```json
{
  "total": 3,
  "created": 2,
  "skipped": 1,
  "failed": 0,
  "errors": []
}
```

On partial failure:
```json
{
  "total": 3,
  "created": 1,
  "skipped": 1,
  "failed": 1,
  "errors": [
    { "version_id": "uuid", "error": "Provider 'x' is unavailable: ..." }
  ]
}
```

### GET /knowledge-bases/{kb_id}/understanding-coverage

Response (200):
```json
{
  "total_versions": 3,
  "completed": 1,
  "missing": 1,
  "stale": 0,
  "failed": 1,
  "completeness_score": 0.3333,
  "recent_errors": [
    {
      "document_version_id": "uuid",
      "profile_id": "*.understand.default",
      "provider": "deterministic-local",
      "error": "some error message"
    }
  ]
}
```

`recent_errors` returns up to 10 most recent failed understanding records,
ordered by most recent update time. Each entry includes the version/path/error
for triage but no content/prompt/secrets.

## 4. Web Console Behavior

The Documents section shows a new «Understanding Coverage» panel above the
document/chunk preview.

- **Coverage card**: knowledge base name, completeness score as a percentage,
  counts of completed/missing/stale/failed versions.
- **Recent error summary**: when `failed > 0`, a card listing the latest error
  messages (truncated for display). Each entry shows the affected
  `document_version_id` and the error text.
- **Run All Understanding button**: triggers `POST
  /knowledge-bases/{kb_id}/understand-all` with `deterministic-local` provider
  and default profile; refreshes both the coverage panel and the document
  preview after completion.

## 5. Idempotency and Re-process Logic

- Each batch run evaluates every version independently.
- `input_hash` comparison uses the same formula as P1:
  `SHA256(profile_id + provider + model + extracted_text)`.
- Fresh (hash match + completed status) records are never re-processed; this
  ensures repeated batch calls are idempotent.
- Stale and failed records are always re-processed regardless of provider.

## 6. Test Coverage (100%)

Unit tests (`tests/test_understanding.py`):

- `TestUnderstandAllVersions`: missing generation, fresh skip, stale
  regeneration, failed regeneration, partial provider failure, empty text
  version, repeat execution idempotency.
- `TestUnderstandingCoverage`: all-missing, mixed states (completed/stale/missing),
  failed-counted, completeness score.

Integration tests (`tests/test_web_console.py`):

- Batch endpoint creates and skips correctly (3 documents).
- Invalid provider records failures in batch errors list.
- Coverage endpoint returns correct counts before and after batch run.
- Console HTML includes coverage panel, Run All button, error summary.
- No secrets leaked in coverage or batch endpoint responses.
- Traceability: API responses include `input_hash`, `profile_id`, provider, model.

## 7. Verification Commands

```bash
make lint
make test      # 408 passed, 9 skipped
make coverage  # 100% line coverage
make web-check # 25 passed
```

## 8. Risk and Limitations

- Synchronous batch execution: KBs with many documents may cause long response
  times. This is explicitly out of scope (no async worker in P2).
- Real LLM providers are not exercised in CI; only the deterministic-local
  provider is tested automatically.
- `recent_errors` is capped at 10 entries to bound response size.
