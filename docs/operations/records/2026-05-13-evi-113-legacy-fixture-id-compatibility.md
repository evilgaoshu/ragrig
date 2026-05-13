# EVI-113 Historical Retrieval Benchmark Fixture ID Compatibility Notes

Date: 2026-05-13
Issue: EVI-113
Related issue: [EVI-111](mention://issue/318afcdf-368e-431f-a802-f05bac68da32)
Environment: repo documentation and evidence audit

## Goal

Prevent post-EVI-111 review work from misreading historical retrieval benchmark `fixture_id` mismatches as fresh regressions.

## Why Older IDs Can Be Invalid

- Before EVI-111, retrieval benchmark `fixture_id` values were derived from checkout absolute paths.
- The same fixture corpus could therefore produce different IDs in different workspaces even when file contents were unchanged.
- After EVI-111, `fixture_id` is content-derived from relative fixture paths plus file bytes, so old and new IDs are not directly comparable.

## Refresh And Revalidation Path

```bash
make retrieval-benchmark-baseline-refresh
make retrieval-benchmark-compare
make retrieval-benchmark-integrity-artifact
make retrieval-benchmark-integrity-summary
```

- Use the refreshed baseline and manifest for any new benchmark comparison, integrity check, or regression triage.
- Do not rewrite older artifacts only to make their IDs match; preserve them as time-stamped historical evidence.

## Historical Snapshot Boundary

The following repository artifacts may still contain legacy path-derived `fixture_id` values and must be treated as snapshot-only references unless regenerated after EVI-111:

- `docs/benchmarks/retrieval-benchmark-baseline.json`
- `docs/benchmarks/retrieval-benchmark-baseline.manifest.json`
- `docs/operations/artifacts/retrieval-benchmark-integrity.json`
- `docs/operations/artifacts/retrieval-benchmark-integrity_summary.json`
- `docs/operations/artifacts/retrieval-benchmark-integrity_summary.md`

What they are still good for:

- historical latency and result-count review
- confirming that a baseline/integrity artifact existed at a given time
- preserving prior evidence linked from specs, PRs, or issue threads

What they are not good for after EVI-111 unless regenerated:

- deciding whether a current `fixture_id mismatch` is a new regression
- comparing fixture identity across different workspace roots
- serving as the authoritative source for post-migration baseline compatibility

## Current Historical Snapshot Observed In Repo

During this audit, the checked-in historical snapshot references the following legacy values:

- baseline manifest `fixture_id`: `eb323cc73a16db53`
- baseline manifest `created_at`: `2026-05-11T03:30:59Z`
- integrity artifact `generated_at`: `2026-05-12T06:46:52.181989+00:00`

These values are preserved for historical traceability. If a future reviewer needs an authoritative compatibility check, they must regenerate the baseline and integrity artifacts through the refresh path above.

## Docs Updated In This Audit

- `docs/specs/retrieval-benchmark-baseline-refresh-spec.md`
- `docs/specs/retrieval-benchmark-integrity-spec.md`
- `docs/specs/EVI-81.md`
- `docs/specs/EVI-84-baseline-compare.md`

## Best-Effort Difference Summary

- Historical snapshots in this repo still show legacy `fixture_id` `eb323cc73a16db53`.
- After EVI-111 refresh, the stable content-derived `fixture_id` is expected to differ even when fixture contents are unchanged, because the old ID encoded checkout path information and the new one does not.
