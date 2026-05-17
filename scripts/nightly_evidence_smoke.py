"""Run the automated nightly pilot evidence smoke and publish a report.

The smoke is intentionally repository-local and secret-free. It executes the
EVI-110 evidence commands, refreshes the pilot go/no-go evidence pack, and emits
one CI-friendly JSON/Markdown summary. Command failures do not stop later
evidence groups from running; the final exit code still fails when any required
evidence command or evidence-pack requirement is missing.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_ARTIFACTS_DIR = REPO_ROOT / "docs" / "operations" / "artifacts"
DEFAULT_REPORT_JSON = DEFAULT_ARTIFACTS_DIR / "nightly-evidence-smoke.json"
DEFAULT_REPORT_MARKDOWN = DEFAULT_ARTIFACTS_DIR / "nightly-evidence-smoke.md"
DEFAULT_PACK_JSON = DEFAULT_ARTIFACTS_DIR / "pilot-go-no-go-evidence.json"
DEFAULT_PACK_MARKDOWN = (
    REPO_ROOT / "docs" / "operations" / "records" / "EVI-110-pilot-go-no-go-evidence.md"
)


@dataclass(frozen=True)
class SmokeCommand:
    command: tuple[str, ...]
    timeout_seconds: int
    env: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SmokeStep:
    id: str
    title: str
    commands: tuple[SmokeCommand, ...]
    expected_artifacts: tuple[Path, ...]
    cleanup_commands: tuple[SmokeCommand, ...] = ()


@dataclass(frozen=True)
class CommandExecution:
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


CommandRunner = Callable[[SmokeCommand, Path, Mapping[str, str]], CommandExecution]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _display(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _command_text(command: Iterable[str]) -> str:
    return shlex.join(tuple(command))


def _run_command(
    command: SmokeCommand,
    cwd: Path,
    env: Mapping[str, str],
) -> CommandExecution:
    merged_env = os.environ.copy()
    merged_env.update(env)
    merged_env.update(command.env)
    try:
        completed = subprocess.run(
            command.command,
            cwd=cwd,
            env=merged_env,
            capture_output=True,
            text=True,
            check=False,
            timeout=command.timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return CommandExecution(
            returncode=124,
            stdout=stdout,
            stderr=stderr,
            timed_out=True,
        )
    return CommandExecution(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def build_smoke_steps(artifacts_dir: Path) -> tuple[SmokeStep, ...]:
    artifacts_dir = artifacts_dir.resolve()
    artifact_env = {"ARTIFACTS_DIR": _display(artifacts_dir)}
    compose_project = os.environ.get("COMPOSE_PROJECT_NAME", "ragrig-nightly-evidence")
    db_host_port = os.environ.get("DB_HOST_PORT", "15433")
    pilot_docker_env = {
        **artifact_env,
        "APP_HOST_PORT": os.environ.get("APP_HOST_PORT", "18000"),
        "DB_HOST_PORT": db_host_port,
        "PILOT_BASE_URL": os.environ.get("PILOT_BASE_URL", "http://127.0.0.1:18000"),
        "COMPOSE_PROJECT_NAME": compose_project,
    }
    fileshare_env = {
        **artifact_env,
        "FILESHARE_AUTO_PICK_PORTS": os.environ.get("FILESHARE_AUTO_PICK_PORTS", "1"),
        "COMPOSE_PROJECT_NAME": compose_project,
    }
    operations_env = {
        **pilot_docker_env,
        "DATABASE_URL": os.environ.get(
            "NIGHTLY_EVIDENCE_DATABASE_URL",
            f"postgresql://ragrig:ragrig_dev@localhost:{db_host_port}/ragrig",
        ),
        "OPS_BACKUP_DIR": os.environ.get("OPS_BACKUP_DIR", "backups/nightly-evidence-smoke"),
    }

    return (
        SmokeStep(
            id="local-pilot-acceptance",
            title="Local Pilot upload, retrieval, and grounded answer acceptance",
            commands=(SmokeCommand(("make", "local-pilot-smoke"), 180, artifact_env),),
            expected_artifacts=(artifacts_dir / "local-pilot-smoke.json",),
        ),
        SmokeStep(
            id="dockerized-local-pilot",
            title="Dockerized Local Pilot app and database smoke",
            commands=(
                SmokeCommand(
                    ("docker", "compose", "down", "--remove-orphans", "--volumes"),
                    180,
                    pilot_docker_env,
                ),
                SmokeCommand(("make", "pilot-up"), 420, pilot_docker_env),
                SmokeCommand(("make", "pilot-docker-smoke"), 180, pilot_docker_env),
            ),
            expected_artifacts=(artifacts_dir / "pilot-docker-smoke.json",),
        ),
        SmokeStep(
            id="real-source-connector",
            title="Equivalent real-source connector path",
            commands=(SmokeCommand(("make", "test-live-fileshare"), 720, fileshare_env),),
            expected_artifacts=(artifacts_dir / "fileshare-live-smoke-record.json",),
        ),
        SmokeStep(
            id="retrieval-answer-baseline",
            title="Retrieval and answer quality baseline",
            commands=(
                SmokeCommand(
                    (
                        "uv",
                        "run",
                        "python",
                        "-m",
                        "scripts.eval_local",
                        "--ephemeral-sqlite",
                        "--output",
                        _display(artifacts_dir / "pilot-eval-local.json"),
                    ),
                    240,
                    artifact_env,
                ),
                SmokeCommand(
                    (
                        "uv",
                        "run",
                        "python",
                        "-m",
                        "scripts.retrieval_benchmark_compare",
                        "--pretty",
                        "--latency-threshold-pct",
                        "500",
                        "--output",
                        _display(artifacts_dir / "pilot-retrieval-benchmark-compare.json"),
                    ),
                    360,
                    artifact_env,
                ),
            ),
            expected_artifacts=(
                artifacts_dir / "pilot-eval-local.json",
                artifacts_dir / "pilot-retrieval-benchmark-compare.json",
            ),
        ),
        SmokeStep(
            id="citation-refusal-diagnostics",
            title="Citation, refusal, and degraded answer diagnostics",
            commands=(SmokeCommand(("make", "answer-live-smoke"), 90, artifact_env),),
            expected_artifacts=(artifacts_dir / "answer-live-smoke.json",),
        ),
        SmokeStep(
            id="inspect-retry-audit",
            title="Failure inspect, retry, and audit trail",
            commands=(SmokeCommand(("make", "pipeline-dag-smoke"), 180, artifact_env),),
            expected_artifacts=(artifacts_dir / "pipeline-dag-smoke.json",),
        ),
        SmokeStep(
            id="operations-smoke",
            title="Backup, restore, and upgrade summary",
            commands=(
                SmokeCommand(("make", "ops-backup-smoke"), 120, operations_env),
                SmokeCommand(("make", "ops-restore-smoke"), 180, operations_env),
                SmokeCommand(("make", "ops-upgrade-smoke"), 180, operations_env),
            ),
            expected_artifacts=(
                artifacts_dir / "ops-backup-summary.json",
                artifacts_dir / "ops-restore-summary.json",
                artifacts_dir / "ops-upgrade-summary.json",
            ),
        ),
    )


def _artifact_status(path: Path) -> dict[str, Any]:
    status: dict[str, Any] = {"path": _display(path), "present": path.exists()}
    if path.exists():
        status["bytes"] = path.stat().st_size
    return status


def _clear_stale_artifacts(paths: Iterable[Path]) -> None:
    for path in paths:
        if path.exists() and path.is_file():
            path.unlink()


def _write_log(log_dir: Path, name: str, content: str) -> str:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / name
    path.write_text(content, encoding="utf-8")
    return _display(path)


def _execute_command(
    *,
    command: SmokeCommand,
    step_id: str,
    index: int,
    log_dir: Path,
    cwd: Path,
    base_env: Mapping[str, str],
    command_runner: CommandRunner,
    cleanup: bool = False,
) -> dict[str, Any]:
    started_at = _now()
    execution = command_runner(command, cwd, base_env)
    finished_at = _now()
    prefix = f"{step_id}-{'cleanup-' if cleanup else ''}{index + 1}"
    stdout_log = _write_log(log_dir, f"{prefix}.stdout.log", execution.stdout)
    stderr_log = _write_log(log_dir, f"{prefix}.stderr.log", execution.stderr)
    return {
        "command": _command_text(command.command),
        "started_at": started_at,
        "finished_at": finished_at,
        "returncode": execution.returncode,
        "timed_out": execution.timed_out,
        "timeout_seconds": command.timeout_seconds,
        "stdout_log": stdout_log,
        "stderr_log": stderr_log,
        "status": "pass" if execution.returncode == 0 else "fail",
    }


def _execute_step(
    *,
    step: SmokeStep,
    log_dir: Path,
    cwd: Path,
    base_env: Mapping[str, str],
    command_runner: CommandRunner,
) -> dict[str, Any]:
    command_results: list[dict[str, Any]] = []
    status = "pass"
    for index, command in enumerate(step.commands):
        result = _execute_command(
            command=command,
            step_id=step.id,
            index=index,
            log_dir=log_dir,
            cwd=cwd,
            base_env=base_env,
            command_runner=command_runner,
        )
        command_results.append(result)
        if result["status"] != "pass":
            status = "fail"
            break

    cleanup_results = [
        _execute_command(
            command=command,
            step_id=step.id,
            index=index,
            log_dir=log_dir,
            cwd=cwd,
            base_env=base_env,
            command_runner=command_runner,
            cleanup=True,
        )
        for index, command in enumerate(step.cleanup_commands)
    ]
    if any(result["status"] != "pass" for result in cleanup_results):
        status = "fail"

    artifacts = [_artifact_status(path) for path in step.expected_artifacts]
    if any(not item["present"] for item in artifacts):
        status = "fail"

    return {
        "id": step.id,
        "title": step.title,
        "status": status,
        "commands": command_results,
        "cleanup_commands": cleanup_results,
        "expected_artifacts": artifacts,
    }


def _run_evidence_pack(
    *,
    artifacts_dir: Path,
    pack_json: Path,
    pack_markdown: Path,
    log_dir: Path,
    cwd: Path,
    base_env: Mapping[str, str],
    command_runner: CommandRunner,
) -> dict[str, Any]:
    command = SmokeCommand(
        (
            "uv",
            "run",
            "python",
            "-m",
            "scripts.pilot_evidence_pack",
            "--pretty",
            "--artifacts-dir",
            _display(artifacts_dir),
            "--json-output",
            _display(pack_json),
            "--markdown-output",
            _display(pack_markdown),
        ),
        90,
        {"ARTIFACTS_DIR": _display(artifacts_dir)},
    )
    result = _execute_command(
        command=command,
        step_id="pilot-evidence-pack",
        index=0,
        log_dir=log_dir,
        cwd=cwd,
        base_env=base_env,
        command_runner=command_runner,
    )

    pack_summary: dict[str, Any] = {
        "command": result,
        "json": _artifact_status(pack_json),
        "markdown": _artifact_status(pack_markdown),
        "decision_status": "missing",
        "pending_requirements": [],
    }
    if pack_json.exists():
        try:
            pack = json.loads(pack_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            pack_summary["decision_status"] = "unreadable"
            pack_summary["error"] = str(exc)
        else:
            pack_summary["decision_status"] = str(pack.get("decision_status", "unknown"))
            requirements = pack.get("requirements", [])
            if isinstance(requirements, list):
                pack_summary["pending_requirements"] = [
                    item.get("id", item.get("title", "unknown"))
                    for item in requirements
                    if isinstance(item, dict) and item.get("evidence_status") != "recorded"
                ]
    return pack_summary


def _run_final_cleanup(
    *,
    artifacts_dir: Path,
    log_dir: Path,
    cwd: Path,
    base_env: Mapping[str, str],
    command_runner: CommandRunner,
) -> list[dict[str, Any]]:
    cleanup_env = {
        "ARTIFACTS_DIR": _display(artifacts_dir),
        "COMPOSE_PROJECT_NAME": os.environ.get("COMPOSE_PROJECT_NAME", "ragrig-nightly-evidence"),
    }
    return [
        _execute_command(
            command=SmokeCommand(
                ("docker", "compose", "down", "--remove-orphans", "--volumes"),
                180,
                cleanup_env,
            ),
            step_id="nightly-cleanup",
            index=0,
            log_dir=log_dir,
            cwd=cwd,
            base_env=base_env,
            command_runner=command_runner,
            cleanup=True,
        )
    ]


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Nightly Evidence Smoke",
        "",
        f"Generated: `{report['generated_at']}`",
        f"Status: `{report['status']}`",
        f"Evidence pack: `{report['evidence_pack']['decision_status']}`",
        "",
        "## Steps",
        "",
        "| Step | Status | Artifacts |",
        "| --- | --- | --- |",
    ]
    for step in report["steps"]:
        artifacts = ", ".join(
            f"`{item['path']}`" if item["present"] else f"`{item['path']}` missing"
            for item in step["expected_artifacts"]
        )
        lines.append(f"| {step['title']} | `{step['status']}` | {artifacts} |")

    pending = report["evidence_pack"].get("pending_requirements", [])
    cleanup_status = "pass"
    if any(item["status"] != "pass" for item in report.get("cleanup", [])):
        cleanup_status = "fail"
    lines.extend(["", "## Evidence Pack", ""])
    if pending:
        lines.append("Pending requirements:")
        lines.extend(f"- `{item}`" for item in pending)
    else:
        lines.append("All evidence-pack requirements are recorded.")
    lines.extend(["", "## Cleanup", "", f"Cleanup status: `{cleanup_status}`"])
    lines.extend(
        [
            "",
            "## Logs",
            "",
            f"Per-command logs live under `{report['log_dir']}`.",
            "",
        ]
    )
    return "\n".join(lines)


def write_report(report: dict[str, Any], *, json_path: Path, markdown_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")


def run_nightly_evidence_smoke(
    *,
    artifacts_dir: Path = DEFAULT_ARTIFACTS_DIR,
    json_output: Path = DEFAULT_REPORT_JSON,
    markdown_output: Path = DEFAULT_REPORT_MARKDOWN,
    pack_json: Path = DEFAULT_PACK_JSON,
    pack_markdown: Path = DEFAULT_PACK_MARKDOWN,
    command_runner: CommandRunner = _run_command,
) -> dict[str, Any]:
    artifacts_dir = artifacts_dir.resolve()
    json_output = json_output.resolve()
    markdown_output = markdown_output.resolve()
    pack_json = pack_json.resolve()
    pack_markdown = pack_markdown.resolve()
    log_dir = artifacts_dir / "nightly-evidence-smoke-logs"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    base_env = {"ARTIFACTS_DIR": _display(artifacts_dir)}
    smoke_steps = build_smoke_steps(artifacts_dir)
    _clear_stale_artifacts(
        [
            *(path for step in smoke_steps for path in step.expected_artifacts),
            json_output,
            markdown_output,
            pack_json,
        ]
    )
    steps = [
        _execute_step(
            step=step,
            log_dir=log_dir,
            cwd=REPO_ROOT,
            base_env=base_env,
            command_runner=command_runner,
        )
        for step in smoke_steps
    ]
    cleanup = _run_final_cleanup(
        artifacts_dir=artifacts_dir,
        log_dir=log_dir,
        cwd=REPO_ROOT,
        base_env=base_env,
        command_runner=command_runner,
    )
    evidence_pack = _run_evidence_pack(
        artifacts_dir=artifacts_dir,
        pack_json=pack_json,
        pack_markdown=pack_markdown,
        log_dir=log_dir,
        cwd=REPO_ROOT,
        base_env=base_env,
        command_runner=command_runner,
    )
    status = "pass"
    if any(step["status"] != "pass" for step in steps):
        status = "fail"
    if any(item["status"] != "pass" for item in cleanup):
        status = "fail"
    if evidence_pack["command"]["status"] != "pass":
        status = "fail"
    if evidence_pack["decision_status"] != "evidence_recorded":
        status = "fail"

    report = {
        "artifact": "nightly-evidence-smoke",
        "version": "1.0.0",
        "generated_at": _now(),
        "status": status,
        "log_dir": _display(log_dir),
        "steps": steps,
        "cleanup": cleanup,
        "evidence_pack": evidence_pack,
    }
    write_report(report, json_path=json_output, markdown_path=markdown_output)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", type=Path, default=DEFAULT_ARTIFACTS_DIR)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_REPORT_JSON)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_REPORT_MARKDOWN)
    parser.add_argument("--pack-json-output", type=Path, default=DEFAULT_PACK_JSON)
    parser.add_argument("--pack-markdown-output", type=Path, default=DEFAULT_PACK_MARKDOWN)
    parser.add_argument("--pretty", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_nightly_evidence_smoke(
        artifacts_dir=args.artifacts_dir,
        json_output=args.json_output,
        markdown_output=args.markdown_output,
        pack_json=args.pack_json_output,
        pack_markdown=args.pack_markdown_output,
    )
    if args.pretty:
        print(json.dumps(report, indent=2, ensure_ascii=True))
    print(f"Nightly evidence smoke report: {_display(args.json_output)}")
    print(f"Nightly evidence smoke summary: {_display(args.markdown_output)}")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
