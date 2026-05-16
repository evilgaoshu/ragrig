# Database Source Connectors Read Path

Date: 2026-05-16

## Summary

Implemented `source.database` as a bounded PostgreSQL/MySQL read path:

- Added config validation for env-only DSNs, read-only SQL, unique query names, row identity columns, and row limits.
- Added SQLAlchemy client wiring plus a fake client for deterministic tests and evidence.
- Added row-to-document ingestion with stable database URIs, row snapshot skip behavior, placeholder delete detection, pipeline run items, and secret-redacted errors.
- Wired the connector into plugin discovery, enterprise connector catalog, workflow operations, source validation/save/dry-run/run-ingest helpers, and the Web Console source form.
- Added `make database-source-check` for reproducible offline evidence.

## Evidence

Primary commands:

```bash
make database-source-check
uv run pytest tests/test_database_source.py -q
uv run pytest tests/test_enterprise_workflows.py tests/test_source_mutating_workflows.py -q
make lint
make test
```

Primary artifact:

```text
docs/operations/artifacts/database-source-check.json
```

## Notes

The PostgreSQL path uses the existing SQLAlchemy/psycopg dependency set. The MySQL path is contract-compatible through SQLAlchemy and requires the optional `pymysql` dependency for live execution. The deterministic smoke uses `FakeDatabaseClient`, so CI can validate connector behavior without live database credentials.
