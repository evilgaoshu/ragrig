# SPEC: Answer Live Smoke Diagnostics Console Badge & CI Artifact

> Version: 1.0
> Corresponding Issue: EVI-97

## Goal

Make `answer-live-smoke` JSON diagnostic results visible in the Web Console
and as a versioned CI artifact, so reviewers can quickly determine provider
availability, skip/degraded reasons, and redacted boundaries.

## Artifact Schema

The generated artifact is written to
`docs/operations/artifacts/answer-live-smoke.json` with the following schema:

```json
{
  "artifact": "answer-live-smoke",
  "schema_version": "1.0",
  "provider": "ollama",
  "model": "llama3.2:1b",
  "base_url_redacted": "http://localhost:11434/v1",
  "status": "healthy",
  "reason": "Provider healthy. Chat smoke completed; response length=42 chars.",
  "citation_count": 2,
  "timing_ms": 1234.56,
  "generated_at": "2026-05-12T00:00:00+00:00",
  "report_path": "docs/operations/artifacts/answer-live-smoke.json"
}
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `artifact` | string | Fixed: `answer-live-smoke` |
| `schema_version` | string | Schema version (currently `1.0`) |
| `provider` | string | Provider name (e.g. `ollama`, `lm_studio`) |
| `model` | string | Model name (e.g. `llama3.2:1b`) |
| `base_url_redacted` | string | Redacted base URL (no API keys, tokens, passwords) |
| `status` | string | `healthy` / `degraded` / `skip` / `error` |
| `reason` | string | Human-readable status description |
| `citation_count` | int | Number of citation IDs in smoke chat response |
| `timing_ms` | float | Total elapsed time in milliseconds |
| `generated_at` | string | ISO 8601 UTC timestamp |
| `report_path` | string | Relative path to the artifact file |

## Status Mapping (Console)

The Web Console maps artifact `status` to a display status:

| Artifact Status | Console Status | Pill Class | Description |
|----------------|---------------|------------|-------------|
| `healthy` | `healthy` | `pill good` (green) | Provider reachable, citations found |
| `degraded` | `degraded` | `pill warn` (amber) | Reachable but no citations |
| `skip` | `skip` | `pill warn` (amber) | Missing optional dependency |
| `error` | `error` | `pill error` (red) | Provider unreachable or failure |

## Staleness Detection

- Artifacts older than 24 hours are flagged as `is_stale: true`
- A stale artifact that was `healthy` is displayed as `degraded` in the console
- Missing or corrupt artifacts show as `failure` — never as healthy

## Missing / Corrupt / Stale Behavior

| Scenario | Console `available` | Console `status` | Console `reason` |
|----------|--------------------|-------------------|------------------|
| Artifact does not exist | `false` | `failure` | `artifact not found or corrupt` |
| Corrupt JSON (parse error) | `false` | `failure` | `artifact not found or corrupt` |
| Wrong artifact type | `false` | `failure` | `artifact not found or corrupt` |
| Stale (>24h) | `true` | `degraded` (was healthy) | Original reason + stale flag |
| Fresh healthy | `true` | `healthy` | Original reason |

## Secret Boundary

All console output must pass through `_redact_console_output()` and
`_assert_console_no_secrets()` to catch:

- Secret-like keys: `api_key`, `access_key`, `secret`, `password`, `token`,
  `credential`, `private_key`, `dsn`, `service_account`, `session_token`
- Forbidden fragments: `sk-live-`, `sk-proj-`, `sk-ant-`, `ghp_`,
  `Bearer `, `PRIVATE KEY-----`

The artifact itself uses `_redact_secrets()` to redact the same key patterns.

## Console Fields

The Web Console endpoint `GET /answer/live-smoke` returns these fields:

| Field | Type | Description |
|-------|------|-------------|
| `available` | bool | Whether a valid artifact exists |
| `status` | string | Normalized status (`healthy`/`degraded`/`skip`/`error`/`failure`) |
| `display_status` | string | Status displayed in badge (same as `status`) |
| `is_stale` | bool | True when artifact is >24h old |
| `provider` | string | Provider name from artifact |
| `model` | string | Model name from artifact |
| `base_url_redacted` | string | Redacted base URL |
| `reason` | string | Human-readable status reason |
| `citation_count` | int | Citation count from artifact |
| `timing_ms` | float | Timing in ms |
| `generated_at` | string | ISO timestamp from artifact |
| `report_path` | string | Relative path to artifact file |
| `artifact_path` | string | Same as report_path |
| `schema_version` | string | Schema version |

## Refresh / Missing Strategy

- Console polls `GET /answer/live-smoke` on page load
- No auto-refresh; operator refreshes the page to see latest
- The status strip always degrades gracefully when no artifact exists

## CI Behavior

- `make answer-live-smoke` writes the artifact without requiring network,
  real LLM, cloud secrets, or local Ollama
- When `openai` is missing, the script outputs status `skip` with the
  install command — never crashes
- Default CI (`make test` / `make coverage`) does not depend on
  `answer-live-smoke` artifacts

## Make Target

```makefile
answer-live-smoke:
    uv run python -m scripts.answer_live_smoke --pretty --output docs/operations/artifacts/answer-live-smoke.json
```

## Endpoint

```
GET /answer/live-smoke
```

Returns the console-safe summary of the latest diagnostics artifact.

## Out of Scope

- No cloud-required smoke checks
- No real LLM judge / multi-turn dialogue
- No production monitoring integration
- No raw secret exposure (handled by redaction layers)
