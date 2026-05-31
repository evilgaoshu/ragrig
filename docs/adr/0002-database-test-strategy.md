# ADR-0002: Database test strategy: SQLite fast path plus PostgreSQL pgvector CI

- Date: 2026-05-31
- Status: Accepted

## Context

The test suite must stay fast enough for frequent local runs while still
catching behavior that only appears on PostgreSQL, especially pgvector distance
calculation, JSONB ACL filtering, migrations, and production-style database
URLs.

## Decision

Keep SQLite as the default local unit and fast integration test database. Add
targeted PostgreSQL CI coverage for migration health and pgvector distance
semantics.

Tests that depend on PostgreSQL-specific behavior must make that dependency
explicit through CI services or environment variables. Generic service tests
should continue to use SQLite when the behavior is database-agnostic.

## Consequences

Local feedback stays quick and cheap. CI still protects the production database
contract where SQLite is not a faithful substitute.

This split requires discipline: SQLite tests cannot be used as proof for
pgvector ordering, JSONB operators, or migration reversibility. PostgreSQL tests
should stay focused so they do not make every PR wait on a full end-to-end
database suite.

## Revisit When

Revisit this decision if SQLite compatibility code starts distorting production
logic, if PostgreSQL-specific regressions escape targeted CI, or if test
runtime allows moving more integration coverage onto PostgreSQL without slowing
normal contribution flow.

