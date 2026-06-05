from __future__ import annotations

from dataclasses import dataclass

from scripts.doctor import DoctorConfig, collect_checks, render_checks


@dataclass
class _Result:
    returncode: int
    stdout: str = ""
    stderr: str = ""


def test_collect_checks_reports_required_tools_port_and_memory() -> None:
    def which(command: str) -> str | None:
        paths = {
            "docker": "/usr/local/bin/docker",
            "uv": "/usr/local/bin/uv",
            "node": "/usr/local/bin/node",
        }
        return paths.get(command)

    def run(command: list[str]) -> _Result:
        versions = {
            ("docker", "--version"): "Docker version 24.0.1, build fixture\n",
            ("uv", "--version"): "uv 0.7.3\n",
            ("node", "--version"): "v22.1.0\n",
        }
        return _Result(returncode=0, stdout=versions[tuple(command)])

    checks = collect_checks(
        DoctorConfig(port=8000, minimum_memory_gb=4.0),
        which=which,
        run=run,
        port_available=lambda port: False,
        total_memory_gb=lambda: 8.0,
    )

    by_name = {check.name: check for check in checks}
    assert by_name["Docker"].status == "ok"
    assert "24.0.1" in by_name["Docker"].detail
    assert by_name["uv"].status == "ok"
    assert by_name["Node.js"].status == "ok"
    assert by_name["Port 8000"].status == "warn"
    assert "already in use" in by_name["Port 8000"].detail
    assert by_name["Memory"].status == "ok"
    assert "8.0 GB" in by_name["Memory"].detail


def test_collect_checks_marks_missing_tools_and_low_memory() -> None:
    checks = collect_checks(
        DoctorConfig(port=18000, minimum_memory_gb=4.0),
        which=lambda command: None,
        run=lambda command: _Result(returncode=127, stderr="not found"),
        port_available=lambda port: True,
        total_memory_gb=lambda: 2.0,
    )

    by_name = {check.name: check for check in checks}
    assert by_name["Docker"].status == "fail"
    assert by_name["uv"].status == "fail"
    assert by_name["Node.js"].status == "fail"
    assert by_name["Port 18000"].status == "ok"
    assert by_name["Memory"].status == "warn"


def test_render_checks_is_plain_text_table() -> None:
    checks = collect_checks(
        DoctorConfig(port=8000, minimum_memory_gb=4.0),
        which=lambda command: "/bin/" + command,
        run=lambda command: _Result(returncode=0, stdout="fixture version\n"),
        port_available=lambda port: True,
        total_memory_gb=lambda: None,
    )

    rendered = render_checks(checks)

    assert "RAGRig doctor" in rendered
    assert "Docker" in rendered
    assert "Port 8000" in rendered
    assert "unknown" in rendered
