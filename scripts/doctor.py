from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class DoctorConfig:
    port: int = 8000
    minimum_memory_gb: float = 4.0


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str


Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]
Which = Callable[[str], str | None]
PortAvailable = Callable[[int], bool]
MemoryReader = Callable[[], float | None]


def _run_version(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _version_check(
    *,
    name: str,
    command_name: str,
    version_command: list[str],
    which: Which,
    run: Runner,
) -> Check:
    path = which(command_name)
    if path is None:
        return Check(name=name, status="fail", detail=f"{command_name} was not found on PATH")

    try:
        result = run(version_command)
    except Exception as exc:
        return Check(name=name, status="fail", detail=f"{command_name} check failed: {exc}")

    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        return Check(
            name=name,
            status="fail",
            detail=output or f"{command_name} exited with {result.returncode}",
        )
    return Check(name=name, status="ok", detail=output or f"found at {path}")


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _total_memory_gb() -> float | None:
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        page_count = os.sysconf("SC_PHYS_PAGES")
    except (AttributeError, OSError, ValueError):
        return None
    if page_size <= 0 or page_count <= 0:
        return None
    return round((page_size * page_count) / (1024**3), 1)


def collect_checks(
    config: DoctorConfig,
    *,
    which: Which = shutil.which,
    run: Runner = _run_version,
    port_available: PortAvailable = _port_available,
    total_memory_gb: MemoryReader = _total_memory_gb,
) -> list[Check]:
    checks = [
        _version_check(
            name="Docker",
            command_name="docker",
            version_command=["docker", "--version"],
            which=which,
            run=run,
        ),
        _version_check(
            name="uv",
            command_name="uv",
            version_command=["uv", "--version"],
            which=which,
            run=run,
        ),
        _version_check(
            name="Node.js",
            command_name="node",
            version_command=["node", "--version"],
            which=which,
            run=run,
        ),
    ]

    if port_available(config.port):
        checks.append(Check(name=f"Port {config.port}", status="ok", detail="available"))
    else:
        checks.append(
            Check(
                name=f"Port {config.port}",
                status="warn",
                detail=(
                    f"already in use; set APP_HOST_PORT to another value such as "
                    f"{config.port + 10000}"
                ),
            )
        )

    memory_gb = total_memory_gb()
    if memory_gb is None:
        checks.append(Check(name="Memory", status="unknown", detail="could not detect total RAM"))
    elif memory_gb < config.minimum_memory_gb:
        checks.append(
            Check(
                name="Memory",
                status="warn",
                detail=(
                    f"{memory_gb:.1f} GB detected; {config.minimum_memory_gb:.1f} GB recommended"
                ),
            )
        )
    else:
        checks.append(
            Check(
                name="Memory",
                status="ok",
                detail=f"{memory_gb:.1f} GB detected",
            )
        )

    return checks


def render_checks(checks: Sequence[Check]) -> str:
    name_width = max([len("Check"), *(len(check.name) for check in checks)])
    status_width = max([len("Status"), *(len(check.status) for check in checks)])
    lines = [
        "RAGRig doctor",
        "",
        f"{'Check'.ljust(name_width)}  {'Status'.ljust(status_width)}  Detail",
        f"{'-' * name_width}  {'-' * status_width}  {'-' * 40}",
    ]
    for check in checks:
        lines.append(
            f"{check.name.ljust(name_width)}  {check.status.ljust(status_width)}  {check.detail}"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check local prerequisites for RAGRig.")
    parser.add_argument("--port", type=int, default=8000, help="Host app port to check.")
    parser.add_argument(
        "--minimum-memory-gb",
        type=float,
        default=4.0,
        help="Recommended minimum host memory in GB.",
    )
    args = parser.parse_args(argv)

    checks = collect_checks(DoctorConfig(port=args.port, minimum_memory_gb=args.minimum_memory_gb))
    print(render_checks(checks))
    return 1 if any(check.status == "fail" for check in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
