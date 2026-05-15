# EVI-134 - ragrig CI Flow Optimization

## Goal

Reduce redundant CI work so PR feedback is faster while preserving the existing job boundaries and make target behavior.

## Hard Requirements

- Keep the `test` job on Python 3.11 only because the `coverage` job already runs the full suite on Python 3.12.
- Remove `uv sync --dev --frozen` from the `lint` job and run Ruff directly through `uvx`.
- Add `paths-ignore` to both `pull_request` and `push` triggers for `docs/**`, `*.md`, and `LICENSE`.
- Keep all existing CI jobs and make target logic intact.
- Require the PR's GitHub Actions checks to pass.

## Out of Scope

- Do not change Makefile test, coverage, or lint target logic.
- Do not merge or delete CI jobs.
- Do not introduce reusable workflows or composite actions.
