# EVI-138 CI Python 3.12 Required Context SPEC

Date: 2026-05-15
Status: Accepted

## Goal

Unify the RAGRig CI `test` job on Python 3.12 and align the `main`
branch protection required checks with that single test context, avoiding
a merge block on the obsolete `RAGRig CI / test (3.11)` context.

## Requirements

- Set `.github/workflows/ci.yml` test job matrix `python-version` to `["3.12"]`.
- Update `main` branch protection required status checks so `RAGRig CI / test (3.11)` is not required and `RAGRig CI / test (3.12)` is required.
- Do not keep a 3.11 required check.
- Do not add a dual-version test matrix.
- Do not change other CI jobs.
- Do not change business code.

## Decision Rationale

Python 3.12 is already used by the other RAGRig CI jobs, and the project
declares `requires-python = ">=3.11"`. A single 3.12 test matrix keeps CI
consistent and avoids duplicate test runtime while still matching the
repository's required merge gate after branch protection is updated.

## Validation

- `.github/workflows/ci.yml` test job matrix is `python-version: ["3.12"]`.
- `gh api repos/evilgaoshu/ragrig/branches/main/protection/required_status_checks --jq '.contexts'` does not contain `RAGRig CI / test (3.11)` and does contain `RAGRig CI / test (3.12)`.
- `gh pr checks 131` shows all required checks as `pass`.
- This document is updated in the PR for the final single-version 3.12 SPEC.
