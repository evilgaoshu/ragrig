# Fileshare Live Smoke — Port Conflict Noise Reduction & Environment Validation

Date: 2026-05-08
Issue: [EVI-48](mention://issue/1cdd3add-b42a-48f5-851f-48c7d7443786)
Environment: macOS, Docker Desktop / OrbStack

## Changes

1. **Preflight `.env` check** — `scripts/preflight_fileshare_live.py` now checks `.env` existence first. Missing `.env` emits an actionable blocker (`cp .env.example .env`) and stops before port or Docker checks.
2. **Env-aware port detection** — preflight reads `SMB_HOST_PORT`, `WEBDAV_HOST_PORT`, and `SFTP_HOST_PORT` from the environment (with defaults 1445/8080/2222). Blocker messages now include the exact port number, env var name, and three fix options.
3. **Auto-pick free ports** — setting `FILESHARE_AUTO_PICK_PORTS=1` lets preflight scan for the next free port instead of blocking. `scripts/test_live_fileshare.py` exports the auto-picked ports into the environment so Docker Compose and pytest use them consistently.
4. **Enhanced optional SDK messages** — missing `smbprotocol`, `paramiko`, or `httpx` now prints the exact install command (`uv sync --extra fileshare --dev`) and a fallback note that offline `make test` / `make coverage` still pass.
5. **Test env var port binding** — `tests/test_fileshare_live_smoke.py` now reads ports from env vars so auto-picked ports are honored end-to-end.
6. **`.env.example` updated** — added `SMB_HOST_PORT`, `WEBDAV_HOST_PORT`, `SFTP_HOST_PORT` for discoverability.
7. **Documentation updated** — `README.md` and `docs/specs/ragrig-fileshare-source-plugin-spec.md` reflect the new preflight behavior.

## Evidence

### `.env` missing blocker

```bash
$ mv .env .env.bak && make preflight-fileshare-live
Preflight FAILED:
  1. .env file is missing. Create it with:
  cp .env.example .env
Then edit any host ports that conflict with your local environment.
  ...
```

### Port conflict with auto-pick

```bash
$ FILESHARE_AUTO_PICK_PORTS=1 make preflight-fileshare-live --json | jq '.checks.ports.suggested_ports'
{
  "SMB_HOST_PORT": 1446,
  "WEBDAV_HOST_PORT": 8081,
  "SFTP_HOST_PORT": 2223
}
```

### Optional SDK message

```
Optional SDK missing: smbprotocol (needed for SMB live tests).
  Install: uv sync --extra fileshare --dev
  Fallback: pytest will skip the corresponding protocol tests; offline `make test` / `make coverage` still pass.
```

### Regression check

```bash
$ make test
======================== 279 passed, 9 skipped in 3.67s ========================

$ make coverage
Required test coverage of 100.0% reached. Total coverage: 100.00%
```

No regression in `make test` or `make coverage`.

## Notes

- Live smoke remains opt-in and is not added to default CI.
- No new core dependencies were introduced.
- Auto-picked ports are propagated through `os.environ` to the subprocess chain (preflight → orchestrator → docker compose → pytest).
