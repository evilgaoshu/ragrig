# RAGRig S3 Source Plugin Spec

Issue: EVI-40
Date: 2026-05-05
Status: DEV implementation spec

## Scope

This document defines the minimum real `source.s3` implementation for RAGRig so S3-compatible object stores can feed the existing metadata, parsing, and pipeline-run model without changing the local-first default path.

Included in scope:

- A real `source.s3` official plugin manifest with effective readiness based on optional S3 SDK availability.
- Config validation for bucket, prefix, endpoint, region, addressing mode, TLS verification, declared secret refs, include/exclude patterns, object size, pagination, retries, and timeouts.
- Object listing with pagination, prefix filtering, fnmatch include/exclude filtering, object metadata extraction, and oversize skip handling.
- Tempfile-based object download followed by existing Markdown/Text parser handoff.
- Persistence through existing `sources`, `documents`, `document_versions`, `pipeline_runs`, and `pipeline_run_items` tables.
- Incremental skip based on stable S3 object snapshot metadata.
- Fake-client tests for default CI and optional local MinIO smoke entrypoints.

Explicitly out of scope:

- delete detection or tombstone workflows
- cursor tables or long-lived sync checkpoints outside document metadata
- streaming multipart ingest, resumable transfers, or parallel download scheduling
- live cloud-account tests as part of default `make test`
- object storage sink implementation
- IAM policy analysis, role assumption, KMS, or versioned-object governance

## Authority

This implementation is subordinate to:

- `docs/specs/ragrig-plugin-system-spec.md`
- `docs/specs/ragrig-phase-1b-local-ingestion-spec.md`
- `docs/specs/ragrig-local-first-quality-supply-chain-policy.md`

If this file conflicts with an authority document, the authority document wins.

## Technical Shape

- Plugin manifest: `src/ragrig/plugins/official.py`
- Source module: `src/ragrig/plugins/sources/s3/`
- Reused persistence boundary: `src/ragrig/repositories/`
- Reused parser boundary: `src/ragrig/parsers/`
- Plugin discovery surfaces: `GET /plugins`, `scripts/plugins_check.py`, `make plugins-check`
- Optional smoke entrypoints: Makefile target and MinIO docker compose profile

The module split under `src/ragrig/plugins/sources/s3/` is:

- `config.py`: validated config model, secret resolution, redaction helpers
- `client.py`: protocol, fake client, lazy boto3 client
- `scanner.py`: paginated listing and skip classification
- `connector.py`: scan, download, parse, persist orchestration
- `errors.py`: configuration, credential, retryable, and permanent failure types

`boto3` and `botocore` remain lazy imports inside the runtime client. Core import paths must stay usable without the optional S3 dependency installed.

## Readiness And Capability Rules

- `source.s3` is an official plugin.
- READY capabilities are limited to `read` and `incremental_sync`.
- `delete_detection` is explicitly not exposed while unimplemented.
- If `boto3` is not installed, discovery must report `status=unavailable` and list the missing dependency.
- If `boto3` is installed, manifest status may be `ready` while runtime credential or endpoint errors are still surfaced per run.

## Config Contract

Required config fields:

- `bucket`
- `access_key`
- `secret_key`

Optional config fields:

- `prefix`
- `endpoint_url`
- `region`
- `use_path_style`
- `verify_tls`
- `session_token`
- `include_patterns`
- `exclude_patterns`
- `max_object_size_mb`
- `page_size`
- `max_retries`
- `connect_timeout_seconds`
- `read_timeout_seconds`

Validation rules:

- unknown fields are forbidden
- bucket must be non-empty and must not include path separators
- prefix is normalized to a stable no-leading-slash, no-trailing-slash form
- endpoint URL must be `http://` or `https://` when provided
- secret-bearing fields must use `env:SECRET_NAME` refs
- only manifest-declared secret names are accepted
- pattern lists must not contain empty strings

