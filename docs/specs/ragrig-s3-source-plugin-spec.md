# RAGRig S3 Source Plugin Spec

## Goal

Upgrade `source.s3` from an official stub to a real S3-compatible source connector that can scan, download, parse, and persist Markdown/Text objects from AWS S3 and compatible services such as MinIO, R2, Ceph RGW, and Wasabi.

## Scope

This spec covers:

- plugin manifest readiness and dependency reporting
- config validation and declared secret refs
- S3-compatible object listing, pagination, filtering, and download
- parser handoff into the existing source/document/document_version/pipeline_run boundary
- incremental skip based on object metadata snapshots
- fake-client-first tests with no default network dependency

This spec does not implement:

- delete detection or tombstones
- cursor-state persistence beyond the object snapshot stored in metadata
- permission mapping
- advanced retry backoff tuning or rate-limit governance
- binary/PDF/DOCX parsing beyond skip-and-record behavior

## Module Boundary

Runtime code lives under `src/ragrig/plugins/sources/s3/`:

- `config.py`: strict config schema with `extra="forbid"`
- `client.py`: fake client, protocol, and lazy `boto3` runtime adapter
- `scanner.py`: paginated object listing plus include/exclude filtering
- `connector.py`: orchestration into the existing ingestion and repository layer
- `errors.py`: typed S3 errors plus secret-safe message sanitization

`boto3` and `botocore` remain lazy imports inside the runtime adapter. They must not enter the default core import path.

## Manifest And Readiness

`source.s3` is an official source plugin.

- READY capabilities: `READ`, `INCREMENTAL_SYNC`
- Not exposed in READY: `DELETE_DETECTION`
- Optional dependency: `boto3`
- If `boto3` is missing, `/plugins` and `make plugins-check` must show `source.s3` as unavailable with missing dependency details
- If `boto3` is installed, the manifest can report `source.s3` as ready even though runtime secrets may still be missing for a particular execution

The manifest docs reference for `source.s3` points to this spec.

## Config Schema

`source.s3` accepts these fields:

- `bucket`
- `prefix`
- `endpoint_url`
- `region`
- `use_path_style`
- `verify_tls`
- `access_key`
- `secret_key`
- optional `session_token`
- `include_patterns`
- `exclude_patterns`
- `max_object_size_mb`
- `page_size`
- `max_retries`
- `connect_timeout_seconds`
- `read_timeout_seconds`

Unknown fields are rejected.

## Secret Handling

Secrets enter the connector only through declared manifest refs:

- `env:AWS_ACCESS_KEY_ID`
- `env:AWS_SECRET_ACCESS_KEY`
- optional `env:AWS_SESSION_TOKEN`

The connector must not:

- read undeclared environment variables
- persist resolved secret values into DB rows
- include resolved secret values in logs, error messages, or pipeline metadata

## Listing And Download Behavior

Object listing uses `list_objects_v2` semantics with:

- `bucket`
- `prefix`
- pagination via continuation tokens and `page_size`
- `fnmatch` include and exclude filters

Object metadata captured for eligible objects:

- `key`
- `etag`
- `last_modified`
- `size`
- `content_type`

Download behavior for this phase:

- download the full object to a temporary file
- run the existing Markdown/Text parser selection path
- clean up the temporary file after parse

Skip behavior:

- unsupported extension: `unsupported_extension`
- binary content: `binary_file`
- oversized object: `object_too_large`

Skipped objects must record a pipeline run item instead of crashing the whole run.

## Persistence Boundary

Source URI:

- `s3://{bucket}` when `prefix` is empty
- `s3://{bucket}/{prefix}` when `prefix` is configured

Document URI:

- `s3://{bucket}/{key}`

Persisted metadata retains:

- object key
- etag
- last modified timestamp
- size
- content type
- parser metadata when parse succeeds
- skip reason or failure reason when applicable
- `object_snapshot = etag:last_modified:size`

Document versions are created only when the object snapshot changes.

## Error Handling

- config or credential errors may fail the full run
- retryable single-object download errors retry up to `max_retries`
- permanent single-object failures create failed pipeline run items and continue
- secret-safe sanitization applies before any error reaches persisted run state

## Test Strategy

Default tests use only fake or stub clients.

Coverage includes:

- config validation
- declared secret refs
- missing dependency readiness
- list and pagination
- download and parser handoff
- unchanged object skip
- unsupported object skip
- oversized object skip
- retryable failure
- permanent failure
- credential/config failure
- DB persistence

## Local Smoke Path

Best-effort local smoke uses:

- `docker compose --profile minio up -d minio`
- `make s3-check`

The smoke path is explicit and opt-in. It is not part of the default `make test` or `make coverage` contract.

## Follow-Up Work

- delete detection and tombstones
- richer parser support for binary office formats and PDFs
- cursor-state persistence separate from document metadata
- rate-limit governance and retry strategy tuning
- richer Web Console config and execution UX for remote sources
