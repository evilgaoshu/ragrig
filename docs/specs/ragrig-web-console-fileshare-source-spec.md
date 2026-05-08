# RAGRig Web Console Fileshare Source Spec

Date: 2026-05-08
Status: Implementation spec

## 1. Goal

Add a dedicated Fileshare Source panel to the RAGRig Web Console so operators can
inspect, configure, and diagnose the `source.fileshare` plugin without using the CLI
or reading documentation.

The panel must make the four supported protocols (SMB, NFS mounted path, WebDAV, SFTP)
visible with their readiness states, required configuration fields, secret hints,
optional SDK gaps, and live-smoke documentation links.

## 2. Scope

In scope:

- Enrich the `source.fileshare` plugin discovery payload with per-protocol metadata:
  - `protocol_example_configs` — example configuration for each protocol
  - `protocol_secret_requirements` — required secrets per protocol
  - `protocol_missing_dependencies` — missing optional SDKs per protocol
- Add a dedicated "Fileshare Source" panel to `web_console.html`:
  - Overall plugin readiness status (READY / DEGRADED / UNAVAILABLE)
  - One card per protocol with status badge
  - Required fields list per protocol
  - Required secrets hints (no plaintext storage)
  - Missing SDK dependency list when unavailable
  - Degraded / unavailable reason text
  - Collapsible example config JSON
  - Live-smoke doc link and CLI commands (`make fileshare-check`, `make test-live-fileshare`)
- Update the Plugin Readiness panel to include `source.fileshare`
- Add tests for new registry fields and HTML panel content
- Add this spec document

Out of scope:

- Browser-triggered fileshare source creation or live connection testing
- Secret value storage or retrieval
- Changes to the plugin registry core logic beyond discovery payload enrichment
- Changes to the fileshare connector backend capabilities

## 3. Backend Contract

The `/plugins` endpoint already returns `source.fileshare` with:

- `status` — overall plugin readiness
- `reason` — overall unavailable / degraded reason
- `supported_protocols` — list of protocol keys
- `protocol_statuses` — map of protocol -> status
- `secret_requirements` — plugin-level secret names
- `missing_dependencies` — plugin-level missing SDKs
- `docs_reference` — path to spec document

This feature extends the payload with:

- `protocol_example_configs` — map of protocol -> example config object
- `protocol_secret_requirements` — map of protocol -> list of secret names
- `protocol_missing_dependencies` — map of protocol -> list of missing SDKs

Example payload fragment:

```json
{
  "plugin_id": "source.fileshare",
  "status": "degraded",
  "reason": "Mounted NFS/local-path mode is ready; install optional SDKs for SMB, WebDAV, and SFTP.",
  "supported_protocols": ["nfs_mounted", "sftp", "smb", "webdav"],
  "protocol_statuses": {
    "nfs_mounted": "ready",
    "sftp": "unavailable",
    "smb": "unavailable",
    "webdav": "unavailable"
  },
  "protocol_example_configs": {
    "nfs_mounted": { "protocol": "nfs_mounted", "root_path": "/mnt/share/docs" },
    "smb": { "protocol": "smb", "host": "files.example.internal", "share": "knowledge", "root_path": "/docs", "username": "env:FILESHARE_USERNAME", "password": "env:FILESHARE_PASSWORD" },
    "webdav": { "protocol": "webdav", "base_url": "https://webdav.example.com", "root_path": "/docs", "username": "env:FILESHARE_USERNAME", "password": "env:FILESHARE_PASSWORD" },
    "sftp": { "protocol": "sftp", "host": "sftp.example.com", "root_path": "/docs", "username": "env:FILESHARE_USERNAME", "password": "env:FILESHARE_PASSWORD", "private_key": "env:FILESHARE_PRIVATE_KEY" }
  },
  "protocol_secret_requirements": {
    "nfs_mounted": [],
    "smb": ["FILESHARE_USERNAME", "FILESHARE_PASSWORD"],
    "webdav": ["FILESHARE_USERNAME", "FILESHARE_PASSWORD"],
    "sftp": ["FILESHARE_USERNAME", "FILESHARE_PASSWORD", "FILESHARE_PRIVATE_KEY"]
  },
  "protocol_missing_dependencies": {
    "nfs_mounted": [],
    "smb": ["smbprotocol"],
    "webdav": ["httpx"],
    "sftp": ["paramiko"]
  }
}
```

## 4. UX Requirements

The Fileshare Source panel lives in the right column of the Web Console, below
"Plugin Readiness" and above "Health / DB Status".

### Panel layout

- **Header**: "Fileshare Source" with subtitle "SMB · NFS mounted path · WebDAV · SFTP"
- **Overall status pill**: READY / DEGRADED / UNAVAILABLE from real registry data
- **Protocol cards** (one per protocol):
  - Protocol display name + status pill
  - Required fields list (e.g., `host, share, root_path`)
  - Required secrets list (or "none")
  - Missing SDK gap list when unavailable
  - Reason text
  - Example config JSON code block
- **Live smoke & docs card**:
  - Offline command: `make fileshare-check`
  - Live command: `make test-live-fileshare`
  - Docs link to `docs/specs/ragrig-fileshare-source-plugin-spec.md`

### Status semantics

- **READY** (green pill): all optional dependencies for this protocol are installed
- **UNAVAILABLE** (red pill): one or more optional SDKs are missing
- **DEGRADED** (amber pill, overall only): some protocols ready, some unavailable

### Honest states

- No mock data. Statuses come from `PluginRegistry.list_discovery()`.
- Missing SDKs are listed explicitly.
- Secrets are never shown in raw form; only env-var names are hinted.

## 5. Acceptance Criteria

- [x] Web Console renders a dedicated "Fileshare Source" panel with 4 protocol cards
- [x] Each protocol shows readiness status from real plugin registry data
- [x] Each protocol shows required config fields and secret hints
- [x] Missing SDK dependencies are listed per protocol when unavailable
- [x] Degraded / unavailable reasons are shown
- [x] Live-smoke commands and doc link are present
- [x] `/plugins` endpoint returns enriched per-protocol metadata
- [x] Plugin Readiness panel includes `source.fileshare`
- [x] `make test` passes (285 passed, 9 skipped)
- [x] `make web-check` passes
- [x] Spec document exists in `docs/specs/`

## 6. Non-goals

- Browser-side live connection testing to real fileshares
- Secret storage or encryption
- Creating or editing sources from the browser
- i18n beyond English in this phase
- Form validation beyond what the plugin registry already provides

## 7. Related Documents

- `docs/specs/ragrig-fileshare-source-plugin-spec.md` — backend connector spec
- `docs/specs/ragrig-web-console-spec.md` — overall Web Console spec
- `docs/specs/ragrig-web-console-plugin-source-wizard-spec.md` — plugin wizard spec
