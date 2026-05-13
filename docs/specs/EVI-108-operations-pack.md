# EVI-108: Deployment Backup Restore Upgrade Operations Pack (Phase 4)

## Goal

Build an integrated operations pack for Docker Compose deployment, backup, restore,
and upgrade workflows targeting local / shared-lab environments.  Every workflow
must be documented, executable via `make`, and produce a verifiable output
artifact.

## Hard Requirements

### Verification gates

- `make lint`, `make test`, `make coverage`, `make web-check` all pass.

### Versioned SPEC document (this file)

Documents:
- Backup object inventory
- Restore sequence
- Pre/post upgrade validation
- Failure / rollback boundaries
- Secret / config redaction rules
- Artifact structure

### Executable smoke workflows

- **deploy** – Docker Compose boot, health endpoint polling, Alembic migration
- **backup** – pg_dump (PostgreSQL metadata), config/artifact tarball, vector backend
  configuration snapshot
- **restore** – pg_restore, config tarball extraction, vector backend reconfiguration
- **upgrade** – Alembic migration step, vector backend compatibility check, post-upgrade
  health verification

### Make targets

- `make ops-backup-smoke` – runs backup, writes JSON/Markdown summary to
  `docs/operations/artifacts/ops-backup-summary.json`
- `make ops-restore-smoke` – runs restore from latest backup, writes
  `docs/operations/artifacts/ops-restore-summary.json`
- `make ops-upgrade-smoke` – runs upgrade simulation, writes
  `docs/operations/artifacts/ops-upgrade-summary.json`
- `make ops-deploy-smoke` – runs deploy check, writes
  `docs/operations/artifacts/ops-deploy-summary.json`

### Summary output format

Each summary JSON includes:
- `snapshot_id` – unique backup/operation timestamp
- `schema_revision` – Alembic revision at time of operation
- `operation_status` – `success` | `failure` | `degraded`
- `verification_checks` – list of check results
- `report_path` – path to the summary artifact

### Verification after restore

Restore must verify:
- Health endpoint returns `healthy`
- Alembic revision matches expected head
- KB / source / document counts match pre-backup snapshot
- Corrupt or missing backup results in explicit `failure` status (never silent success)

### Console / Ops diagnostics page

- Display latest backup / restore / upgrade summary
- Display degraded state when artifacts missing or corrupt
- **Never** display plaintext DSN, token, API key, or object storage secret

## Out of Scope

- Production-grade HA
- Managed cloud backup services
- Automatic blue-green deployment
- Real external object storage integration

## Backup Object Inventory

| Object | Backup Method | Location |
|--------|--------------|----------|
| PostgreSQL metadata (tables, embeddings) | `pg_dump --format=custom` | `{backup_dir}/postgres/ragrig_{timestamp}.dump` |
| Vector backend config (Qdrant) | JSON snapshot via REST API | `{backup_dir}/vector/` |
| Application config (.env) | File copy | `{backup_dir}/config/` |
| Operations artifacts | Tarball | `{backup_dir}/artifacts/` |

## Restore Sequence

1. Stop application containers (`docker compose down app`)
2. Restore `.env` from config backup
3. Restore PostgreSQL via `pg_restore --clean --if-exists`
4. Run Alembic migrations to head
5. Restore vector backend config (Qdrant collections)
6. Verify health, schema revision, entity counts
7. Restart application containers

## Upgrade Validation

### Pre-upgrade checks
- Current Alembic revision recorded
- Health endpoint reachable
- Vector backend healthy

### Post-upgrade checks
- Alembic revision advanced to expected head
- Health endpoint healthy
- KB / source / document counts unchanged
- Vector backend still healthy

## Failure / Rollback Boundaries

| Failure Point | Action |
|---------------|--------|
| Pre-upgrade health check fails | Abort – do not proceed |
| Database restore fails | Restore from backup tarball; exit 1 |
| Migration conflicts | `alembic downgrade -1`; restore from backup; exit 1 |
| Vector backend incompatible | Log warning; continue degraded |
| Corrupt/missing backup | Exit 1 with explicit message |

## Secret / Config Redaction

The following fields are **never** written to console output, diagnostics pages,
or summary artifacts:
- `dsn`, `password`, `api_key`, `access_key`, `secret`, `token`, `credential`,
  `private_key`, `session_token`, `service_account`
- Any string containing patterns: `sk-live-`, `sk-proj-`, `sk-ant-`, `ghp_`,
  `Bearer `, `PRIVATE KEY-----`

Redaction is applied recursively through all dict/list nesting levels.
A runtime assertion (`_assert_console_no_secrets`) panics if any forbidden
fragment is detected in output.

## Artifact Structure

```
docs/operations/artifacts/
  ops-backup-summary.{json,md}
  ops-restore-summary.{json,md}
  ops-upgrade-summary.{json,md}
  ops-deploy-summary.{json,md}
```

Each artifact follows the schema:

```json
{
  "artifact": "ops-backup-summary",
  "version": "1.0.0",
  "generated_at": "2026-05-13T00:00:00Z",
  "snapshot_id": "20260513T000000Z",
  "schema_revision": "abc123_def456",
  "operation_status": "success",
  "verification_checks": [
    {"name": "health", "status": "pass", "detail": null}
  ],
  "report_path": "docs/operations/artifacts/ops-backup-summary.json"
}
```

## Shared Lab Run Record Template

### Runtime-validated commit
```markdown
## Ops Smoke Results
- **Commit**: `<sha>`
- **Date**: `<date>`
- **Operator**: `<name>`

### Commands Executed
```
make ops-deploy-smoke
make ops-backup-smoke
make ops-restore-smoke
make ops-upgrade-smoke
```

### Results
- ops-deploy-smoke: success/failure/degraded
- ops-backup-smoke: success/failure/degraded
- ops-restore-smoke: success/failure/degraded
- ops-upgrade-smoke: success/failure/degraded

### Artifacts
- `docs/operations/artifacts/ops-deploy-summary.json`
- `docs/operations/artifacts/ops-backup-summary.json`
- `docs/operations/artifacts/ops-restore-summary.json`
- `docs/operations/artifacts/ops-upgrade-summary.json`
```

### Docs-only evidence commit
Same as above but with `# Docs-only evidence` header – no runtime results.
