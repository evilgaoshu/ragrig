# RAGRig Web Console Plugin and Source Setup Wizard Spec

Date: 2026-05-05
Status: Implementation spec

## 1. Goal

Add a Web Console wizard that helps operators inspect plugin readiness, choose a source
or sink plugin, prepare a safe configuration draft, validate that draft through the real
plugin registry, and understand the next command or limitation.

The wizard must make the current plugin system usable without pretending that RAGRig has
a secret store, browser-triggered ingestion writes, or live enterprise connector setup.

## 2. Product Rules

- The wizard is registry-backed. It reads real plugin metadata from `/plugins`.
- The wizard is validation-backed. It validates configuration drafts through a backend
  endpoint that calls `PluginRegistry.validate_config`.
- The wizard is safe by default. It must not collect raw secrets; secret values should be
  expressed as `env:VARIABLE_NAME` references.
- The wizard is honest. Missing SDKs, contract-only stubs, degraded protocols, and
  unavailable plugins must be visible.
- The wizard is useful before writes exist. It should generate a validated config draft
  and command hints, not fake source creation.

## 3. Scope

In scope:

- Add a versioned spec and README references.
- Extend plugin discovery payloads with example config, docs reference, plugin type, family,
  tier, supported protocols, and readiness metadata already owned by the registry.
- Add a backend validation route:
  - `POST /plugins/{plugin_id}/validate-config`
  - request body: `{ "config": { ... } }`
  - success: returns `valid: true`, sanitized config, plugin readiness, required secrets,
    missing dependencies, docs reference, and next-step command hints
  - failure: returns `400` with `valid: false`, error code, and message
- Add a Web Console wizard panel:
  - filter chips for sources, sinks, models, vectors, and all plugins
  - searchable/selectable plugin list
  - status badges for ready/degraded/unavailable
  - config draft textarea seeded from `example_config`
  - secret guidance that encourages `env:` references
  - validate button that calls the backend route
  - validation result with sanitized config and next steps
- Add tests for route success/failure and console HTML contract.

Out of scope:

- Persisting plugin configuration.
- Creating sources from the browser.
- Storing or testing raw secrets.
- Running network connector probes.
- Implementing Google Workspace, Microsoft 365, wiki, database, or Office preview runtime
  connectors.
- Replacing existing CLI paths.

## 4. UX Requirements

The wizard should feel like an operator workbench, not a marketing page.

Required UI states:

- Empty/degraded state when no plugins are returned.
- Source plugin selected by default when available.
- `source.s3`, `source.fileshare`, `sink.object_storage`, `vector.qdrant`,
  `model.ollama`, and cloud provider stubs should be discoverable from the list when
  present in the registry.
- Config textarea shows formatted JSON and does not resize the whole layout.
- Invalid JSON is caught in the browser before a request is made.
- Backend validation errors are displayed without white-screening.
- Missing dependencies and required secrets are displayed near the selected plugin.
- The result panel must distinguish:
  - config schema is valid
  - plugin runtime is ready/degraded/unavailable
  - next action is CLI/config work, not browser persistence

## 5. Backend Contract

`POST /plugins/{plugin_id}/validate-config`

Example request:

```json
{
  "config": {
    "bucket": "docs",
    "prefix": "team-a",
    "access_key": "env:AWS_ACCESS_KEY_ID",
    "secret_key": "env:AWS_SECRET_ACCESS_KEY"
  }
}
```

Example success:

```json
{
  "valid": true,
  "plugin_id": "source.s3",
  "status": "ready",
  "config": {
    "bucket": "docs"
  },
  "secret_requirements": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
  "missing_dependencies": [],
  "next_steps": ["Run make s3-check after exporting the declared env vars."]
}
```

Example failure:

```json
{
  "valid": false,
  "error": {
    "code": "plugin_config_invalid",
    "message": "undeclared secret reference(s): BAD_SECRET"
  }
}
```

## 6. Acceptance Criteria

- `/console` renders a plugin/data source setup wizard.
- `/plugins` includes enough metadata for the wizard to render example config, docs links,
  required secrets, missing dependencies, status, capabilities, plugin type, family, and tier.
- `POST /plugins/{plugin_id}/validate-config` succeeds for valid example configs from
  configurable plugins.
- The validation route returns `400` for invalid plugin IDs, non-configurable plugins with
  config, undeclared secret references, invalid config shapes, and malformed request bodies.
- The Web Console validates JSON locally before calling the backend.
- The Web Console displays ready/degraded/unavailable states truthfully.
- The Web Console never asks for raw secret values.
- The wizard provides command hints for local ingestion, S3 source, fileshare source,
  object storage export, vector backend checks, and model/provider checks when those plugin
  families are selected.
- `make web-check`, `make test`, and `make coverage` pass.
- The PR description includes screenshots or a clear explanation if browser screenshot
  capture is blocked.
