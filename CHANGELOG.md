# Changelog

All notable changes to this project will be documented in this file.

This project follows the spirit of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and uses calendar-dated entries until a formal release cadence is established.

## Unreleased

### Added

- Rotating file logging configuration for production deployments.
- Structured authentication and rate-limiting event logs.
- Service-layer modules for authentication and knowledge-base route workflows.
- Project `CODE_OF_CONDUCT.md`.

### Changed

- PostgreSQL sub-query fan-out retrieval now uses database-side vector ordering and limit.

## 2026-05-30

### Added

- Batch embedding support in the indexing pipeline.
- API key authentication.
- Multi-stage Docker build with a non-root runtime user.
- Shared pytest helpers in `conftest.py`.
- Vercel Preview deployment scaffolding.

### Changed

- Split FastAPI route handlers into router and service layers.
- Removed obsolete legacy `/console` tests after the React console moved to `/`.
- Avoided loading all pgvector embeddings during primary vector search.
