# Understanding Runs Export Contract v1.0

## Overview

This document defines the stable export contract and shareable filter view for Understanding Runs in RAGRig.

## Export JSON Schema

### Single Run Export

`GET /understanding-runs/{run_id}/export`

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-05-09T12:00:00+00:00",
  "filter": {},
  "run_count": 1,
  "run_ids": ["uuid-of-run"],
  "id": "uuid-of-run",
  "knowledge_base_id": "uuid-of-kb",
  "knowledge_base": "kb-name",
  "provider": "deterministic-local",
  "model": "",
  "profile_id": "*.understand.default",
  "trigger_source": "api",
  "operator": "user-id",
  "status": "success",
  "total": 10,
  "created": 8,
  "skipped": 2,
  "failed": 0,
  "error_summary": null,
  "started_at": "2026-05-09T12:00:00+00:00",
  "finished_at": "2026-05-09T12:00:05+00:00"
}
```

### Filtered List Export

`GET /knowledge-bases/{kb_id}/understanding-runs/export`

Top-level fields:

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | string | Always `"1.0"` |
| `generated_at` | string (ISO 8601) | Timestamp of export generation |
| `filter` | object | The filter criteria used for this export |
| `run_count` | integer | Number of runs in this export |
| `run_ids` | string[] | Ordered list of run IDs in this export |
| `knowledge_base` | string \| null | KB name |
| `knowledge_base_id` | string | KB UUID |
| `runs` | object[] | Array of run objects (sanitized) |

Filter object fields (all nullable):

| Field | Type | Description |
|-------|------|-------------|
| `provider` | string \| null | Filter by provider name |
| `model` | string \| null | Filter by model name |
| `profile_id` | string \| null | Filter by profile ID |
| `status` | string \| null | Filter by run status |
| `started_after` | string \| null | ISO 8601 lower bound |
| `started_before` | string \| null | ISO 8601 upper bound |
| `limit` | integer \| null | Max results |

## Sanitization Rules

The export sanitizer redacts:

- **Sensitive keys**: `extracted_text`, `prompt`, `full_prompt`, `system_prompt`, `user_prompt`, `messages`, `raw_response` → `"[REDACTED]"`
- **Secret-like key/value pairs**: keys containing `api_key`, `access_key`, `secret`, `session_token`, `token`, `password`, `private_key`, `credential` with non-empty values → `"[REDACTED]"`

Applied recursively through nested objects and arrays.

## List Sort Order

Runs are sorted by `started_at DESC`, then `id DESC` for deterministic tie-breaking when multiple runs share the same timestamp.

## URL Query Parameters (Web Console)

The Web Console filter bar syncs its state to URL query parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `provider` | string | Provider filter |
| `model` | string | Model filter |
| `profile_id` | string | Profile filter |
| `status` | string | Status filter |
| `started_after` | string | ISO 8601 datetime-local |
| `started_before` | string | ISO 8601 datetime-local |
| `limit` | integer | Max results (5, 10, 20, 50) |

### Behavior

- Filter changes update the URL via `pushState` (no page reload).
- Page refresh preserves filter state from URL query.
- Browser back/forward (`popstate`) re-renders the filtered list.
- The "📋 Copy Link" button copies the current URL with all filter params to clipboard.

## Web Console Features

### Shareable URL

Every filter change writes to the URL query string. Users can copy the URL, share it, and the recipient sees the same filtered view.

### Export with Filter Summary

The export button downloads a JSON file. The export payload includes the `filter` object and `run_ids` array so external tools can verify completeness.

### Copy Link Button

A "📋 Copy Link" button in the filter bar copies the current URL (with all active filter parameters) to the system clipboard.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/understanding-runs?provider=&status=&limit=...` | Web Console list (filtered) |
| GET | `/understanding-runs/{run_id}` | Single run detail |
| GET | `/understanding-runs/{run_id}/export` | Single run export (JSON) |
| GET | `/knowledge-bases/{kb_id}/understanding-runs/export?provider=&status=...` | Filtered list export (JSON) |
| GET | `/knowledge-bases/{kb_id}/understanding-runs` | KB-scoped runs list |

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-05-09 | Initial release: export contract, URL query sync, deterministic sort, sanitization |
