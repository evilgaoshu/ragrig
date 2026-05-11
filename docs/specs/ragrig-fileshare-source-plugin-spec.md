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

Tests are organized in three tiers:

1. **Fake/offline tests** (default `make test` / `make coverage`)
   - No network, no secrets, no optional dependencies required.
   - Uses `FakeFileshareClient` and local fixtures.
   - Covers config validation, scanner filtering, ingestion behavior, mounted-path dry-run, and offline smoke payload generation.

2. **Local live smoke** (explicit opt-in)
   - Requires optional SDKs (`uv pip install -e '.[fileshare]'`).
   - Spins up local Samba/WebDAV/SFTP containers via Docker Compose profile `fileshare-live`.
   - Validates real `list_files`, `read_file`, and `scan_files` against at least one protocol.
   - Gated by `RAGRIG_FILESHARE_LIVE_SMOKE=1`.
   - Not part of default CI.

3. **Enterprise shared盘 live** (out of scope for this repo)
   - Requires real credentials and network access.
   - Operators validate independently using the same connector contract.

## Smoke Path

Offline smoke uses:

- `make fileshare-check`

This command validates mounted-path fixture input plus fake SMB/WebDAV/SFTP scanner behavior.

Live smoke uses:

- `make fileshare-live-up` — start local test services
- `make test-live-fileshare` — run live smoke tests
- `make fileshare-live-down` — tear down services

Required environment / secrets for live smoke:

| Protocol | Required env / config |
|----------|----------------------|
| SMB      | `SMB_HOST_PORT` (default 1445), username `testuser`, password `testpass` |
| WebDAV   | `WEBDAV_HOST_PORT` (default 8080), username `testuser`, password `testpass` |
| SFTP     | `SFTP_HOST_PORT` (default 2222), username `testuser`, password `testpass` |

Live smoke records:

- list/read/stat for each supported protocol
- scanner filter behavior (include/exclude, size limits, unsupported extensions)
- graceful skip when optional SDK is missing

## Live Smoke Preflight and Evidence

This section defines the preflight checks and evidence output added to the live smoke path.

### Preflight Checks (`scripts/preflight_fileshare_live.py`)

Before starting containers, the preflight script verifies:

1. **Docker CLI** — `docker --version` must succeed.
2. **Docker Compose** — `docker compose version` must succeed (Compose v2).
3. **Docker daemon** — `docker info` must succeed and show a running daemon.
4. **Ports** — `127.0.0.1` ports `SMB_HOST_PORT` (default `1445`), `WEBDAV_HOST_PORT` (default `8080`), and `SFTP_HOST_PORT` (default `2222`) must be free. If a port is occupied, the blocker message includes the port number, env var name, and three fix options:
   - free the port,
   - override via environment variables,
   - or enable `FILESHARE_AUTO_PICK_PORTS=1` to let preflight find free alternatives.
5. **Optional SDKs** — `smbprotocol`, `paramiko`, and `httpx` import checks. Missing SDKs produce a warning with the exact install command (`uv sync --extra fileshare --dev`) and a fallback note that pytest will skip the protocol.

Failure behavior:

- If any hard blocker (Docker missing, daemon down, port conflict) is found, the script exits `1` and prints an actionable, numbered list of blockers to `stderr`. No containers are started.
- If only optional SDKs are missing, the script exits `0` with a warning; pytest skips the corresponding tests.
- `--json` outputs a structured result including `suggested_ports`, `target_ports`, and per-check details for programmatic consumption.

### Evidence Orchestration (`scripts/test_live_fileshare.py`)

The orchestration script runs the live smoke end-to-end and produces a timestamped evidence record:

1. **Preflight** — runs the preflight script; hard blockers stop before `compose up`.
2. **Compose up** — `docker compose --profile fileshare-live up -d --wait samba webdav sftp`.
3. **Seed fixtures** — copies `tests/fixtures/fileshare_live/` into each container.
4. **Pytest** — runs `tests/test_fileshare_live_smoke.py` with `RAGRIG_FILESHARE_LIVE_SMOKE=1`.
5. **Container logs** — tails the last N lines (default 100) from `samba`, `webdav`, and `sftp`.
6. **Teardown** — runs `docker compose --profile fileshare-live down --remove-orphans samba webdav sftp` (default true; disable with `--no-teardown`).

The evidence record is written to `docs/operations/artifacts/fileshare-live-smoke-record.json` by default and contains:

- `meta`: start/finish timestamps, runner, cwd, overall result (`passed`/`failed`/`blocked`/`compose_up_failed`/`seed_failed`).
- `preflight`: structured preflight result.
- `steps`: ordered list of each step with timestamps, command, return code, stdout, and stderr.

CLI flags:

- `--no-start` — skip compose up (use when containers are already running).
- `--no-teardown` — leave containers running after tests.
- `--record <path>` — override the evidence file path.
- `--print-evidence` — print the JSON record to stdout after running.
- `--skip-preflight` — bypass preflight (not recommended).
- `--logs-tail <N>` — change the number of log lines captured.

### Makefile Targets

- `make preflight-fileshare-live` — run preflight checks only.
- `make test-live-fileshare` — run full orchestration with default evidence file.
- `make test-live-fileshare-print-evidence` — same, but print evidence to stdout.
- `make fileshare-live-up` / `make fileshare-live-down` — manual container lifecycle.

### QA Acceptance Path

1. Run `make preflight-fileshare-live` first. If blockers are reported, do not start containers.
2. Run `make test-live-fileshare` to produce the evidence record.
3. Paste the record (or `make test-live-fileshare-print-evidence` output) into the PR or issue as验收证据.

### Unavailable Environment Fallback

- No Docker / no daemon / port conflict → preflight blocks with actionable steps; containers are never started.
- Missing optional SDKs → preflight warns; pytest skips the corresponding protocol tests.
- No network in CI → `make test` and `make coverage` remain the hard gates; live smoke is opt-in only.
- `make fileshare-check` (offline smoke) remains available without Docker or optional SDKs.
