# Architecture Decision Records

Architecture Decision Records (ADRs) capture durable technical decisions that
shape RAGRig. They are not implementation specs; each record should explain the
context, decision, consequences, and what would make the decision worth
revisiting.

## Status Values

- `Proposed`: under discussion and not yet binding
- `Accepted`: current project direction
- `Superseded`: replaced by a later ADR

## Index

| ADR | Status | Title |
| --- | --- | --- |
| [0001](0001-vector-backend-strategy.md) | Accepted | Vector backend strategy: pgvector first, Qdrant optional |
| [0002](0002-database-test-strategy.md) | Accepted | Database test strategy: SQLite fast path plus PostgreSQL pgvector CI |
| [0003](0003-application-boundary.md) | Accepted | Application boundary: modular FastAPI monolith before services |

