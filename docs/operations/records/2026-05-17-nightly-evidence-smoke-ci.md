# Automated Nightly Evidence Smoke CI

This record closes the Local Pilot roadmap item for automated nightly evidence
smoke in CI.

## Changes

- Added `make nightly-evidence-smoke`, backed by `scripts.nightly_evidence_smoke`.
- Added `.github/workflows/nightly-evidence-smoke.yml` with nightly schedule,
  manual dispatch, and PR path checks for workflow/orchestrator changes.
- The smoke runs the seven EVI-110 evidence groups, refreshes the pilot
  go/no-go evidence pack, and writes JSON/Markdown summaries plus per-command
  logs under `docs/operations/artifacts/`.
- Dockerized pilot and operations smoke run under an isolated
  `ragrig-nightly-evidence` compose project with a fresh volume so stale local
  development databases cannot affect the scheduled evidence result.
- The workflow installs the `fileshare` extra so SMB/WebDAV/SFTP live smoke has
  its optional SDKs in GitHub-hosted runners.

## Evidence

```bash
uv run pytest tests/test_nightly_evidence_smoke.py tests/test_github_ci_docs.py -q
make nightly-evidence-smoke
make lint
make test
```

The nightly workflow uploads:

```text
docs/operations/artifacts/nightly-evidence-smoke.json
docs/operations/artifacts/nightly-evidence-smoke.md
docs/operations/artifacts/nightly-evidence-smoke-logs/
docs/operations/artifacts/pilot-go-no-go-evidence.json
docs/operations/records/EVI-110-pilot-go-no-go-evidence.md
```

## Boundary

The job is secret-free. Provider live answer checks may report `healthy`,
`degraded`, or `skip`; silent absence of the artifact fails the smoke through the
evidence-pack decision status.
