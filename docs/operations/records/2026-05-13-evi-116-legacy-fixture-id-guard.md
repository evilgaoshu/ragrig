# EVI-116 Retrieval Benchmark Legacy Fixture ID Guard

Date: 2026-05-13
Issue: EVI-116
Related issue: EVI-113, EVI-111

## Goal

Add an automated guard so snapshot-only legacy retrieval benchmark `fixture_id` values cannot be reused as the active baseline identity.

## Guard Entry Points

- `scripts/retrieval_benchmark_baseline_refresh.py`
  - `_compute_fixture_id()` now derives the identifier from relative fixture paths plus file bytes only.
  - `build_manifest()` rejects any computed ID that matches the known legacy snapshot-only set.
- `scripts/retrieval_benchmark_compare.py`
  - `_check_manifest_compatibility()` fails before normal fixture comparison when the baseline manifest carries a known legacy path-derived ID.
- `src/ragrig/retrieval_benchmark_integrity.py`
  - `check_integrity()` records `legacy_fixture_id` as a degraded reason when the manifest carries a known legacy snapshot-only ID.

## Trigger Condition

The guard triggers when a manifest `fixture_id` matches a known pre-EVI-111 path-derived snapshot ID, currently:

- `eb323cc73a16db53`

## Failure / Warning Text

- Compare / refresh rejection:
  - `legacy path-derived fixture_id detected: 'eb323cc73a16db53'; this snapshot-only artifact must be refreshed via make retrieval-benchmark-baseline-refresh before reuse as an active baseline`
- Integrity degraded reason:
  - `legacy_fixture_id: legacy path-derived fixture_id detected: 'eb323cc73a16db53'; this snapshot-only artifact must be refreshed via make retrieval-benchmark-baseline-refresh before reuse as an active baseline`

## Regression Coverage

- `tests/test_retrieval_benchmark_baseline_refresh.py`
  - verifies `fixture_id` stays stable across different checkout absolute paths when file contents are identical
  - verifies compare rejects a baseline manifest carrying the legacy snapshot-only ID
- `tests/test_retrieval_benchmark_integrity.py`
  - verifies integrity surfaces the legacy snapshot-only ID as a degraded reason

## Snapshot Boundary

- Existing historical artifacts remain unchanged:
  - `docs/benchmarks/retrieval-benchmark-baseline.json`
  - `docs/benchmarks/retrieval-benchmark-baseline.manifest.json`
  - `docs/operations/artifacts/retrieval-benchmark-integrity.json`
  - `docs/operations/artifacts/retrieval-benchmark-integrity_summary.json`
  - `docs/operations/artifacts/retrieval-benchmark-integrity_summary.md`
- The new guard only blocks future reuse of those snapshot-only IDs as active compatibility inputs.
- Historical snapshot artifacts are preserved for traceability and are not auto-rewritten by this task.