Declared secret requirements:

- `AWS_ACCESS_KEY_ID` required
- `AWS_SECRET_ACCESS_KEY` required
- `AWS_SESSION_TOKEN` optional

The plugin must not read undeclared environment variables and must not persist resolved secret values into the database, logs, API payloads, or error messages.

## Scanner Rules

Listing behavior:

- use paginated S3 listing with configured `page_size`
- apply `prefix` server-side when available
- apply fnmatch include and exclude patterns against both full key and basename
- skip directory placeholder keys ending in `/`

Tracked object metadata:

- `key`
- `etag`
- `last_modified`
- `size`
- `content_type`

Skip reasons tracked at scan or ingest time:

- `excluded`
- `unsupported_extension`
- `object_too_large`
- `binary_file`
- `unchanged`

## Download And Parser Handoff

- Objects are downloaded into a temporary local file.
- The existing parser selector is reused, so `.md` and `.markdown` use the Markdown parser and other supported text inputs use the plain text parser.
- Unsupported extensions are skipped before download when possible.
- Binary content discovered after download is skipped and recorded without crashing the run.
- Temporary files are always cleaned up.

## Persistence Rules

- Source URI uses `s3://{bucket}/{prefix}` when prefix is non-empty, otherwise `s3://{bucket}`.
- Document URI uses `s3://{bucket}/{key}`.
- `sources.kind` must be `s3`.
- `sources.config_json` stores only validated config with secret refs preserved as `env:` references.
- `documents.metadata_json`, `document_versions.metadata_json`, and `pipeline_run_items.metadata_json` must retain object metadata and parser metadata.
- Skip and failure records may create durable document rows so pipeline run items can point at a stable object identity.

Minimum persisted metadata for successful items:

- `object_key`
- `etag`
- `last_modified`
- `size`
- `content_type`
- `s3_snapshot`
- `parser_metadata`

Minimum persisted metadata for skipped or failed items:

- base object metadata above
- `skip_reason` or `failure_reason`

## Incremental Rules

The unchanged snapshot is based on:

- `etag`
- `last_modified`
- `size`

If the stored snapshot exactly matches the current object snapshot, the connector records a skipped pipeline item with `skip_reason=unchanged` and does not create a new `document_versions` row.

If any part of the snapshot changes, the connector downloads the object again and writes the next sequential document version.

## Error Handling Rules

- Missing optional SDK dependency: fail fast with a clean dependency error.
- Config or secret resolution error: fail the whole run with a diagnostic that does not leak resolved secret values.
- Credential error: fail the whole run with a sanitized authentication diagnostic.
- Retryable per-object error: retry up to configured max retries, then record a failed item if retries are exhausted.
- Permanent per-object error: record a failed item and continue other objects.
- Unsupported, oversized, or binary objects: record skipped items and continue.

## Testing And Verification

Default test coverage must use only fake clients and sqlite-backed persistence.

Required test coverage:

- manifest readiness and secret requirements
- config validation and unknown-field rejection
- missing dependency guard
- pagination and filtering
- object download and parser handoff
- unchanged skip behavior
- oversized skip behavior
- unsupported or binary object skip behavior
- retryable and permanent per-object failure behavior
- config or credential failure behavior
- metadata persistence in `documents`, `document_versions`, and `pipeline_run_items`

Required repository verification commands:

- `make format`
- `make lint`
- `make test`
- `make coverage`
- `make plugins-check`

Best-effort local smoke validation:

- `docker compose --profile minio up -d minio`
- `make s3-check`

If the optional MinIO smoke path is unavailable in the current branch, the delivery comment must call that out explicitly as a blocker or deferred follow-up.

## Deferred Follow-Ups

- delete detection and tombstones
- durable cursor state beyond document metadata snapshots
- richer retry strategy and rate-limit shaping
- advanced document parsers for PDFs and Office formats
- web console configuration workflow for `source.s3`
