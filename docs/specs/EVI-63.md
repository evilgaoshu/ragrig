# EVI-63: Consolidated Chore/Deps Upgrade (2026-05-09)

## Scope

Consolidate the following Dependabot chore/deps PRs into a single upgrade:

| Original PR | Type | Dependency | Change |
|-------------|------|-----------|--------|
| [#40](https://github.com/evilgaoshu/ragrig/pull/40) | GitHub Actions | `actions/checkout` | v4 → v6 |
| [#41](https://github.com/evilgaoshu/ragrig/pull/41) | GitHub Actions | `actions/upload-artifact` | v4 → v7 |
| [#42](https://github.com/evilgaoshu/ragrig/pull/42) | GitHub Actions | `astral-sh/setup-uv` | v6 → v7 |
| [#43](https://github.com/evilgaoshu/ragrig/pull/43) | Python dev-dep | `openai` | `<2.0.0` → `<3.0.0` (in `cloud-openai` and `local-ml`) |
| [#44](https://github.com/evilgaoshu/ragrig/pull/44) | Python dev-dep | `sentence-transformers` | `<4.0.0` → `<6.0.0` |
| [#45](https://github.com/evilgaoshu/ragrig/pull/45) | Python dev-dep | `cohere` | `<6.0.0` → `<7.0.0` |
| [#46](https://github.com/evilgaoshu/ragrig/pull/46) | Python dev-dep | `pyarrow` | `<20.0.0` → `<25.0.0` |

## Changes Applied

### `.github/workflows/ci.yml`
- `actions/checkout@v4` → `actions/checkout@v6` (7 occurrences across all jobs)
- `astral-sh/setup-uv@v6` → `astral-sh/setup-uv@v7` (6 occurrences across lint, test, coverage, db-smoke, web-smoke, supply-chain jobs)
- `actions/upload-artifact@v4` → `actions/upload-artifact@v7` (2 occurrences in coverage and supply-chain jobs)

### `pyproject.toml`
- `cohere`: `>=5.15.0,<6.0.0` → `>=5.15.0,<7.0.0` (cloud-cohere)
- `openai`: `>=1.82.0,<2.0.0` → `>=1.82.0,<3.0.0` (cloud-openai + local-ml)
- `sentence-transformers`: `>=3.4.1,<4.0.0` → `>=3.4.1,<6.0.0` (local-ml)
- `pyarrow`: `>=19.0.0,<20.0.0` → `>=19.0.0,<25.0.0` (parquet)

### `uv.lock`
- Regenerated to reflect updated dependency constraints.

## Superseded PRs

After this consolidated PR is merged, the following should be closed/ignored:

- #40 (actions/checkout)
- #41 (actions/upload-artifact)
- #42 (astral-sh/setup-uv)
- #43 (openai)
- #44 (sentence-transformers)
- #45 (cohere)
- #46 (pyarrow)

## Verification

- CI: all jobs pass (lint, test, coverage, db-smoke, web-smoke, docker-build, supply-chain)
- `gh pr list --repo evilgaoshu/ragrig --state open` should show the above 7 PRs superseded/closed
- No functional changes; all modifications are version constraint bumps only
