from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from scripts.nightly_evidence_smoke import (
    CommandExecution,
    SmokeCommand,
    build_smoke_steps,
    run_nightly_evidence_smoke,
)
from scripts.pilot_evidence_pack import build_pack, write_pack

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]


def _resolve(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _arg(command: SmokeCommand, name: str) -> Path:
    values = list(command.command)
    return _resolve(values[values.index(name) + 1])


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _successful_fake_runner(calls: list[str]):
    def fake_runner(
        command: SmokeCommand, _cwd: Path, _base_env: dict[str, str]
    ) -> CommandExecution:
        calls.append(_command_text(command))
        artifacts_dir = _resolve(command.env.get("ARTIFACTS_DIR", "docs/operations/artifacts"))

        if command.command == ("make", "local-pilot-smoke"):
            _write_json(
                artifacts_dir / "local-pilot-smoke.json",
                {"answer": {"grounding_status": "grounded"}},
            )
        elif command.command == ("make", "pilot-docker-smoke"):
            _write_json(
                artifacts_dir / "pilot-docker-smoke.json",
                {"answer_smoke": {"status": "healthy"}},
            )
        elif command.command == ("make", "test-live-fileshare"):
            _write_json(
                artifacts_dir / "fileshare-live-smoke-record.json",
                {"meta": {"result": "passed"}},
            )
        elif command.command == ("make", "answer-live-smoke"):
            _write_json(artifacts_dir / "answer-live-smoke.json", {"status": "skip"})
        elif command.command == ("make", "pipeline-dag-smoke"):
            _write_json(
                artifacts_dir / "pipeline-dag-smoke.json",
                {"meta": {"result": "completed"}},
            )
        elif command.command == ("make", "ops-backup-smoke"):
            _write_json(
                artifacts_dir / "ops-backup-summary.json",
                {"operation_status": "success"},
            )
        elif command.command == ("make", "ops-restore-smoke"):
            _write_json(
                artifacts_dir / "ops-restore-summary.json",
                {"operation_status": "success"},
            )
        elif command.command == ("make", "ops-upgrade-smoke"):
            _write_json(
                artifacts_dir / "ops-upgrade-summary.json",
                {"operation_status": "success"},
            )
        elif command.command[:5] == ("uv", "run", "python", "-m", "scripts.eval_local"):
            _write_json(_arg(command, "--output"), {"status": "completed"})
        elif command.command[:5] == (
            "uv",
            "run",
            "python",
            "-m",
            "scripts.retrieval_benchmark_compare",
        ):
            _write_json(_arg(command, "--output"), {"overall_status": "pass"})
        elif command.command[:5] == (
            "uv",
            "run",
            "python",
            "-m",
            "scripts.pilot_evidence_pack",
        ):
            pack_artifacts_dir = _arg(command, "--artifacts-dir")
            pack = build_pack(artifacts_dir=pack_artifacts_dir)
            write_pack(
                pack,
                json_path=_arg(command, "--json-output"),
                markdown_path=_arg(command, "--markdown-output"),
            )

        return CommandExecution(returncode=0, stdout="ok\n")

    return fake_runner


def _command_text(command: SmokeCommand) -> str:
    return shlex.join(command.command)


def test_default_nightly_steps_cover_evi110_evidence_groups(tmp_path: Path) -> None:
    steps = build_smoke_steps(tmp_path / "artifacts")

    assert [step.id for step in steps] == [
        "local-pilot-acceptance",
        "dockerized-local-pilot",
        "real-source-connector",
        "retrieval-answer-baseline",
        "citation-refusal-diagnostics",
        "inspect-retry-audit",
        "operations-smoke",
    ]
    commands = "\n".join(_command_text(command) for step in steps for command in step.commands)
    assert "make local-pilot-smoke" in commands
    assert "docker compose down --remove-orphans --volumes" in commands
    assert "make pilot-up" in commands
    assert "make pilot-docker-smoke" in commands
    assert "make test-live-fileshare" in commands
    assert "scripts.eval_local" in commands
    assert "scripts.retrieval_benchmark_compare" in commands
    assert "make answer-live-smoke" in commands
    assert "make pipeline-dag-smoke" in commands
    assert "make ops-backup-smoke" in commands
    assert "make ops-restore-smoke" in commands
    assert "make ops-upgrade-smoke" in commands


def test_nightly_evidence_smoke_writes_pass_report_and_runs_cleanup(tmp_path: Path) -> None:
    calls: list[str] = []
    artifacts = tmp_path / "artifacts"
    report = run_nightly_evidence_smoke(
        artifacts_dir=artifacts,
        json_output=artifacts / "nightly-evidence-smoke.json",
        markdown_output=artifacts / "nightly-evidence-smoke.md",
        pack_json=artifacts / "pilot-go-no-go-evidence.json",
        pack_markdown=tmp_path / "EVI-110.md",
        command_runner=_successful_fake_runner(calls),
    )

    assert report["status"] == "pass"
    assert report["evidence_pack"]["decision_status"] == "evidence_recorded"
    assert "docker compose down --remove-orphans --volumes" in calls
    assert (artifacts / "nightly-evidence-smoke.json").exists()
    assert (artifacts / "nightly-evidence-smoke.md").exists()
    persisted = json.loads((artifacts / "nightly-evidence-smoke.json").read_text())
    assert persisted["artifact"] == "nightly-evidence-smoke"


def test_nightly_evidence_smoke_fails_but_continues_to_pack(tmp_path: Path) -> None:
    calls: list[str] = []
    success_runner = _successful_fake_runner(calls)

    def fake_runner(command: SmokeCommand, cwd: Path, base_env: dict[str, str]) -> CommandExecution:
        if command.command == ("make", "pipeline-dag-smoke"):
            calls.append(_command_text(command))
            return CommandExecution(returncode=2, stderr="pipeline failed\n")
        return success_runner(command, cwd, base_env)

    artifacts = tmp_path / "artifacts"
    report = run_nightly_evidence_smoke(
        artifacts_dir=artifacts,
        json_output=artifacts / "nightly-evidence-smoke.json",
        markdown_output=artifacts / "nightly-evidence-smoke.md",
        pack_json=artifacts / "pilot-go-no-go-evidence.json",
        pack_markdown=tmp_path / "EVI-110.md",
        command_runner=fake_runner,
    )

    assert report["status"] == "fail"
    failed_step = next(step for step in report["steps"] if step["id"] == "inspect-retry-audit")
    assert failed_step["status"] == "fail"
    assert "make ops-backup-smoke" in calls
    assert any("scripts.pilot_evidence_pack" in call for call in calls)
    assert report["evidence_pack"]["decision_status"] == "evidence_pending"


def test_nightly_evidence_smoke_clears_stale_artifacts_before_run(tmp_path: Path) -> None:
    calls: list[str] = []
    artifacts = tmp_path / "artifacts"
    _write_json(
        artifacts / "local-pilot-smoke.json",
        {"answer": {"grounding_status": "stale-grounded"}},
    )
    success_runner = _successful_fake_runner(calls)

    def fake_runner(command: SmokeCommand, cwd: Path, base_env: dict[str, str]) -> CommandExecution:
        if command.command == ("make", "local-pilot-smoke"):
            calls.append(_command_text(command))
            return CommandExecution(returncode=2, stderr="auth required\n")
        return success_runner(command, cwd, base_env)

    report = run_nightly_evidence_smoke(
        artifacts_dir=artifacts,
        json_output=artifacts / "nightly-evidence-smoke.json",
        markdown_output=artifacts / "nightly-evidence-smoke.md",
        pack_json=artifacts / "pilot-go-no-go-evidence.json",
        pack_markdown=tmp_path / "EVI-110.md",
        command_runner=fake_runner,
    )

    assert report["status"] == "fail"
    assert not (artifacts / "local-pilot-smoke.json").exists()
    assert report["evidence_pack"]["decision_status"] == "evidence_pending"
    assert "local_pilot_acceptance" in report["evidence_pack"]["pending_requirements"]
