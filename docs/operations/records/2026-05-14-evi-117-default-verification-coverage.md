# EVI-117 Retrieval Benchmark Legacy Guard Default Verification Coverage

Date: 2026-05-14
Issue: EVI-117
Related issue: EVI-116, EVI-113, EVI-111

## Goal

Confirm where the retrieval benchmark legacy `fixture_id` guard is covered by default local and CI verification, and record the dedicated repro paths when operators need the raw failure or warning output.

## Default Verification Entry Points

| Entry point | Local default | GitHub CI default | Legacy guard coverage | Notes |
|---|---|---|---|---|
| `make lint` | Yes | `lint` job | No | Style and static checks only. |
| `make test` | Yes | Indirectly via `make test-fast` in `test` job | Yes | Runs retrieval benchmark unit tests, including legacy compare and integrity guard regressions. |
| `make coverage` | Yes | `coverage` job | Yes | Local `make coverage` runs the full pytest suite; the CI `coverage` job focuses on coverage artifacts and evaluation output. |
| `make web-check` | Yes | `web-smoke` job | Partial | Covers the Web Console integrity consumer, not the compare preflight failure text. |
| `make retrieval-benchmark-compare` | Dedicated | `benchmark-guard` job | Yes | Reproduces the active-baseline failure path with the raw compare error. |
| `make retrieval-benchmark-integrity-artifact` | Dedicated | `benchmark-guard` job | Yes | Surfaces `legacy_fixture_id` as a degraded reason in a standard CI artifact path. |

## Verified Failure and Warning Paths

### Active baseline failure path

- Guard location: `scripts/retrieval_benchmark_compare._check_manifest_compatibility()`
- Trigger: baseline manifest carries known snapshot-only legacy `fixture_id` `eb323cc73a16db53`
- Failure text:
  - `legacy path-derived fixture_id detected: 'eb323cc73a16db53'; this snapshot-only artifact must be refreshed via make retrieval-benchmark-baseline-refresh before reuse as an active baseline`
- Default coverage:
  - `tests/test_retrieval_benchmark_baseline_refresh.py::TestManifestCompatibility::test_fail_when_baseline_uses_legacy_path_derived_fixture_id`
  - `tests/test_retrieval_benchmark_compare.py::TestLegacyFixtureGuard::test_legacy_fixture_id_mismatch_includes_refresh_guidance`

### Integrity warning path

- Guard location: `src/ragrig/retrieval_benchmark_integrity.check_integrity()`
- Trigger: manifest carries known snapshot-only legacy `fixture_id`
- Warning text:
  - `legacy_fixture_id: legacy path-derived fixture_id detected: 'eb323cc73a16db53'; this snapshot-only artifact must be refreshed via make retrieval-benchmark-baseline-refresh before reuse as an active baseline`
- Default coverage:
  - `tests/test_retrieval_benchmark_integrity.py::TestCheckIntegrityValid::test_degraded_when_manifest_uses_legacy_fixture_id`
  - `make retrieval-benchmark-integrity-artifact`
  - `make retrieval-benchmark-integrity-summary`

## Manual Operator Path

1. Refresh the active baseline with `make retrieval-benchmark-baseline-refresh`.
2. Re-run `make retrieval-benchmark-compare` to confirm the active baseline now passes preflight.
3. Re-run `make retrieval-benchmark-integrity-artifact && make retrieval-benchmark-integrity-summary` to regenerate integrity evidence.

## CI Acceptance Note

- EVI-120 adds a standalone `RAGRig CI / benchmark-guard` check for `make retrieval-benchmark-compare`, `make retrieval-benchmark-integrity-artifact`, and `make retrieval-benchmark-integrity-summary`.
- The `coverage` job no longer generates retrieval benchmark integrity artifacts, avoiding duplicate execution while keeping the failure signal visible in the PR check list.
- The dedicated job stays deterministic because it does not refresh or mutate snapshot-only benchmark artifacts during PR checks.

## Snapshot Boundary Reconfirmed

- Historical snapshot-only artifacts remain read-only references and are not auto-rewritten by this task:
  - `docs/benchmarks/retrieval-benchmark-baseline.json`
  - `docs/benchmarks/retrieval-benchmark-baseline.manifest.json`
  - `docs/operations/artifacts/retrieval-benchmark-integrity.json`
  - `docs/operations/artifacts/retrieval-benchmark-integrity_summary.json`
  - `docs/operations/artifacts/retrieval-benchmark-integrity_summary.md`
- The guard only blocks reuse of known legacy IDs as active compatibility inputs.
