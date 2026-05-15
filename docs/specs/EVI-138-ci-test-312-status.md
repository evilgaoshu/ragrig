# EVI-138 CI Test 3.12 Status Spec

## Goal

Remove the dangling required GitHub status
`RAGRig CI / test (3.12)` by ensuring the CI test matrix emits a status
for Python 3.12.

## Hard Requirements

1. `.github/workflows/ci.yml` `test` job matrix `python-version` includes
   `"3.12"`.
2. After opening the PR, GitHub Actions runs `RAGRig CI / test (3.12)` and
   reports a pass or fail status instead of `Expected - Waiting for status to
   be reported`.
3. Existing Python 3.11 test matrix coverage remains in place.

## Out of Scope

- Do not modify branch protection rules.
- Do not change other CI jobs such as lint, coverage, or database smoke checks.
