# ADR-0003: Application boundary: modular FastAPI monolith before services

- Date: 2026-05-31
- Status: Accepted

## Context

RAGRig currently combines ingestion, retrieval, auth, evaluation, observability,
and the web console in one deployable application. The project is still adding
core product behavior, and many flows cross database models, ACL checks,
retrieval ranking, and audit/usage records.

## Decision

Keep a modular FastAPI monolith as the default deployment boundary. Enforce
internal boundaries through routers, services, repositories, schemas, and import
guards before introducing separate microservices.

Services may be extracted later when there is a clear independent scaling,
security, or operational ownership need. Until then, split code by module and
contract, not by network boundary.

## Consequences

The monolith keeps local-first setup, migrations, transaction boundaries, and
end-to-end smoke tests straightforward. It also reduces distributed tracing,
deployment, and compatibility overhead while the product surface is still
changing.

The tradeoff is that module boundaries must be actively maintained. Routers
should stay thin, services should not import routers, repositories should own
data access, and shared error/permission contracts should live below the router
layer.

## Revisit When

Revisit this decision when one subsystem needs independent scaling or release
cadence, when isolation is required for tenant/security reasons, or when queue
backed workers become the dominant runtime path and need separate operational
ownership.

