# RAGRig Database Source Connector Spec

Status: implemented
Date: 2026-05-16

## Scope

`source.database` ingests PostgreSQL and MySQL rows through bounded read-only SQL queries. Each returned row becomes one `Document` plus one `DocumentVersion` when its row snapshot changes.

## Contract

- Supported engines: `postgresql`, `mysql`.
- DSN must be supplied as `env:SOURCE_DATABASE_DSN`; plaintext DSNs are rejected.
- Query SQL must be a single `SELECT` or `WITH` statement. DML/DDL/control statements are rejected during config validation.
- MySQL uses SQLAlchemy plus optional `pymysql`; PostgreSQL uses the project’s core SQLAlchemy/psycopg stack.
- Row identity is derived from configured `document_id_columns` or, if omitted, the query row index. Document URIs use a stable identity hash and never include the DSN.
- `max_rows_per_query` bounds each query. Truncated result sets create a skipped control item.
- `known_document_uris` supplies placeholder delete detection for rows missing from the latest query result.

## Pipeline Mapping

Connector output uses:

- Source kind: `database`
- Source URI: `database://{engine}/{source_name}`
- Document URI: `database://{engine}/{source_name}/{query_name}/{row_identity_hash}`
- Run type: `database_ingest`
- Parser name: `database_row`

Row metadata includes the engine, source name, query name, row identity hash, row snapshot hash, selected metadata columns, result count, and truncation flag. Secret material is omitted from document URIs, metadata, pipeline run snapshots, and error messages.

## Operations

Offline evidence is produced with:

```bash
make database-source-check
```

The check runs PostgreSQL and MySQL paths with a fake database client against an ephemeral SQLite metadata database. It verifies created versions, unchanged-row skip behavior, and DSN redaction.
