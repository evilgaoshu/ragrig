# SPEC — Understanding Export Offline Verification & Audit Summary

**Version**: 1.0  
**Issue**: [EVI-80](mention://issue/9cc64c04-f4e2-4ba7-a191-bd81ee952c3a)  
**Status**: Implemented

---

## 1. Goal

Provide a local, offline command that reads Understanding Runs export JSON files, validates structural integrity, checks sanitization boundaries, and emits a concise audit summary.  No network, no LLM, no schema changes.

---

## 2. Verification Command

```bash
make verify-understanding-export
```

Runs `uv run python -m scripts.verify_understanding_export` against the built-in fixture by default.

### CLI

```bash
# Single file
uv run python -m scripts.verify_understanding_export path/to/export.json

# Batch (best-effort)
uv run python -m scripts.verify_understanding_export a.json b.json c.json

# JSON artifact output (best-effort)
uv run python -m scripts.verify_understanding_export --json --output summary.json a.json b.json
```

---

## 3. Validation Rules

### 3.1 Required Fields

**Top-level**
- `schema_version`
- `generated_at`
- `filter`
- `run_count`
- `run_ids`
- `knowledge_base`
- `knowledge_base_id`
- `runs`

**Per-run**
- `id`, `knowledge_base_id`, `provider`, `model`, `profile_id`
- `trigger_source`, `operator`, `status`
- `total`, `created`, `skipped`, `failed`
- `error_summary`, `started_at`, `finished_at`

**Filter object**
- `provider`, `model`, `profile_id`, `status`
- `started_after`, `started_before`, `limit`

### 3.2 Schema Version

Must be exactly `"1.0"`.

### 3.3 Count Consistency

- `len(run_ids) == run_count`
- `len(runs) == run_count`

### 3.4 Sanitization Boundary

Forbidden keys (redacted if present):
- `extracted_text`, `prompt`, `full_prompt`, `system_prompt`, `user_prompt`
- `messages`, `raw_response`

Secret-like patterns (in key or value):
- `api_key`, `access_key`, `secret_key`, `session_token`
- `password`, `private_key`, `credential`
- `sk-` (OpenAI-style prefix)

Presence of any forbidden key or secret-like value causes verification to **fail**.

---

## 4. Output Summary

On success, the command prints (or JSON-ifies):

| Field | Description |
|-------|-------------|
| `schema_version` | Export schema version (e.g. `"1.0"`) |
| `run_count` | Number of runs exported |
| `filter_keys` | List of filter object keys |
| `sanitized_field_count` | Number of redacted/sanitized fields detected (must be 0) |

**Constraints**
- Never outputs full prompts, original extracted text, or secret values.
- On failure, outputs diagnostic paths (e.g. `$.runs[0].extracted_text`) but not the redacted content itself.

---

## 5. Test Coverage

File: `tests/test_understanding_export_verify.py` (31 cases, `pytest.mark.unit`)

| Scenario | Count |
|----------|-------|
| Valid fixture passes | 2 |
| Missing top-level / filter / run fields fail | 4 |
| `run_count` / `run_ids` / `runs` mismatch fail | 3 |
| Forbidden key leak (`extracted_text`, `prompt`) fail | 2 |
| Secret-like value leak (`api_key`, `sk-`, `password`) fail | 4 |
| Nested secret detection fail | 1 |
| Invalid / missing `schema_version` fail | 3 |
| File I/O errors (missing, bad JSON, non-object) | 3 |
| Summary formatting (pass, fail, error, no secrets in output) | 3 |
| Constants sanity | 3 |

---

## 6. Best-Effort Goals

- Batch validation of multiple export files in one invocation.
- `--json --output <path>` for CI artifact generation.

---

## 7. Out of Scope

- Cloud archival / upload
- BI / dashboards
- Running real LLM inference
- Changing the export v1 schema

---

## 8. Makefile Targets

```makefile
verify-understanding-export:
	$(UV) run python -m scripts.verify_understanding_export

verify-understanding-export-json:
	$(UV) run python -m scripts.verify_understanding_export \
		--json --output $(ARTIFACTS_DIR)/understanding-export-verify-summary.json
```

---

## 9. Changelog

| Version | Date | Change |
|---------|------|--------|
| 1.0 | 2026-05-11 | Initial implementation |
