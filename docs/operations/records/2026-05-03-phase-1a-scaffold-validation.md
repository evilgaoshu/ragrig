# Phase 1a Scaffold Validation Record

Date: 2026-05-03
Issue: EVI-28

## Local Verification

Successful local commands on the development machine:

```bash
make format
make lint
make test
```

Observed result:

- `ruff format` completed successfully
- `ruff check` returned no findings
- `pytest` passed `2` tests in `tests/test_health.py`

## Local Runtime Blocker

Attempted command:

```bash
cp .env.example .env && docker compose up --build -d
```

Observed failure:

```text
unable to get image 'ragrig-app': failed to connect to the docker API at unix:///Users/yue/.orbstack/run/docker.sock; check if the path is correct and if the daemon is running: dial unix /Users/yue/.orbstack/run/docker.sock: connect: no such file or directory
```

Impact:

- local `docker compose up` could not be completed on this machine
- local `/health` runtime verification through Compose is blocked by unavailable Docker daemon
- local pgvector extension verification through Compose is blocked for the same reason

Recommended next step:

- rerun `docker compose up --build` on a machine with Docker daemon access enabled
- then verify:

```bash
curl http://localhost:8000/health
docker compose exec db psql -U ragrig -d ragrig -c "SELECT extname FROM pg_extension WHERE extname = 'vector';"
```

## Shared Environment 192.168.3.100 Blocker

Attempted command:

```bash
ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=10 192.168.3.100 'hostname'
```

Observed result:

```text
mff
```

Current interpretation:

- the shared environment is not presently usable from this session with the available access path
- no runtime commands were executed successfully on `192.168.3.100` in this run

Required follow-up once access is available:

```bash
cp .env.example .env
docker compose up --build -d
curl http://localhost:8000/health
docker compose exec db psql -U ragrig -d ragrig -c "SELECT extname FROM pg_extension WHERE extname = 'vector';"
```
