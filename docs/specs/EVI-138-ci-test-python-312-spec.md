# EVI-138 CI Test Python 3.12 SPEC

Date: 2026-05-15
Status: Accepted

## Goal

Make the `RAGRig CI / test (3.12)` GitHub check report status by running the CI test job on Python 3.12.

## Requirements

- Set `.github/workflows/ci.yml` test job matrix `python-version` to `["3.12"]`.
- Do not keep a Python 3.11 test matrix entry.
- Do not change branch protection rules.
- Do not change other CI jobs.
- Do not add Python 3.11 tests.

## Validation

- `.github/workflows/ci.yml` test job matrix is `python-version: ["3.12"]`.
- A pull request reports `RAGRig CI / test (3.12)` as pass or fail instead of waiting for status.
- Existing CI jobs `lint`, `coverage`, `db-smoke`, `web-smoke`, and `benchmark-guard` remain present.
