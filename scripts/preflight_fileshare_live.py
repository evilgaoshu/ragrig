#!/usr/bin/env python3
"""Preflight checks for fileshare live smoke tests.

Exit codes:
  0 - all checks passed
  1 - one or more blockers found (actionable message printed to stderr)
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load .env early so that port overrides and other env vars are available
# for the rest of the preflight logic.
load_dotenv(dotenv_path=Path(".env"))

_REQUIRED_PORTS = {
    "SMB_HOST_PORT": 1445,
    "WEBDAV_HOST_PORT": 8080,
    "SFTP_HOST_PORT": 2222,
}
_OPTIONAL_SDKS = {
    "smbprotocol": ("SMB live tests", "uv sync --extra fileshare --dev"),
    "paramiko": ("SFTP live tests", "uv sync --extra fileshare --dev"),
    "httpx": ("WebDAV live tests", "uv sync --extra fileshare --dev"),
}


def _run_quiet(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True)


def _docker_available() -> str | None:
    """Return blocker message if docker CLI is missing, else None."""
    result = _run_quiet(["docker", "--version"])
    if result.returncode != 0:
        return (
            "Docker CLI not found. Install Docker or OrbStack: https://docs.docker.com/get-docker/"
        )
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
        if (
            "Cannot connect to the Docker daemon" in stderr
            or "connection refused" in stderr.lower()
        ):
            return f"Docker daemon is not running. Start Docker Desktop or OrbStack. ({stderr})"
        return f"Docker daemon check failed: {stderr}"
    return None


def _get_target_ports() -> dict[str, int]:
    """Return env-aware port mapping for fileshare live services."""
    return {name: int(os.environ.get(name, default)) for name, default in _REQUIRED_PORTS.items()}


def _is_port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) != 0


def _find_free_port(start: int, host: str = "127.0.0.1") -> int:
    port = start
    while port < 65535:
        if _is_port_free(host, port):
            return port
        port += 1
    raise RuntimeError(f"No free port found starting from {start}")


def _ports_free(ports: dict[str, int], *, auto_pick: bool) -> tuple[list[str], dict[str, int]]:
    """Return (blockers, suggested_ports).

    If auto_pick is True and a default port is occupied, attempt to find a
    free alternative instead of emitting a hard blocker.
    """
    blockers: list[str] = []
    suggested: dict[str, int] = {}
    for var_name, port in ports.items():
        if _is_port_free("127.0.0.1", port):
            suggested[var_name] = port
            continue

        if auto_pick:
            try:
                free = _find_free_port(port + 1)
                suggested[var_name] = free
                continue
            except RuntimeError as exc:
                blockers.append(
                    f"Port {port} ({var_name}) is occupied and auto-pick failed: {exc}.\n"
                    f"  Fix: manually free the port or set {var_name}=<free_port> in .env"
                )
        else:
            blockers.append(
                f"Port {port} ({var_name}) is already in use on 127.0.0.1.\n"
                f"  Fix options:\n"
                f"    1) Free the port (e.g. `lsof -ti :{port} | xargs kill -9` on macOS)\n"
                f"    2) Override in .env: {var_name}=<free_port>\n"
                f"    3) Auto-pick: FILESHARE_AUTO_PICK_PORTS=1 make test-live-fileshare"
            )
    return blockers, suggested


def _optional_sdks() -> list[str]:
    """Return list of blocker messages for missing optional SDKs."""
    blockers: list[str] = []
    for module, (purpose, install_cmd) in _OPTIONAL_SDKS.items():
        try:
            __import__(module)
        except ImportError:
            blockers.append(
                f"Optional SDK missing: {module} (needed for {purpose}).\n"
                f"  Install: {install_cmd}\n"
                f"  Fallback: pytest will skip the corresponding protocol tests; "
                f"offline `make test` / `make coverage` still pass."
            )
    return blockers


def _env_file() -> str | None:
    """Return warning message if .env is missing, else None."""
    if not Path(".env").exists():
        return (
            ".env file not found.\n"
            "  Fix: cp .env.example .env  (then edit overrides if needed)\n"
            "  Note: preflight will still proceed; defaults will be used."
        )
    return None


def run_checks() -> dict[str, object]:
    """Run all preflight checks and return a structured result.

    Hard blockers (Docker, Compose, daemon, ports) prevent container startup.
    Optional SDK warnings are reported but do not block if no hard blockers exist.
    """
    checks: dict[str, object] = {}
    hard_blockers: list[str] = []
    warnings: list[str] = []
    suggested_ports: dict[str, int] = {}

    for name, fn in [
        ("docker_cli", _docker_available),
        ("docker_compose", _docker_compose_available),
        ("docker_daemon", _docker_daemon_running),
    ]:
        msg = fn()
        checks[name] = {"ok": msg is None, "blocker": msg}
        if msg:
            hard_blockers.append(msg)

    target_ports = _get_target_ports()
    auto_pick = os.environ.get("FILESHARE_AUTO_PICK_PORTS", "").lower() in ("1", "true", "yes")
    port_blockers, suggested_ports = _ports_free(target_ports, auto_pick=auto_pick)
    checks["ports"] = {
        "ok": not port_blockers,
        "blockers": port_blockers,
        "target_ports": target_ports,
        "suggested_ports": suggested_ports,
    }
    hard_blockers.extend(port_blockers)

    env_msg = _env_file()
    checks["env_file"] = {"ok": env_msg is None, "blocker": env_msg}
    if env_msg:
        warnings.append(env_msg)

    sdk_blockers = _optional_sdks()
    checks["optional_sdks"] = {"ok": not sdk_blockers, "blockers": sdk_blockers}
    warnings.extend(sdk_blockers)

    return {
        "ok": not hard_blockers,
        "hard_blockers": hard_blockers,
        "warnings": warnings,
        "blockers": hard_blockers + warnings,
        "checks": checks,
        "suggested_ports": suggested_ports,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preflight checks for fileshare live smoke tests.")
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
                print(
                    "\nPreflight passed with warnings. "
                    "Containers will start, but some protocol tests may be skipped."
                )

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
