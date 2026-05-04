# RAGRig GitHub CI Checks Spec

Date: 2026-05-04
Status: Accepted for EVI-36

## Goal

Establish the smallest GitHub Actions baseline that produces stable PR checks for RAGRig and removes the current `no checks reported` merge risk.

## Scope

- Add `.github/workflows/ci.yml` with a stable workflow name: `RAGRig CI`.
- Trigger the workflow on `pull_request` to `main` and `push` to `main`.
- Use Python 3.11 with `uv.lock`-based dependency installation via `uv sync --dev --frozen`.
- Run the current baseline commands in CI:
  - `uv run ruff check .`
  - `make test`
  - `make web-check`
- Document the GitHub CI coverage and its validation boundary in repository docs.

## Non-Goals

- Do not require secrets, cloud accounts, GPUs, Ollama, LM Studio, model downloads, or any local model service.
- Do not depend on `192.168.3.100` or any shared-host runtime service.
- Do not add `make coverage`, `make supply-chain-check`, SBOM, audit, or license jobs while EVI-35 is still not merged to `main`.

## Workflow Requirements

- The GitHub check name must remain stable so PM, QA, and PR review can reference it reliably.
- CI must not modify `uv.lock`; installs must stay frozen.
- Failure logs must clearly show whether `Lint`, `Test`, or `Web check` failed.
- `make web-check` remains a hard requirement for this issue even if it is currently a subset of `make test`.

## Documentation Requirements

- `README.md` must describe:
  - what GitHub CI covers
  - what local developer validation still covers
  - what shared-environment validation still covers
  - what GitHub CI does not cover yet
- The README must explicitly state that this workflow does not replace `192.168.3.100` runtime verification when an issue requires shared-environment evidence.

## Follow-Up Boundary

- If EVI-35 lands before this branch merges, rebase and evaluate whether newly landed stable commands should be added.
- If EVI-35 does not land first, keep this workflow limited to the current baseline and record EVI-35 as the next expansion point.
- After the first successful workflow run exists on GitHub, the repository owner may still need to configure branch protection required checks manually.
