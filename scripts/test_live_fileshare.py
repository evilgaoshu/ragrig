#!/usr/bin/env python3
"""Orchestrate fileshare live smoke tests with preflight, evidence, and diagnostics.

Produces a local record file (or --print-evidence stdout) that combines:
- preflight results
- compose up / down state
- fixture seed output
- pytest results
- container log tail

Exit codes:
  0 - smoke passed
  1 - preflight blocker (no containers started)
  2 - smoke test failed (containers may still be running unless --teardown)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_RECORD_DIR = _REPO_ROOT / "docs" / "operations" / "artifacts"
_DEFAULT_RECORD = _RECORD_DIR / "fileshare-live-smoke-record.json"
_COMPOSE_FILE = _REPO_ROOT / "docker-compose.yml"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run(
    cmd: list[str],
    *,
    capture: bool = True,
    env: dict[str, str] | None = None,
    check: bool = False,
    timeout: float | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        env=merged_env,
        check=check,
        timeout=timeout,
        cwd=str(cwd) if cwd else None,
    )


def _docker_compose_up() -> dict[str, object]:
    start = _now()
    proc = _run(
        ["docker", "compose", "--profile", "fileshare-live", "up", "-d", "--wait"],
        check=False,
        timeout=120,
        cwd=_REPO_ROOT,
    )
    return {
        "step": "compose_up",
        "started_at": start,
        "finished_at": _now(),
        "cmd": " ".join(proc.args),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _seed_fixtures() -> dict[str, object]:
    start = _now()
    proc = _run(
        [sys.executable, "-m", "scripts.seed_fileshare_live_fixtures"],
        check=False,
        timeout=60,
        cwd=_REPO_ROOT,
    )
    return {
        "step": "seed_fixtures",
        "started_at": start,
        "finished_at": _now(),
        "cmd": " ".join(proc.args),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _run_pytest(verbose: bool = True) -> dict[str, object]:
    start = _now()
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_fileshare_live_smoke.py",
        "-v",
    ]
    if verbose:
        cmd.append("-v")
    proc = _run(
        cmd,
        env={**os.environ, "RAGRIG_FILESHARE_LIVE_SMOKE": "1"},
        check=False,
        timeout=300,
        cwd=_REPO_ROOT,
    )
    return {
        "step": "pytest",
        "started_at": start,
        "finished_at": _now(),
        "cmd": " ".join(proc.args),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def _container_logs_tail(lines: int = 100) -> dict[str, object]:
    start = _now()
    services = ["samba", "webdav", "sftp"]
    logs: dict[str, str] = {}
    for svc in services:
        proc = _run(
            ["docker", "compose", "logs", "--tail", str(lines), svc],
            check=False,
            timeout=30,
            cwd=_REPO_ROOT,
        )
        logs[svc] = proc.stdout + (f"\n[stderr] {proc.stderr}" if proc.stderr else "")
    return {
        "step": "container_logs",
        "started_at": start,
        "finished_at": _now(),
        "logs": logs,
    }


def _docker_compose_down() -> dict[str, object]:
    start = _now()
    proc = _run(
        ["docker", "compose", "--profile", "fileshare-live", "down", "--remove-orphans"],
        check=False,
        timeout=60,
        cwd=_REPO_ROOT,
    )
    return {
        "step": "compose_down",
        "started_at": start,
        "finished_at": _now(),
        "cmd": " ".join(proc.args),
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Orchestrate fileshare live smoke tests with evidence output."
    )
    parser.add_argument(
        "--no-start",
        action="store_true",
        help="Skip docker compose up (assume containers are already running).",
    )
    parser.add_argument(
        "--teardown",
        action="store_true",
        default=True,
        help="Run docker compose down after tests (default: true).",
    )
    parser.add_argument(
        "--no-teardown",
        dest="teardown",
        action="store_false",
        help="Leave containers running after tests.",
    )
    parser.add_argument(
        "--record",
        type=Path,
        default=_DEFAULT_RECORD,
        help="Path to write the JSON evidence record.",
    )
    parser.add_argument(
        "--print-evidence",
        action="store_true",
        help="Print the evidence record to stdout after running.",
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip preflight checks (not recommended).",
    )
    parser.add_argument(
        "--logs-tail",
        type=int,
        default=100,
        help="Number of container log lines to capture (default: 100).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    record: dict[str, object] = {
        "meta": {
            "started_at": _now(),
            "runner": os.environ.get("USER", "unknown"),
            "cwd": str(Path.cwd()),
        },
        "steps": [],
    }

    # Preflight
    if not args.skip_preflight:
        preflight_proc = _run(
            [sys.executable, "-m", "scripts.preflight_fileshare_live", "--json"],
            check=False,
            timeout=30,
            cwd=_REPO_ROOT,
        )
        try:
            preflight = (
                json.loads(preflight_proc.stdout)
                if preflight_proc.stdout
                else {"ok": False, "blockers": ["preflight output empty"]}
            )
        except json.JSONDecodeError:
            preflight = {
                "ok": False,
                "blockers": [f"preflight JSON parse error: {preflight_proc.stdout}"],
            }
        record["preflight"] = preflight
        record["steps"].append({"step": "preflight", **preflight})
        if not preflight["ok"]:
            record["meta"]["finished_at"] = _now()
            record["meta"]["result"] = "blocked"
            _persist(record, args.record)
            if args.print_evidence:
                print(json.dumps(record, indent=2))
            print(
                "\nBLOCKED: preflight checks failed. Containers were NOT started.", file=sys.stderr
            )
            print("Run `python -m scripts.preflight_fileshare_live` for details.", file=sys.stderr)
            return 1

    # Compose up (unless skipped)
    if not args.no_start:
        up_result = _docker_compose_up()
        record["steps"].append(up_result)
        if up_result["returncode"] != 0:
            record["meta"]["finished_at"] = _now()
            record["meta"]["result"] = "compose_up_failed"
            _persist(record, args.record)
            if args.print_evidence:
                print(json.dumps(record, indent=2))
            print("\nFAILED: docker compose up failed.", file=sys.stderr)
            if args.teardown:
                _docker_compose_down()
            return 2

    # Seed fixtures
    seed_result = _seed_fixtures()
    record["steps"].append(seed_result)
    if seed_result["returncode"] != 0:
        record["meta"]["finished_at"] = _now()
        record["meta"]["result"] = "seed_failed"
        _persist(record, args.record)
        if args.print_evidence:
            print(json.dumps(record, indent=2))
        print("\nFAILED: fixture seeding failed.", file=sys.stderr)
        if args.teardown:
            _docker_compose_down()
        return 2

    # Pytest
    pytest_result = _run_pytest()
    record["steps"].append(pytest_result)
    smoke_passed = pytest_result["returncode"] == 0

    # Container logs
    logs_result = _container_logs_tail(args.logs_tail)
    record["steps"].append(logs_result)

    # Teardown
    if args.teardown:
        down_result = _docker_compose_down()
        record["steps"].append(down_result)

    record["meta"]["finished_at"] = _now()
    record["meta"]["result"] = "passed" if smoke_passed else "failed"

    _persist(record, args.record)

    if args.print_evidence:
        print(json.dumps(record, indent=2))

    if smoke_passed:
        print(f"\nPASSED. Evidence written to {args.record}")
        return 0
    else:
        print(f"\nFAILED. Evidence written to {args.record}", file=sys.stderr)
        return 2


def _persist(record: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    raise SystemExit(main())
