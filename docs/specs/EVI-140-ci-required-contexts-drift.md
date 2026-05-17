# EVI-140 CI Required Contexts Drift SPEC

Date: 2026-05-16
Status: Accepted

## Goal

Keep the repository-declared required GitHub CI contexts aligned with
`.github/workflows/ci.yml` job names and matrix expansion, so branch
protection does not drift after CI workflow edits.

## Required Contexts

This block is the repository-owned expected branch-protection context list
consumed by `scripts.check_required_ci_contexts`. Keep it aligned with the live
`main` required status checks.

<!-- required-ci-contexts:start -->
- `RAGRig CI / lint`
- `RAGRig CI / test (3.12)`
- `RAGRig CI / db-smoke`
- `RAGRig CI / smoke`
- `RAGRig CI / docker-build`
- `RAGRig CI / frontend`
<!-- required-ci-contexts:end -->

The test matrix covers `["3.12"]` only. `web-smoke` was consolidated into
the test matrix job (each matrix entry now runs `make web-check` after
`make test-fast`), so the standalone `RAGRig CI / web-smoke` context is no
longer emitted. `RAGRig CI / coverage` runs only on push to main (not on
PRs) to keep PR feedback fast; it is therefore not a required PR context.

Other workflow jobs, such as `detect-changes`, `drift-diff`, and
`supply-chain`, may run on PRs without being branch-protection required
contexts. `benchmark-guard` now runs in the nightly workflow only. The local checker treats them as non-required workflow contexts while
still failing if a required context disappears or the test matrix introduces an
unexpected `RAGRig CI / test (...)` context.

## Validation

Local, permission-free validation:

```bash
uv run python -m scripts.check_required_ci_contexts
```

This check parses the expected required context list above, parses
`.github/workflows/ci.yml`, expands lightweight matrix values, and fails when a
required context is missing from the workflow or an unexpected test matrix
context appears. It does not call GitHub and is safe for CI, forks, and local
contributors without branch-protection permissions.

Optional branch-protection validation:

```bash
gh api repos/evilgaoshu/ragrig/branches/main/protection/required_status_checks --jq '.contexts'
uv run python -m scripts.check_required_ci_contexts --remote
```

The direct `gh api` command is the authority for the live `main` branch
protection setting. `--remote` compares that required-context value exactly
with this spec when the caller has permission. If GitHub denies the API call or
`gh` is not authenticated, the script reports `branch protection check:
degraded` and exits successfully as long as the local workflow/spec comparison
passes.

PR check interpretation:

```bash
gh pr checks <number>
```

For merge readiness, every context listed in this document should appear
as a passing required check for the PR. A missing or pending required
context usually means branch protection and workflow naming have drifted,
the workflow did not run for that PR, or the check name changed.

## Authority Boundaries

- This repository can declare expected contexts and prevent workflow
  naming/matrix drift.
- GitHub branch protection remains a remote repository setting. Updating
  it requires repository administration permission and cannot be enforced
  from a normal fork or default CI token.
- A no-permission environment is acceptable when the local drift check
  passes and the remote check clearly reports degraded access instead of
  pretending the live branch protection was verified.
