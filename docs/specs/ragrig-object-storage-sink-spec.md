# RAGRig Object Storage Sink Spec

## Goal

Define the first official `sink.object_storage` runtime for exporting governed RAGRig assets to S3-compatible object storage without requiring network access, cloud credentials, or optional SDKs in the default test path.

## Scope

- Support S3-compatible object storage through optional `boto3`.
- Export a minimum artifact set as JSONL and Markdown.
- Preserve traceability back to knowledge base, document version, chunk, and pipeline run metadata.
- Expose truthful plugin readiness through the registry, `/plugins`, and the web console.
- Provide an opt-in CLI smoke command with dry-run support.

## Supported Runtime Surface

Implemented in this phase:

- AWS S3
- Cloudflare R2
- MinIO
- Ceph RGW
- Wasabi
- Backblaze B2 S3 API
- Tencent COS S3 API
- Alibaba OSS in S3-compatible mode

Contract-only, not runtime-ready in this phase:

- Google Cloud Storage
- Azure Blob Storage

Because of that split, `sink.object_storage` reports `degraded` when `boto3` is installed and `unavailable` when it is missing.

## Config Contract

`sink.object_storage` reuses the shared S3-compatible connection surface:

- `bucket`
- `prefix`
- `endpoint_url`
- `region`
- `use_path_style`
- `verify_tls`
- `access_key`
- `secret_key`
- `session_token`
- `max_retries`
- `connect_timeout_seconds`
- `read_timeout_seconds`

Sink-only fields:

- `path_template`
- `overwrite`
- `dry_run`
- `include_retrieval_artifact`
- `include_markdown_summary`
- `object_metadata`

Secrets must use explicit `env:` references and are limited to declared requirements.

## Exported Artifacts

Minimum artifact set in this phase:

- `knowledge_base_manifest.jsonl`
- `documents.jsonl`
- `document_versions.jsonl`
- `chunks.jsonl`
- `pipeline_runs.jsonl`
- `export_summary.md`

The manifest explicitly marks retrieval and evaluation exports as unsupported until a dedicated runtime path exists.

## Idempotency and Overwrite

- Export paths are generated from `path_template`.
- Existing objects are skipped by default when `overwrite=false`.
- Existing objects are replaced when `overwrite=true`.
- `dry_run=true` computes the artifact plan without uploading objects.

## Content Type and Metadata

- JSONL artifacts use `application/x-ndjson`.
- Markdown summaries use `text/markdown; charset=utf-8`.
- Object metadata includes artifact name, knowledge base, run id, content hash, and caller-supplied metadata.

## Testing Requirements

- Fake-client contract tests cover write success, dry-run, overwrite/idempotency, missing credentials, bucket access failure, retryable write failure, and metadata/content type handling.
- Default tests remain offline and secret-free.
- Optional SDKs remain outside top-level core imports.

## Operator Smoke Command

Use:

- `make export-object-storage-check`

This command is opt-in, reads credentials from declared environment variables, and defaults to `dry_run` unless explicitly disabled.
