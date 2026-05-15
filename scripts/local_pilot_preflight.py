from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from ragrig.main import create_app
from scripts.local_pilot_smoke import _create_file_session_factory

Check = dict[str, str]


def _check(name: str, status: str, detail: str) -> Check:
    return {"name": name, "status": status, "detail": detail}


def _required_check(name: str, probe: Callable[[], str]) -> Check:
    try:
        return _check(name, "pass", probe())
    except Exception as exc:
        return _check(name, "fail", str(exc))


def _check_app_import() -> str:
    if create_app is None:
        raise RuntimeError("FastAPI app factory is unavailable.")
    return "FastAPI app factory imports successfully."


def _check_ephemeral_sqlite_health() -> str:
    with tempfile.TemporaryDirectory(prefix="ragrig-preflight-") as temp_dir:
        database_path = Path(temp_dir) / "preflight.db"
        session_factory, engine = _create_file_session_factory(database_path)
        try:
            client = TestClient(
                create_app(check_database=lambda: None, session_factory=session_factory)
            )
            response = client.get("/health")
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != "healthy":
                raise RuntimeError(f"/health returned {payload!r}")
            return "Ephemeral SQLite app health check is healthy."
        finally:
            engine.dispose()


def _check_artifact_directory_writable(artifacts_dir: Path) -> str:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    probe_path = artifacts_dir / ".ragrig-preflight-write-check"
    probe_path.write_text("ok", encoding="utf-8")
    probe_path.unlink()
    return f"Artifact directory is writable: {artifacts_dir}"


def _check_docker_cli() -> str:
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("docker CLI is required for Docker mode.")
    return f"docker CLI is available: {docker}"


def _check_docker_compose_file() -> str:
    compose = Path("docker-compose.yml")
    dockerfile = Path("Dockerfile")
    missing = [str(path) for path in (compose, dockerfile) if not path.exists()]
    if missing:
        raise RuntimeError(f"missing Docker startup files: {', '.join(missing)}")
    return "Dockerfile and docker-compose.yml are present."


def _optional_answer_model_configuration() -> Check:
    configured = [
        name
        for name in (
            "RAGRIG_ANSWER_BASE_URL",
            "OPENAI_API_KEY",
            "OPENROUTER_API_KEY",
            "GEMINI_API_KEY",
        )
        if os.environ.get(name)
    ]
    if configured:
        return _check(
            "answer_model_configuration",
            "pass",
            f"Optional answer model configuration detected: {', '.join(configured)}.",
        )
    return _check(
        "answer_model_configuration",
        "skip",
        "No answer model configuration detected; this does not block startup.",
    )


def run_preflight(*, mode: str = "local", artifacts_dir: Path | str) -> dict[str, Any]:
    if mode not in {"local", "docker"}:
        raise ValueError("mode must be 'local' or 'docker'")

    artifacts_path = Path(artifacts_dir)
    required_checks = [
        _required_check("app_import", _check_app_import),
        _required_check("ephemeral_sqlite_health", _check_ephemeral_sqlite_health),
        _required_check(
            "artifact_directory_writable",
            lambda: _check_artifact_directory_writable(artifacts_path),
        ),
    ]
    if mode == "docker":
        required_checks.extend(
            [
                _required_check("docker_cli", _check_docker_cli),
                _required_check("docker_startup_files", _check_docker_compose_file),
            ]
        )

    optional_checks = [_optional_answer_model_configuration()]
    status = "pass" if all(check["status"] == "pass" for check in required_checks) else "fail"
    return {
        "status": status,
        "mode": mode,
        "required_checks": required_checks,
        "optional_checks": optional_checks,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run minimal Local Pilot startup preflight checks."
    )
    parser.add_argument(
        "--mode",
        choices=["local", "docker"],
        default="local",
        help="Use 'docker' to include Docker CLI and compose file checks.",
    )
    parser.add_argument(
        "--artifacts-dir",
        type=Path,
        default=Path("docs/operations/artifacts"),
        help="Directory used for preflight output and write checks.",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = run_preflight(mode=args.mode, artifacts_dir=args.artifacts_dir)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
