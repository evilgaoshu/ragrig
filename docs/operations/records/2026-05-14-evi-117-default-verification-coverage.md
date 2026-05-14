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
| `make coverage` | Yes | `coverage` job | Yes | Local `make coverage` runs the full pytest suite; the CI `coverage` job additionally emits integrity artifact and summary after coverage completes. |
| `make web-check` | Yes | `web-smoke` job | Partial | Covers the Web Console integrity consumer, not the compare preflight failure text. |
| `make retrieval-benchmark-compare` | Dedicated | Not in default CI job graph | Yes | Reproduces the active-baseline failure path with the raw compare error. |
| `make retrieval-benchmark-integrity-artifact` | Dedicated | `coverage` job | Yes | Surfaces `legacy_fixture_id` as a degraded reason in a standard CI artifact path. |

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

- GitHub CI does not run `make retrieval-benchmark-compare` as a standalone required check today.
- Accepted reason: the active-baseline failure path is already enforced by default pytest coverage in `make test-fast` and `make coverage`, while the `coverage` job also publishes the integrity artifact path for reviewer visibility.
- This keeps CI lightweight and deterministic without refreshing or mutating snapshot-only benchmark artifacts during PR checks.

## Snapshot Boundary Reconfirmed

- Historical snapshot-only artifacts remain read-only references and are not auto-rewritten by this task:
  - `docs/benchmarks/retrieval-benchmark-baseline.json`
  - `docs/benchmarks/retrieval-benchmark-baseline.manifest.json`
  - `docs/operations/artifacts/retrieval-benchmark-integrity.json`
  - `docs/operations/artifacts/retrieval-benchmark-integrity_summary.json`
  - `docs/operations/artifacts/retrieval-benchmark-integrity_summary.md`
- The guard only blocks reuse of known legacy IDs as active compatibility inputs.
