# Qdrant Vector Backend Validation Record

- Date: 2026-05-04
- Feature: Qdrant vector backend and unified vector contract
- PR URL: https://github.com/evilgaoshu/ragrig/pull/14
- Head commit: 8cc85835f3992a3940ea493ef4bdab6d8eee6698

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

Status: validated

Shared-environment validation is complete in this run using `root@192.168.3.100`.

Validated checkout:

- Host: `192.168.3.100`
- User: `root`
- Path: `/root/ragrig-evi38-qdrant`
- App port reserved for this checkout: `18003`
- DB host port: `35440`
- Qdrant host port: `36333`
- Qdrant gRPC port: `36334`

Fixes required before the smoke could pass:

- `docker-compose.yml` referenced `qdrant/qdrant:v1.14.2`, which does not exist on Docker Hub; the image was corrected to `qdrant/qdrant:v1.14.1`
- `QdrantBackend.search()` assumed the SDK exposed `QdrantClient.search()`, but the installed official client exposes `query_points()`; the adapter now supports both client shapes

Commands run:

```bash
docker manifest inspect qdrant/qdrant:v1.14.2
docker manifest inspect qdrant/qdrant:v1.14.1

cat > .env <<'EOF'
APP_NAME=ragrig
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=18003
APP_HOST_PORT=18003
DB_HOST_PORT=35440
QDRANT_HOST_PORT=36333
QDRANT_GRPC_PORT=36334
DATABASE_URL=postgresql://ragrig:ragrig_dev@db:5432/ragrig
VECTOR_BACKEND=qdrant
QDRANT_URL=http://localhost:36333
EOF

/root/.local/bin/uv sync --dev --extra vectorstores
docker compose down --remove-orphans
docker compose --profile qdrant up -d db qdrant
make UV=/root/.local/bin/uv migrate
make UV=/root/.local/bin/uv ingest-local
VECTOR_BACKEND=qdrant make UV=/root/.local/bin/uv index-local
VECTOR_BACKEND=qdrant make UV=/root/.local/bin/uv retrieve-check QUERY="RAGRig Guide"
curl -fsS http://127.0.0.1:36333/collections
docker compose --profile qdrant ps
docker compose exec -T db psql -U ragrig -d ragrig -c "SELECT COUNT(*) AS documents FROM documents; SELECT COUNT(*) AS chunks FROM chunks; SELECT COUNT(*) AS embeddings FROM embeddings;"
```

Observed result:

- `docker compose --profile qdrant up -d db qdrant` succeeded on `192.168.3.100` after correcting the image tag
- `VECTOR_BACKEND=qdrant make index-local` completed without failures and used the live Qdrant container
- `VECTOR_BACKEND=qdrant make retrieve-check QUERY="RAGRig Guide"` returned three real ranked results from `nested/deep.md`, `guide.md`, and `notes.txt`
- `curl http://127.0.0.1:36333/collections` returned a live collection named `ragrig_fixture_local_deterministic_lo_hash_8d_8d_0cbfafa4`
- `docker compose --profile qdrant ps` showed both `db` and `qdrant` containers healthy/running on the reserved host ports
- SQL verification confirmed `documents=5`, `chunks=3`, and `embeddings=3`

Remote operational note:

- `qdrant-client==1.17.1` warns that it is newer than `qdrant/qdrant:v1.14.1`, but live indexing and retrieval both completed successfully in this validation run
