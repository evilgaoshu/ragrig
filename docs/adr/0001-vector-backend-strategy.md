# ADR-0001: Vector backend strategy: pgvector first, Qdrant optional

- Date: 2026-05-31
- Status: Accepted

## Context

RAGRig needs vector search that works in local-first deployments, supports
workspace-aware filtering, and can be validated in CI without requiring a large
external service stack. The project also needs a path to managed or dedicated
vector infrastructure when deployments outgrow the relational database.

## Decision

Use pgvector as the default vector backend. Keep Qdrant as an optional backend
behind the existing vector store contract and compose profile.

The default application path stores metadata, ACL payloads, embeddings, and
retrieval audit context in PostgreSQL. Qdrant remains available for deployments
that need dedicated vector operations, but it must not be required for the
baseline local and CI experience.

## Consequences

pgvector keeps the default architecture small: one metadata database, one
migration path, and direct SQL joins for permission-aware retrieval. It also
lets CI verify exact distance semantics with a real PostgreSQL service.

The tradeoff is that high-scale vector workloads may need dedicated tuning or a
Qdrant migration. The vector store abstraction therefore must stay honest:
backend metadata, distance semantics, workspace filters, and degraded health
must be explicit rather than hidden behind a lowest-common-denominator API.

## Revisit When

Revisit this decision if production workloads show PostgreSQL becoming the
dominant retrieval bottleneck after indexing/query tuning, if Qdrant-only
features become required for core product behavior, or if managed vector
service operations become simpler than maintaining pgvector performance.

