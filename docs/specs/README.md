# Specs Index

This directory contains product specs, implementation contracts, and historical
EVI notes. New readers should not read everything front-to-back.

## Start Here

Read these first:

1. [MVP scope](./ragrig-mvp-spec.md)
2. [Metadata database](./ragrig-phase-1a-metadata-db-spec.md)
3. [Chunking and embedding](./ragrig-phase-1c-chunking-embedding-spec.md)
4. [Retrieval API](./ragrig-phase-1d-retrieval-api-spec.md)
5. [Web Console](./ragrig-web-console-spec.md)
6. [Architecture overview](../architecture.md)

## Active Product Specs

- [Local pilot](./ragrig-local-pilot-spec.md)
- [Web Console](./ragrig-web-console-spec.md)
- [Plugin system](./ragrig-plugin-system-spec.md)
- [Processing profiles](./ragrig-processing-profile-spec.md)
- [Processing profile persistence](./ragrig-processing-profile-persistence-spec.md)
- [Processing profile diff and rollback](./ragrig-processing-profile-diff-rollback-spec.md)
- [Processing profile sanitizer unification](./ragrig-processing-profile-sanitizer-unified.md)
- [Document understanding P1](./ragrig-document-understanding-p1-spec.md)
- [Document understanding P2](./ragrig-document-understanding-p2-spec.md)
- [Knowledge map cross-document understanding](./ragrig-knowledge-map-cross-document-understanding-spec.md)
- [KG lite graph retrieval](./ragrig-kg-lite-graph-retrieval-spec.md)
- [Vercel Preview + Supabase](./EVI-130-vercel-preview-supabase.md)

## Connectors And Backends

- [S3 source plugin](./ragrig-s3-source-plugin-spec.md)
- [Fileshare source plugin](./ragrig-fileshare-source-plugin-spec.md)
- [Database source connector](./ragrig-database-source-connector-spec.md)
- [Google Workspace source connector](./SPEC-google-workspace-source-connector.md)
- [Object storage sink](./ragrig-object-storage-sink-spec.md)
- [Parquet export](./ragrig-parquet-export-spec.md)
- [Qdrant vector backend](./ragrig-qdrant-vector-backend-spec.md)
- [Vector backend status console](./ragrig-vector-backend-status-console-spec.md)

## Reference Contracts

- [GitHub CI checks](./ragrig-github-ci-checks-spec.md)
- [Local-first quality and supply chain policy](./ragrig-local-first-quality-supply-chain-policy.md)
- [Core coverage and supply-chain gates](./ragrig-core-coverage-supply-chain-gates.md)
- [Cost and latency tracking](./ragrig-cost-latency-tracking-spec.md)
- [Advanced parser corpus](./ragrig-advanced-parser-corpus-spec.md)
- [Answer live smoke diagnostics](./answer-live-smoke-diagnostics.md)
- [Retrieval benchmark integrity](./retrieval-benchmark-integrity-spec.md)
- [Retrieval benchmark baseline refresh](./retrieval-benchmark-baseline-refresh-spec.md)
- [Sanitizer golden snapshot](./ragrig-sanitizer-golden-snapshot-spec.md)
- [Sanitizer golden drift diff](./sanitizer-golden-drift-diff-spec.md)
- [Sanitizer coverage artifact](./sanitizer-coverage-artifact-spec.md)
- [Understanding runs export v1](./understanding-runs-export-v1.md)

## Historical Phase Specs

These describe earlier build phases and are useful when reconstructing why a
module exists.

- [Phase 1a scaffold](./ragrig-phase-1a-scaffold-spec.md)
- [Phase 1a metadata DB](./ragrig-phase-1a-metadata-db-spec.md)
- [Phase 1b local ingestion](./ragrig-phase-1b-local-ingestion-spec.md)
- [Phase 1c chunking and embedding](./ragrig-phase-1c-chunking-embedding-spec.md)
- [Phase 1d retrieval API](./ragrig-phase-1d-retrieval-api-spec.md)
- [Phase 1e hybrid retrieval](./ragrig-phase-1e-hybrid-retrieval-spec.md)
- [Phase 1e local model provider plugin](./ragrig-phase-1e-local-model-provider-plugin-spec.md)
- [Phase 2 ACL](./phase2-acl.md)

## Internal EVI Notes

EVI files are project-tracking notes. They are retained for auditability, but
most newcomers should start with the active product specs above.

- [EVI-63](./EVI-63.md)
- [EVI-64](./EVI-64.md)
- [EVI-66](./EVI-66.md)
- [EVI-67](./EVI-67.md)
- [EVI-68](./EVI-68.md)
- [EVI-73](./EVI-73.md)
- [EVI-75](./EVI-75.md)
- [EVI-81](./EVI-81.md)
- [EVI-83](./EVI-83.md)
- [EVI-84 baseline compare](./EVI-84-baseline-compare.md)
- [EVI-87 sanitizer degraded summary](./EVI-87-sanitizer-degraded-summary.md)
- [EVI-93 sanitizer cross-layer contract](./EVI-93-sanitizer-cross-layer-contract-spec.md)
- [EVI-95 sanitizer contract matrix](./EVI-95-sanitizer-contract-matrix-spec.md)
- [EVI-102](./EVI-102.md)
- [EVI-104 phase 3 ACL regression](./EVI-104-phase3-acl-regression-spec.md)
- [EVI-105](./EVI-105.md)
- [EVI-106 ingestion DAG runner](./EVI-106-ingestion-dag-runner.md)
- [EVI-108 operations pack](./EVI-108-operations-pack.md)
- [EVI-110](./EVI-110.md)
- [EVI-111](./EVI-111.md)
- [EVI-120](./EVI-120.md)
- [EVI-124](./EVI-124.md)
- [EVI-129 fake reranker production guard](./EVI-129-fake-reranker-production-guard.md)
- [EVI-132 task runtime observability](./EVI-132-task-runtime-observability.md)
- [EVI-133](./EVI-133.md)
- [EVI-134 CI flow optimization](./EVI-134-ci-flow-optimization.md)
- [EVI-136 task retry failure recovery](./EVI-136-task-retry-failure-recovery.md)
- [EVI-138 CI test Python 3.12](./EVI-138-ci-test-python-312-spec.md)
- [EVI-139 retry multiprocess idempotency](./EVI-139-retry-multiprocess-idempotency.md)
- [EVI-140 CI required contexts drift](./EVI-140-ci-required-contexts-drift.md)
- [EVI-141 reranker policy observability](./EVI-141-reranker-policy-observability.md)
- [SPEC-EVI-79 sanitizer boundary hardening](./SPEC-EVI-79-sanitizer-boundary-hardening.md)
- [EVI-60 CI/CD optimization](./evi-60-cicd-optimization.md)

## Maintenance Notes

- Prefer adding new public-facing specs under descriptive `ragrig-*` names.
- Use EVI names only for internal tracking notes.
- Keep this index updated whenever a new spec becomes part of the recommended
  learning path.
