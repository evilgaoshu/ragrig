# RAGRig Fileshare Source Plugin Spec

## Goal

Upgrade `source.fileshare` from an official stub to a real local-first source connector that can ingest enterprise files from SMB/CIFS, mounted NFS paths, WebDAV, and SFTP without making optional SDKs part of the default core runtime.

## Scope

This spec covers:

- plugin manifest readiness, protocol-specific dependency reporting, and secret declaration
- strict config validation for SMB, mounted NFS, WebDAV, and SFTP
- a transport-agnostic scanner that applies include/exclude filters, size limits, binary detection, cursor handoff, and delete-detection placeholders
- a fileshare ingestion connector that reuses the current document/document_version/pipeline_run persistence path
- fake-client-first offline tests plus an explicit offline smoke command

This spec does not implement:

- real ACL enforcement beyond metadata placeholders
- network-required live smoke in default CI
- Office/PDF parsing beyond existing text/markdown behavior and skip/failure recording
- a native NFS SDK path; NFS stays mounted-path-first

## Module Boundary

Runtime code lives under `src/ragrig/plugins/sources/fileshare/`:

- `config.py`: strict schema and protocol-specific validation
- `errors.py`: typed fileshare errors with secret-safe sanitization
- `client.py`: fake client, mounted-path client, and runtime client boundary
- `scanner.py`: transport-agnostic listing/filtering/delete placeholder logic
- `connector.py`: ingestion orchestration and DB persistence

Optional SDKs remain lazy runtime dependencies:

- SMB: `smbprotocol`
- SFTP: `paramiko`
- WebDAV: `httpx`

Mounted NFS/local path mode requires no optional dependency.

## Manifest And Readiness

`source.fileshare` is an official source plugin.

- READY capabilities: `READ`, `INCREMENTAL_SYNC`, `DELETE_DETECTION`, `PERMISSION_MAPPING`
- Protocols: `nfs_mounted`, `smb`, `webdav`, `sftp`
- If only mounted-path mode is available, the manifest reports `degraded`
- If all remote protocol SDKs are installed, the manifest reports `ready`
- `/plugins` and `make plugins-check` expose supported protocols, protocol-level statuses, missing dependencies, and declared secret requirements

The manifest docs reference for `source.fileshare` points to this spec.

## Config Schema

`source.fileshare` accepts these fields:

- `protocol`
- `host`
- `port`
- `share`
- `base_url`
- `root_path`
- `username`
- `password`
- `private_key`
- `include_patterns`
- `exclude_patterns`
- `max_file_size_mb`
- `page_size`
- `max_retries`
- `connect_timeout_seconds`
- `read_timeout_seconds`
- `cursor`
- `known_document_uris`

Unknown fields are rejected.

Protocol rules:

- mounted NFS requires only `root_path`
- SMB requires `host`, `share`, and usually username/password
- WebDAV requires `base_url`
- SFTP requires `host` and either password or private-key auth

## Secret Handling

Secrets enter the connector only through declared refs:

- `env:FILESHARE_USERNAME`
- `env:FILESHARE_PASSWORD`
- `env:FILESHARE_PRIVATE_KEY`

The connector must not:

- read undeclared env vars
- persist resolved secret values into source config, pipeline snapshots, documents, or run items
- surface resolved secrets in persisted errors

## Scan And Read Behavior

Listing applies:

- include/exclude glob filtering
- file-size limits
- binary detection from sample bytes
- cursor handoff through modified timestamps
- delete-detection placeholder comparison through `known_document_uris`

Skip reasons in this phase:

- `excluded`
- `unsupported_extension`
- `file_too_large`
- `binary_file`
- `unchanged`
- `deleted_upstream`

`deleted_upstream` is a placeholder signal only. It records audit state but does not yet delete documents or versions.

## Persistence Boundary

Source URI examples:

- `smb://host/share/root`
- `sftp://host/share/root`
- `webdav://host/root`
- `nfs://mounted/root`

Document URIs are stable per file under the source URI.

Persisted metadata includes:

- protocol
- remote path
- source URI
- modified timestamp
- size
- content type
- source snapshot
- parser metadata on success
- skip/failure reason where applicable
- permission mapping placeholder with `owner`, `group`, `permissions`, and `enforcement = not_implemented`

## Error Handling

- config or credential failures may fail the full run
- retryable read failures retry up to `max_retries`
- permanent single-file failures record failed run items and continue
- secret-safe sanitization applies before run or item errors are persisted

## Mounted NFS Mode

NFS support is mounted-path-first.

- operators mount NFS through the OS
- `source.fileshare` with `protocol = nfs_mounted` scans the mounted tree
- dry-run and offline smoke must work without network or a real NFS server

## Test Strategy

Default tests use fake clients and local fixtures only.

Coverage includes:

- config validation and declared secret refs
- readiness and discovery output
- scanner filtering and delete placeholders
- ingestion success/skip/failure behavior
- mounted-path dry-run
- offline smoke payload generation

## Smoke Path

Offline smoke uses:

- `make fileshare-check`

This command validates mounted-path fixture input plus fake SMB/WebDAV/SFTP scanner behavior. Any future live smoke must be explicit and opt-in.
