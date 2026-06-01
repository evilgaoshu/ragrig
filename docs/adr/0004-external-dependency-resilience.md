# ADR-0004: External dependency resilience and circuit breakers

- Date: 2026-05-31
- Status: Accepted

## Context

RAGRig calls external systems for OIDC, webhooks, web imports, source
connectors, object stores, embedding models, rerankers, and answer providers.
The system already has route-level rate limiting, workflow retry backoff, task
queue isolation, Prometheus metrics, and OpenTelemetry spans. A single global
circuit breaker around every outbound call would be simple, but it would also
mix unrelated failure domains and could block healthy connectors because a
different provider is degraded.

## Decision

Do not introduce a global circuit breaker around all HTTP clients or connector
calls. Use targeted circuit breakers only around dependency groups with clear
ownership, consistent failure semantics, and a safe degraded mode:

- model providers, embedding providers, and rerankers;
- webhook delivery;
- connector families where the source kind is the operational boundary.

Circuit state must be keyed by low-cardinality dependency identity such as
provider name or source kind. It must not be keyed by user ID, email, document
URI, file path, query text, or raw tenant identifiers. Circuit transitions
should emit structured logs, OpenTelemetry events, and low-cardinality metrics.

Retries and circuit breakers must be coordinated. Retries happen inside a closed
or half-open circuit with exponential backoff. Once a circuit is open, requests
should fail fast or use an explicit degraded fallback instead of creating retry
storms.

## Consequences

This keeps resilience behavior local to the dependency that actually failed and
preserves useful observability from HTTPX spans and pipeline metrics. It avoids
turning transient failures in one integration into a process-wide outage.

The tradeoff is that future circuit breakers must be added deliberately per
dependency family. Each implementation needs tests for open, half-open, closed,
fallback, and metric/log behavior.

## Revisit When

Revisit this decision when the same circuit breaker policy is independently
needed by at least three dependency families, or when workers become the primary
runtime path and dependency health needs centralized coordination across
processes.
