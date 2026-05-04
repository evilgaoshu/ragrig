# Qdrant Vector Backend Validation Record

- Date: 2026-05-04
- Feature: Qdrant vector backend and unified vector contract
- PR URL: not created yet
- Head commit: not committed yet

## Local Verification

Commands run locally:

```bash
make format
make lint
make test
make coverage
```

Result summary:

- `make format`: passed
- `make lint`: passed
- `make test`: passed, 90 tests
- `make coverage`: passed, 100% total coverage

Optional dependency verification:

- default core path works without `qdrant-client`
- `tests/test_import_guard.py` keeps `qdrant_client` out of top-level core imports
- `tests/test_vectorstore.py` covers degraded health and clear error behavior when the optional SDK is not installed

## Runtime Notes

- Default backend remains `VECTOR_BACKEND=pgvector`
- Explicit Qdrant path is enabled with `VECTOR_BACKEND=qdrant`
- Optional local Qdrant startup path:

```bash
docker compose --profile qdrant up -d qdrant
uv sync --extra vectorstores
VECTOR_BACKEND=qdrant make index-local
VECTOR_BACKEND=qdrant make retrieve-check QUERY="RAGRig Guide"
```

## 192.168.3.100 Shared Environment

Status: blocker

Reason:

- shared environment verification was not completed in this workspace session
- no verified connectivity, Docker runtime access, or repo deployment flow to `192.168.3.100` was established here

Commands not run on `192.168.3.100`:

```bash
docker compose --profile qdrant up -d qdrant
uv sync --extra vectorstores
VECTOR_BACKEND=qdrant make index-local
VECTOR_BACKEND=qdrant make retrieve-check QUERY="RAGRig Guide"
```

Risk:

- local automated checks are green, but shared-host live Qdrant smoke remains unverified

Next step:

- run the commands above on `192.168.3.100`
- record container health, retrieval result summary, and any environment-specific path issues in this file or the PR
