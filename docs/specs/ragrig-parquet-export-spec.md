# RAGRig Object Storage Sink Parquet Export Spec

## Summary

Extend `sink.object_storage` so it can export governed artifacts as Parquet in addition to the existing JSONL and Markdown outputs. The Parquet path is optional, uses `pyarrow` as an optional dependency, and must not affect core imports or the existing JSONL/Markdown flow when `pyarrow` is absent.

## Scope

- Add `pyarrow` as a `parquet` optional dependency group.
- Add `parquet_export: bool = False` to `ObjectStorageSinkConfig`.
- Emit `.parquet` artifacts for `chunks`, `documents`, `document_versions`, and `retrieval_status` when `parquet_export=True`.
- Encode Parquet payloads from `list[dict]` rows using `pyarrow`.
- Keep typed, minimal schemas for each Parquet artifact and flatten nested JSON payloads into JSON strings.
- Report missing `pyarrow` as degraded plugin readiness, matching the existing contract-first behavior for optional runtimes.

## Non-Goals

- No partitioning, registry, or data lake management features.
- No compression tuning or storage layout optimization.
- No live cloud integration beyond the existing fake-client and contract tests.

## Artifact Schemas

### `chunks.parquet`

- `chunk_id: string`
- `document_version_id: string`
- `document_uri: string`
- `chunk_index: int64`
- `text: string`
- `char_start: int64`
- `char_end: int64`
- `page_number: int64`
- `heading: string`
- `metadata: string` (`metadata_json` serialized to stable JSON)

### `document_versions.parquet`

- `document_version_id: string`
- `document_id: string`
- `version_number: int64`
- `content_hash: string`
- `parser_name: string`
- `parser_config: string` (stable JSON)
- `metadata: string` (stable JSON)
- `document_uri: string`
- `source_uri: string`

### `documents.parquet`

- `document_id: string`
- `knowledge_base_id: string`
- `source_id: string`
- `document_uri: string`
- `content_hash: string`
- `mime_type: string`
- `metadata: string` (stable JSON)

### `retrieval_status.parquet`

- `status: string`
- `reason: string`

When retrieval export has no rows beyond schema metadata, the artifact must still be emitted as schema-only Parquet.

## Dependency and Readiness Behavior

- `sink.object_storage` continues to advertise a degraded runtime manifest.
- Missing `boto3`, missing `pyarrow`, or both together remain discovery-time missing dependencies for this plugin.
- Core imports and plugin listing must not import `pyarrow` at module import time.
- JSONL and Markdown export continue to work when `pyarrow` is not installed and `parquet_export=False`.
- `parquet_export=True` without `pyarrow` raises a sink configuration/runtime error before any remote object storage call.

## Test Requirements

- Fake client coverage for Parquet writes, metadata, content type, overwrite/idempotency.
- Coverage for missing `pyarrow` degradation and JSONL fallback.
- No network or cloud account dependencies in default test runs.
- `make format`, `make lint`, `make test`, and `make coverage` must pass.
