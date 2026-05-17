# Verification commands

Day-to-day checks contributors and CI run. The README only lists `make test`
and `make lint`; everything below is for deeper validation.

## Default suite

```bash
make format
make lint
make test
make coverage
make web-check
make local-pilot-smoke
make dependency-inventory
```

These run in CI on every PR. `make web-check` covers the FastAPI Web Console
contract; `make local-pilot-smoke` runs the API-level Local Pilot smoke.

## Nightly evidence pack

```bash
make nightly-evidence-smoke
```

Automated in GitHub Actions; can be run locally when Docker-backed live
smoke is available.

## Browser-level Local Pilot Console check

```bash
make local-pilot-console-e2e
```

Starts an ephemeral SQLite-backed app, verifies a failed upload/retry path,
uploads Markdown/PDF/DOCX through the Web Console, checks pipeline/chunk UI,
and asks one grounded Playground question. Requires `npm` and a local
Chrome/Chromium browser; set
`RAGRIG_CONSOLE_E2E_BROWSER_CHANNEL=chromium` if Chrome is not available.

## Supply-chain checks

```bash
make licenses
make sbom
make audit
```

`make audit` needs network access to vulnerability services. Offline
environments should run `make audit-dry-run` and record the missing live
audit as a release blocker.

## Vercel Preview deployment smoke

```bash
VERCEL_PREVIEW_URL='https://your-preview-url.vercel.app' make vercel-preview-smoke
```

See [EVI-130](../specs/EVI-130-vercel-preview-supabase.md) for the full
contract and Supabase migration boundary.

## Optional live-provider smokes

Off by default — they need real credentials and incur cost. See
[optional-services.md](./optional-services.md) for env-var wiring of S3 /
MinIO, Qdrant, fileshare, and the answer live smoke against a local LLM.
