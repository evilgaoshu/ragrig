# Google Workspace Diagnostics Parity

Date: 2026-05-16

## Scope

This record closes the Local Pilot roadmap item for Google Workspace pilot diagnostics parity with the production connector contract.

The connector remains a pilot and does not make live Google API calls in CI. The hardening is in the operator-facing contract:

- missing credentials report `skip`, not false success
- malformed service-account JSON reports `degraded`
- fixture discovery reports `healthy`
- `permission_mapping` is explicitly `not_declared`
- raw service-account payloads are not emitted in JSON or text diagnostics

## Evidence

Primary command:

```bash
make google-workspace-diagnostics
```

Primary artifact:

```text
docs/operations/artifacts/google-workspace-diagnostics.json
```

Supporting tests:

```bash
uv run pytest tests/test_google_workspace_source.py tests/test_google_workspace_diagnostics.py
```

## Production Boundary

The diagnostics artifact records `network_calls=false` and `ci_mode=dry_run_fixture`. Live Google Drive API retry remains reserved behind `max_retries`; the pilot does not claim live retry or permission mapping support until runtime output includes those payloads.
