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

Shared host access is available. The blocker is remote Docker permissions for the `yue` account, not network reachability.

Attempted command:

```bash
ssh -o BatchMode=yes -o StrictHostKeyChecking=no -o ConnectTimeout=10 192.168.3.100 'hostname'
```

Observed result:

```text
mff
```

Follow-up environment checks:

```bash
ssh -o BatchMode=yes -o StrictHostKeyChecking=no 192.168.3.100 'hostname && whoami && pwd && docker version --format "{{.Server.Version}}"'
ssh -o BatchMode=yes -o StrictHostKeyChecking=no 192.168.3.100 'id && groups && ls -l /var/run/docker.sock && systemctl is-active docker || true && sudo -n docker version --format "{{.Server.Version}}"'
ssh -o BatchMode=yes -o StrictHostKeyChecking=no 192.168.3.100 'cd ~/tmp/ragrig-phase1a-check && cp .env.example .env && docker compose up --build -d'
```

Observed result:

```text
mff
yue
/home/yue
permission denied while trying to connect to the docker API at unix:///var/run/docker.sock

uid=1000(yue) gid=1000(yue) groups=1000(yue),4(adm),24(cdrom),27(sudo),30(dip),46(plugdev),101(lxd)
yue adm cdrom sudo dip plugdev lxd
srw-rw---- 1 root docker 0 Apr  7 18:38 /var/run/docker.sock
active
sudo: a password is required

unable to get image 'pgvector/pgvector:pg16': permission denied while trying to connect to the docker API at unix:///var/run/docker.sock
```

Current interpretation:

- `192.168.3.100` is reachable and accepts SSH public key login for `yue`
- Docker daemon is running on the host, but the current user is not in the `docker` group and cannot access `/var/run/docker.sock`
- passwordless sudo is not available in this session, so the agent cannot self-remediate Docker access
- repository checkout on the host succeeded and is at PR #2 head commit `d75b97c518ceac990bad3d2498fdbf618bf2f324`
- runtime verification remains blocked until the owner or environment admin grants Docker socket access, adds `yue` to the `docker` group, or provides an approved sudo path

Required follow-up once access is available:

```bash
cp .env.example .env
docker compose up --build -d
curl http://localhost:8000/health
docker compose exec db psql -U ragrig -d ragrig -c "SELECT extname FROM pg_extension WHERE extname = 'vector';"
```
