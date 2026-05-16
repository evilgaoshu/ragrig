# EVI-140 CI Required Contexts Record

Date: 2026-05-16
Status: Accepted

## Decision

RAGRig declares branch-protection required GitHub CI contexts in
`docs/specs/EVI-140-ci-required-contexts-drift.md` and validates them with
`scripts.check_required_ci_contexts`.

The local check is the default acceptance path because it needs no GitHub
branch-protection permissions. It confirms every required context is still
produced by `.github/workflows/ci.yml` and that the test matrix has not
reintroduced an unexpected Python context. Remote branch-protection comparison
is optional and degrades clearly when `gh api` is unavailable or unauthorized.

## Acceptance

Run the permission-free drift check:

```bash
uv run python -m scripts.check_required_ci_contexts
```

Optionally compare live `main` branch protection:

```bash
gh api repos/evilgaoshu/ragrig/branches/main/protection/required_status_checks --jq '.contexts'
uv run python -m scripts.check_required_ci_contexts --remote
```

Interpret PR checks with:

```bash
gh pr checks <number>
```

All required contexts from the EVI-140 spec should be present and
passing. `RAGRig CI / test (3.11)` must not be required; the preserved
test matrix is Python 3.12 only.
