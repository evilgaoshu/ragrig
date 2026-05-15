# EVI-138 CI Required Test Contexts SPEC v3

Date: 2026-05-15
Status: Accepted

## Goal

Make both branch-protection required GitHub checks report and pass:

- `RAGRig CI / test (3.11)`
- `RAGRig CI / test (3.12)`

## Requirements

- Set `.github/workflows/ci.yml` test job matrix `python-version` to `["3.11", "3.12"]`.
- Keep a CI configuration comment explaining that both versions come from branch protection required contexts.
- Do not change branch protection rules.
- Do not use admin bypass.
- Do not change other CI jobs.
- Do not change business code.

## Validation

- `.github/workflows/ci.yml` test job matrix is `python-version: ["3.11", "3.12"]`.
- `gh pr checks 131` shows both `RAGRig CI / test (3.11)` and `RAGRig CI / test (3.12)` as `pass`.
- `gh pr checks 131` shows `lint`, `coverage`, `db-smoke`, `web-smoke`, and `docker-build` as `pass`.
- This document is updated in the PR as SPEC v3.
