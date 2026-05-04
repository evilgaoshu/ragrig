# Supply Chain Operations

## Commands

Run from a fresh clone after `make sync`.

```bash
make licenses
make sbom
make audit
make supply-chain-check
```

## Outputs

- `docs/operations/artifacts/licenses.json`
- `docs/operations/artifacts/sbom.cyclonedx.json`
- `docs/operations/artifacts/pip-audit.json`

## What Each Command Checks

- `make licenses`: fails on GPL, AGPL, SSPL, or source-available matches from installed third-party dependencies.
- `make sbom`: exports the current Python environment as a CycloneDX JSON SBOM.
- `make audit`: queries the vulnerability service for the currently installed environment.

## Offline Or Degraded Environments

- `make licenses` and `make sbom` work offline after dependencies are installed.
- `make audit` requires network access.
- If the environment is offline, run `make audit-dry-run` to confirm dependency collection still works, then record the vulnerability audit as blocked instead of silently skipping it.

## Governance Notes

- Optional cloud, OCR, enterprise connector, and heavy ML SDKs must stay out of the default dependency set.
- Core imports must succeed without optional extras installed.
- Refresh `docs/operations/dependency-inventory.md` with `make dependency-inventory` when dependency groups change.
