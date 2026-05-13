# EVI-111 Retrieval Benchmark Fixture ID Cross-Workspace Validation

Date: 2026-05-13
Issue: [EVI-111](mention://issue/318afcdf-368e-431f-a802-f05bac68da32)
Environment: macOS, local Multica workspace

## What Changed

1. `scripts.retrieval_benchmark_baseline_refresh._compute_fixture_id()` now hashes relative file paths plus file bytes instead of the fixture root absolute path.
2. `scripts.retrieval_benchmark_compare._check_manifest_compatibility()` now emits a baseline refresh hint when `fixture_id` mismatches, covering legacy path-derived manifests.
3. Unit tests now verify cross-workspace stability, content sensitivity, and legacy migration guidance.

## Cross-Environment Revalidation Notes

- Same corpus copied under two different temporary roots now produces the same `fixture_id`.
- Changing file bytes while keeping file size unchanged now produces a different `fixture_id`.
- Baselines generated before this change must be refreshed once because their `fixture_id` was derived from checkout-local absolute paths.

## Migration

```bash
make retrieval-benchmark-baseline-refresh
make retrieval-benchmark-compare
```

After refresh, the committed baseline and manifest become portable across different workspace roots as long as the corpus content is unchanged.

## Verification Commands

```bash
make lint
make test
make coverage
make web-check
BENCHMARK_BASELINE_PATH=/var/folders/p2/wwgksm0s2xj98__bmwzlglww0000gn/T/opencode/evi111-legacy-baseline.json make retrieval-benchmark-compare
make retrieval-benchmark-baseline-refresh
make retrieval-benchmark-compare
```

## Result Summary

- `make lint` passed via `ruff check .`
- `make test` passed: `1495 passed, 11 skipped`
- `make coverage` passed: total coverage `95.70%` with required `90.0%`
- `make web-check` passed: `131 passed`
- `BENCHMARK_BASELINE_PATH=/var/folders/p2/wwgksm0s2xj98__bmwzlglww0000gn/T/opencode/evi111-legacy-baseline.json make retrieval-benchmark-compare` failed with `fixture_id mismatch` and the expected legacy baseline refresh hint
- `make retrieval-benchmark-baseline-refresh` rewrote `docs/benchmarks/retrieval-benchmark-baseline.json` and `.manifest.json` with stable content-derived `fixture_id` `34f839a57cf1af5d`
- Final `make retrieval-benchmark-compare` passed with `overall_status: pass`
