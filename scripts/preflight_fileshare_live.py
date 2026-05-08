#!/usr/bin/env python3
"""Preflight checks for fileshare live smoke tests.

Exit codes:
  0 - all checks passed
  1 - one or more blockers found (actionable message printed to stderr)
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from typing import Iterable

_REQUIRED_PORTS = [1445, 8080, 2222]
_OPTIONAL_SDKS = {
    "smbprotocol": "SMB live client (pip install 'ragrig[fileshare]')",
    "paramiko": "SFTP live client (pip install 'ragrig[fileshare]')",
    "httpx": "WebDAV live client (pip install 'ragrig[fileshare]')",
}


def _run_quiet(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True)


def _docker_available() -> str | None:
    """Return blocker message if docker CLI is missing, else None."""
    result = _run_quiet(["docker", "--version"])
    if result.returncode != 0:
        return "Docker CLI not found. Install Docker or OrbStack: https://docs.docker.com/get-docker/"
    return None


def _docker_compose_available() -> str | None:
    """Return blocker message if docker compose is missing, else None."""
    result = _run_quiet(["docker", "compose", "version"])
    if result.returncode != 0:
        return "Docker Compose plugin not found. Install Docker Compose v2: https://docs.docker.com/compose/install/"
    return None


def _docker_daemon_running() -> str | None:
    """Return blocker message if Docker daemon is unreachable, else None."""
    result = _run_quiet(["docker", "info"])
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "Cannot connect to the Docker daemon" in stderr or "connection refused" in stderr.lower():
            return f"Docker daemon is not running. Start Docker Desktop or OrbStack. ({stderr})"
        return f"Docker daemon check failed: {stderr}"
    return None


def _ports_free(ports: Iterable[int]) -> list[str]:
    """Return list of blocker messages for occupied ports."""
    blockers: list[str] = []
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                blockers.append(
                    f"Port {port} is already in use on 127.0.0.1. "
                    f"Free it or override with env var (SMB_HOST_PORT / WEBDAV_HOST_PORT / SFTP_HOST_PORT)."
                )
    return blockers


def _optional_sdks() -> list[str]:
    """Return list of blocker messages for missing optional SDKs."""
    blockers: list[str] = []
    for module, hint in _OPTIONAL_SDKS.items():
        try:
            __import__(module)
        except ImportError:
            blockers.append(f"Optional SDK missing: {module} ({hint})")
    return blockers


def run_checks() -> dict[str, object]:
    """Run all preflight checks and return a structured result.

    Hard blockers (Docker, Compose, daemon, ports) prevent container startup.
    Optional SDK warnings are reported but do not block if no hard blockers exist.
    """
    checks: dict[str, object] = {}
    hard_blockers: list[str] = []
    warnings: list[str] = []

    for name, fn in [
        ("docker_cli", _docker_available),
        ("docker_compose", _docker_compose_available),
        ("docker_daemon", _docker_daemon_running),
    ]:
        msg = fn()
        checks[name] = {"ok": msg is None, "blocker": msg}
        if msg:
            hard_blockers.append(msg)

    port_blockers = _ports_free(_REQUIRED_PORTS)
    checks["ports"] = {"ok": not port_blockers, "blockers": port_blockers}
    hard_blockers.extend(port_blockers)

    sdk_blockers = _optional_sdks()
    checks["optional_sdks"] = {"ok": not sdk_blockers, "blockers": sdk_blockers}
    warnings.extend(sdk_blockers)

    return {
        "ok": not hard_blockers,
        "hard_blockers": hard_blockers,
        "warnings": warnings,
        "blockers": hard_blockers + warnings,
        "checks": checks,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preflight checks for fileshare live smoke tests."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON instead of human-readable text.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first blocker instead of collecting all.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run_checks()

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        if result["ok"] and not result["warnings"]:
            print("Preflight OK: Docker, Compose, daemon, ports, and optional SDKs are ready.")
        else:
            if result["hard_blockers"]:
                print("Preflight FAILED:", file=sys.stderr)
                for i, b in enumerate(result["hard_blockers"], 1):
                    print(f"  {i}. {b}", file=sys.stderr)
            if result["warnings"]:
                print("Preflight WARNINGS:", file=sys.stderr)
                for i, w in enumerate(result["warnings"], 1):
                    print(f"  {i}. {w}", file=sys.stderr)
            if result["ok"]:
                print("\nPreflight passed with warnings. Containers will start, but some protocol tests may be skipped.")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
