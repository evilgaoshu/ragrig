#!/usr/bin/env python3
"""Orchestrate fileshare live smoke tests with preflight checks and evidence output."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

REPO_ROOT = Path(__file__).parent.parent.resolve()
EVIDENCE_DIR = REPO_ROOT / "test-evidence"
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "fileshare_live"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"

# Ports used by fileshare-live profile services
FILESHARE_PORTS = {
    "samba": ("SMB", 1445),
    "webdav": ("WebDAV", 8080),
    "sftp": ("SFTP", 2222),
}

OPTIONAL_SDKS = {
    "httpx": "WebDAV tests",
    "smbprotocol": "SMB tests",
    "paramiko": "SFTP tests",
}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _print_block(title: str, body: str, out: TextIO = sys.stdout) -> None:
    print(f"\n{'=' * 60}", file=out)
    print(f"  {title}", file=out)
    print(f"{'=' * 60}", file=out)
    print(body, file=out)


def _run(
    cmd: list[str],
    *,
    check: bool = True,
    capture: bool = True,
    env: dict[str, str] | None = None,
    timeout: int | None = 120,
) -> subprocess.CompletedProcess[str]:
    merged_env = {**os.environ, **(env or {})}
    kwargs: dict[str, object] = {
        "check": check,
        "text": True,
        "env": merged_env,
        "cwd": str(REPO_ROOT),
    }
    if capture:
        kwargs["capture_output"] = True
    if timeout is not None:
        kwargs["timeout"] = timeout
    return subprocess.run(cmd, **kwargs)  # noqa: S603


def _docker_cmd() -> list[str] | None:
    """Return working docker compose command prefix, or None."""
    for cmd in (["docker", "compose"], ["docker-compose"]):
        try:
            _run([*cmd, "version"], check=True, capture=True, timeout=10)
            return cmd
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return None


def _docker_daemon_ok() -> bool:
    try:
        _run(["docker", "info"], check=True, capture=True, timeout=10)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _check_optional_sdk(name: str) -> bool:
    try:
        __import__(name)
        return True
    except ImportError:
        return False


def preflight() -> tuple[list[str], list[str]]:
    """Return (blockers, warnings)."""
    blockers: list[str] = []
    warnings: list[str] = []

    # Docker daemon
    if not _docker_daemon_ok():
        blockers.append(
            "Docker daemon is not running or `docker` CLI is not in PATH. "
            "Install Docker Desktop / OrbStack / Rancher and start the daemon."
        )

    # Docker Compose
    if _docker_cmd() is None and "Docker Compose" not in "\n".join(blockers):
        blockers.append(
            "`docker compose` (or `docker-compose`) is not available. "
            "Ensure Docker Desktop >= 20.10 or install docker-compose-plugin."
        )

    # Compose file exists
    if not COMPOSE_FILE.exists():
        blockers.append(f"docker-compose.yml not found at {COMPOSE_FILE}")

    # Ports
    for service, (proto, port) in FILESHARE_PORTS.items():
        if _port_in_use(port):
            warnings.append(
                f"Port {port} ({service}/{proto}) is already in use. "
                f"Set env var (e.g., {proto.upper()}_HOST_PORT) to avoid conflict."
            )

    # Optional SDKs
    for pkg, purpose in OPTIONAL_SDKS.items():
        if not _check_optional_sdk(pkg):
            warnings.append(
                f"Optional SDK `{pkg}` is not installed ({purpose} will be skipped). "
                f"Install with: uv sync --extra fileshare --dev"
            )

    return blockers, warnings


def _collect_container_logs(docker_cmd: list[str]) -> str:
    lines: list[str] = []
    for service in ("samba", "webdav", "sftp"):
        lines.append(f"\n--- {service} logs (last 50 lines) ---")
        try:
            result = _run(
                [*docker_cmd, "logs", "--tail", "50", service],
                check=False,
                capture=True,
                timeout=15,
            )
            lines.append(result.stdout or "(no stdout)")
            if result.stderr:
                lines.append(result.stderr)
        except Exception as exc:  # noqa: BLE001
            lines.append(f"Error fetching logs: {exc}")
    return "\n".join(lines)


def _run_pytest(evidence_lines: list[str]) -> int:
    """Run pytest and append output to evidence. Returns exit code."""
    evidence_lines.append(f"\n{'=' * 60}")
    evidence_lines.append("  pytest: tests/test_fileshare_live_smoke.py")
    evidence_lines.append(f"{'=' * 60}")

    env = {"RAGRIG_FILESHARE_LIVE_SMOKE": "1"}
    try:
        result = _run(
            ["python", "-m", "pytest", "tests/test_fileshare_live_smoke.py", "-v"],
            check=False,
            capture=True,
            env=env,
            timeout=180,
        )
        evidence_lines.append(result.stdout or "")
        if result.stderr:
            evidence_lines.append("\n--- stderr ---")
            evidence_lines.append(result.stderr)
        evidence_lines.append(f"\npytest exit code: {result.returncode}")
        return result.returncode
    except subprocess.TimeoutExpired:
        evidence_lines.append("ERROR: pytest timed out after 180s")
        return 1
    except Exception as exc:  # noqa: BLE001
        evidence_lines.append(f"ERROR running pytest: {exc}")
        return 1


def _seed_fixtures(evidence_lines: list[str]) -> int:
    evidence_lines.append(f"\n{'=' * 60}")
    evidence_lines.append("  Seed fixtures")
    evidence_lines.append(f"{'=' * 60}")
    try:
        result = _run(
            ["python", "-m", "scripts.seed_fileshare_live_fixtures"],
            check=False,
            capture=True,
            timeout=60,
        )
        evidence_lines.append(result.stdout or "")
        if result.stderr:
            evidence_lines.append("\n--- stderr ---")
            evidence_lines.append(result.stderr)
        evidence_lines.append(f"\nseed exit code: {result.returncode}")
        return result.returncode
    except subprocess.TimeoutExpired:
        evidence_lines.append("ERROR: seed timed out after 60s")
        return 1
    except Exception as exc:  # noqa: BLE001
        evidence_lines.append(f"ERROR running seed: {exc}")
        return 1


def _compose_up(docker_cmd: list[str], evidence_lines: list[str]) -> int:
    evidence_lines.append(f"\n{'=' * 60}")
    evidence_lines.append("  docker compose up")
    evidence_lines.append(f"{'=' * 60}")
    try:
        result = _run(
            [*docker_cmd, "--profile", "fileshare-live", "up", "-d"],
            check=False,
            capture=True,
            timeout=120,
        )
        evidence_lines.append(result.stdout or "")
        if result.stderr:
            evidence_lines.append("\n--- stderr ---")
            evidence_lines.append(result.stderr)
        evidence_lines.append(f"\ncompose up exit code: {result.returncode}")
        return result.returncode
    except subprocess.TimeoutExpired:
        evidence_lines.append("ERROR: compose up timed out after 120s")
        return 1
    except Exception as exc:  # noqa: BLE001
        evidence_lines.append(f"ERROR running compose up: {exc}")
        return 1


def _compose_down(docker_cmd: list[str]) -> None:
    try:
        _run(
            [*docker_cmd, "--profile", "fileshare-live", "down", "--remove-orphans"],
            check=False,
            capture=True,
            timeout=60,
        )
    except Exception:
        pass


def _write_evidence(content: str) -> Path:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    path = EVIDENCE_DIR / f"fileshare-live-{_timestamp()}.txt"
    path.write_text(content, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Fileshare live smoke test orchestrator")
    parser.add_argument(
        "--print-evidence",
        action="store_true",
        help="Print the full evidence report to stdout after running",
    )
    parser.add_argument(
        "--teardown",
        action="store_true",
        help="Tear down containers after tests (default: leave running)",
    )
    args = parser.parse_args()

    evidence_lines: list[str] = [
        textwrap.dedent(
            f"""\
            RAGRig Fileshare Live Smoke Test Evidence
            ==========================================
            Generated: {_now()}
            Working directory: {REPO_ROOT}
            Command: {" ".join(sys.argv)}
            """
        )
    ]

    # ── Preflight ──
    evidence_lines.append(f"\n{'=' * 60}")
    evidence_lines.append("  Preflight checks")
    evidence_lines.append(f"{'=' * 60}")

    blockers, warnings = preflight()

    for w in warnings:
        evidence_lines.append(f"[WARNING] {w}")
        print(f"[WARNING] {w}", file=sys.stderr)

    if blockers:
        evidence_lines.append("")
        for b in blockers:
            evidence_lines.append(f"[BLOCKER] {b}")
        evidence_lines.append("")
        evidence_lines.append("BLOCKED: fileshare live smoke tests cannot run.")
        evidence_lines.append(
            "Action: resolve the blockers above and re-run `make test-live-fileshare`."
        )

        report = "\n".join(evidence_lines)
        path = _write_evidence(report)

        print("\n" + "=" * 60, file=sys.stderr)
        print("  FILESHARE LIVE SMOKE — BLOCKED", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        for b in blockers:
            print(f"\n[BLOCKER] {b}", file=sys.stderr)
        print(f"\nEvidence written to: {path}", file=sys.stderr)

        if args.print_evidence:
            print("\n" + report)

        return 0

    evidence_lines.append("Preflight passed. No blockers found.")
    if not warnings:
        evidence_lines.append("No warnings.")

    # Ensure .env exists so docker compose doesn't fail on the app service env_file
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        env_file.write_text("# Auto-created by test_live_fileshare.py\n", encoding="utf-8")
        evidence_lines.append(
            f"\n[INFO] Created empty {env_file} (required by docker-compose.yml)."
        )

    # ── Orchestrate ──
    docker_cmd = _docker_cmd()
    assert docker_cmd is not None  # guarded by preflight

    exit_code = 0
    try:
        # 1. Compose up
        if _compose_up(docker_cmd, evidence_lines) != 0:
            exit_code = 1

        # 2. Seed fixtures
        if exit_code == 0 and _seed_fixtures(evidence_lines) != 0:
            exit_code = 1

        # 3. Pytest
        if exit_code == 0:
            exit_code = _run_pytest(evidence_lines)
        else:
            evidence_lines.append("\n[SKIP] pytest skipped because earlier step failed.")

        # 4. Container logs
        evidence_lines.append(f"\n{'=' * 60}")
        evidence_lines.append("  Container log tail")
        evidence_lines.append(f"{'=' * 60}")
        evidence_lines.append(_collect_container_logs(docker_cmd))

    finally:
        if args.teardown:
            _compose_down(docker_cmd)
            evidence_lines.append("\n[TEARDOWN] Containers stopped and removed.")
        else:
            evidence_lines.append(
                "\n[INFO] Containers left running. Run `make fileshare-live-down` to tear down."
            )

    # ── Evidence output ──
    evidence_lines.append(f"\n{'=' * 60}")
    evidence_lines.append("  Summary")
    evidence_lines.append(f"{'=' * 60}")
    evidence_lines.append(f"Overall exit code: {exit_code}")
    evidence_lines.append(f"Timestamp: {_now()}")

    report = "\n".join(evidence_lines)
    path = _write_evidence(report)

    print(f"\nEvidence written to: {path}")
    if args.print_evidence:
        print("\n" + report)

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
