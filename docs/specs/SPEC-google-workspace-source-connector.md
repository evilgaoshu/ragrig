# Google Workspace Source Connector SPEC

**Version**: 1.1.0  
**Last Updated**: 2026-05-13  
**Status**: Pilot

---

## 1. Overview

This SPEC defines the first enterprise collaboration source connector for ragrig: a Google Workspace (Drive + Docs) pilot. It validates configuration, discovery, incremental sync, desensitization (secret masking), and Console diagnostic loop.

This version inherits the EVI-107 pilot shipped in PR #99 and narrows three QA follow-ups from EVI-112: diagnostic status semantics, console exception redaction, and capability contract alignment.

---

## 2. Credential / Config Schema

### 2.1 GoogleWorkspaceSourceConfig

| Field | Type | Required | Description |
|---|---|---|---|
| `drive_id` | `string \| null` | No | Optional shared drive ID to scope discovery |
| `include_shared_drives` | `bool` | Yes | Whether to include shared drives |
| `include_patterns` | `string[]` | Yes | File glob patterns to include (default: `["*.pdf", "*.txt", "*.docx"]`) |
| `exclude_patterns` | `string[]` | Yes | File glob patterns to exclude |
| `page_size` | `int` | Yes | Pagination page size (1–1000, default: 100) |
| `max_retries` | `int` | Yes | Retry count for transient failures (default: 3) |
| `service_account_json` | `string` | Yes | `env:` reference to service account JSON key |

### 2.2 Secret Requirements

| Name | Required | Description |
|---|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Yes | Google service account JSON key content |

### 2.3 Minimal Scope

The connector uses Google Drive API readonly access. Live implementation requires:
- `https://www.googleapis.com/auth/drive.readonly`

---

## 3. Source Item Schema

### 3.1 GoogleDriveItem

| Field | Type | Description |
|---|---|---|
| `item_id` | `string` | Stable identity (Drive file ID or Docs document ID) |
| `name` | `string` | Human-readable name |
| `mime_type` | `string` | MIME type from Google Drive |
| `modified_at` | `datetime` | Modification timestamp (UTC) |
| `etag` | `string` | ETag or equivalent version marker |
| `version` | `string \| null` | Optional explicit version |
| `parent_path` | `string` | Logical parent path |
| `web_view_link` | `string \| null` | Link to open in Google Workspace |
| `size_bytes` | `int \| null` | File size (null for native Docs) |

---

## 4. Incremental Cursor

Discovery supports pagination via an opaque `cursor` string:
- `cursor == null` → first page
- `next_cursor` in response → subsequent page
- `next_cursor == null` → end of results

Dry-run fixture behavior:
- `cursor == "page1"` → returns second fixture
- `cursor == "page2"` → returns empty list
- `cursor == null` → returns both fixtures

---

## 5. File Type Mapping

| MIME Type | Logical Type |
|---|---|
| `application/pdf` | drive_file |
| `text/plain` | drive_file |
| `application/vnd.openxmlformats-officedocument.wordprocessingml.document` | drive_file |
| `application/vnd.google-apps.document` | docs_document (future) |
| Any other | drive_file (fallback) |

---

## 6. Failure / Retry Strategy

- **Missing credentials** → `SKIP` status with skip reason
- **Invalid credential format** → `DEGRADED` status with degraded reason
- **Invalid JSON in service account** → `DEGRADED` status with degraded reason
- **Dry-run** → no real API calls; stable fixture data returned
- Real API retry is out of scope for this pilot; `max_retries` field reserved for future use.

---

## 7. Secret Boundary

The following must never appear in Console output, JSON reports, or Markdown summaries:

- `client_secret`
- `refresh_token`
- `access_token`
- `service_account_json` raw values
- Any credential values of any kind

Masking rule:
- Strings longer than 8 chars: first 4 chars + `...` + last 4 chars
- Short strings: `***`
- Nested dicts: recursive sanitization
- Error messages: replace known secrets with `[REDACTED]`

Console-specific redaction rule:
- Any exception text containing `client_secret`, `refresh_token`, or `access_token` must be rewritten before rendering in plain-text console output as well as JSON output.

---

## 8. Connector State / Console Output

Console output must display:
- `connector_id`
- `status` (`healthy`, `degraded`, `skip`)
- `config_valid`
- `schema_version`
- `skip_reason` (when applicable)
- `degraded_reason` (when applicable)
- `last_discovery_at`
- `last_discovery` summary (total count, skipped count, next cursor, item list)
- `next_step_command`

Status semantics:
- `healthy`: config resolved and discovery summary is available
- `skip`: connector is not runnable because required credentials are absent in the environment
- `degraded`: config shape is invalid, service-account payload is invalid JSON, or any rendered connector error required sanitization

Permission mapping contract for this pilot:
- `PERMISSION_MAPPING` is not declared for `source.google_workspace` in v1.1 because the pilot does not emit ACL or sharing metadata yet.
- A later version may re-introduce the capability once runtime output includes a documented permission-mapping payload.

---

## 9. CI Behavior

When credentials are not present (default in CI):
- `_resolve_credential` returns error
- `scan_drive_items` returns empty discovered list
- `build_connector_state` returns `SKIP` status with reason
- All unit tests pass without real Google API calls
- No live network traffic required

When credentials are present but malformed:
- invalid JSON service-account payloads return `DEGRADED`
- invalid `service_account_json` config references return `DEGRADED`

---

## 10. Makefile Entry Points

Existing Makefile targets cover the new code:
- `make lint` — includes `src/ragrig/plugins/sources/google_workspace` via ruff
- `make test` — discovers `tests/test_google_workspace_source.py`
- `make coverage` — includes all source modules
- `make web-check` — runs `tests/test_web_console.py`

---

## 11. Out of Scope

- SharePoint / OneDrive implementation
- Organization-wide admin installation
- SaaS-hosted OAuth control plane
- CI connecting to real Google API by default
- Live OAuth token refresh
- Real-time webhook sync
- Google Sheets / Slides parsing
