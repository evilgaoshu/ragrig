from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_supports_local_pilot_runtime() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY alembic.ini" in dockerfile
    assert "COPY alembic ./alembic" in dockerfile
    assert "COPY scripts ./scripts" in dockerfile
    assert "RAGRIG_AUTO_MIGRATE" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "/health" in dockerfile
    assert "uv run --no-dev uvicorn" in dockerfile

    entrypoint = (REPO_ROOT / "scripts" / "docker-entrypoint.sh").read_text(encoding="utf-8")
    assert "uv run --no-dev alembic upgrade head" in entrypoint


def test_compose_app_is_ready_for_pilot_without_bundled_models() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    app = compose["services"]["app"]

    assert app["build"] == "."
    assert app["environment"]["DATABASE_URL"] == (
        "${RAGRIG_DOCKER_DATABASE_URL:-postgresql://ragrig:ragrig_dev@db:5432/ragrig}"
    )
    assert app["environment"]["DB_RUNTIME_HOST"] == "${RAGRIG_DOCKER_DB_RUNTIME_HOST:-db}"
    assert app["environment"]["RAGRIG_AUTO_MIGRATE"] == "${RAGRIG_AUTO_MIGRATE:-1}"
    assert app["environment"]["RAGRIG_ANSWER_BASE_URL"].startswith(
        "${RAGRIG_ANSWER_BASE_URL:-http://host.docker.internal:"
    )
    assert "ollama" not in compose["services"]
    assert "lmstudio" not in compose["services"]
    assert "healthcheck" in app


def test_makefile_exposes_pilot_docker_targets() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "local-pilot-preflight:" in makefile
    assert "pilot-docker-preflight:" in makefile
    assert "pilot-docker-build:" in makefile
    assert "pilot-up:" in makefile
    assert "pilot-down:" in makefile
    assert "pilot-docker-smoke:" in makefile
    assert "scripts.pilot_docker_smoke" in makefile
    assert "--output $(ARTIFACTS_DIR)/pilot-docker-smoke.json" in makefile


def test_readme_documents_ten_minute_local_pilot_demo() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    zh_readme = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

    assert "10-Minute Local Pilot Demo" in readme
    assert "make pilot-docker-preflight" in readme
    assert "examples/local-pilot/company-handbook.md" in readme
    assert "examples/local-pilot/demo-questions.json" in readme
    assert "Model configuration is optional for startup" in readme

    assert "10 分钟本地试点演示" in zh_readme
    assert "make pilot-docker-preflight" in zh_readme
    assert "examples/local-pilot/company-handbook.md" in zh_readme
    assert "examples/local-pilot/demo-questions.json" in zh_readme
    assert "模型配置不影响启动" in zh_readme


class _PilotSmokeHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._write_json({"status": "healthy"})
            return
        if self.path == "/local-pilot/status":
            self._write_json(
                {
                    "upload": {"extensions": [".md", ".txt", ".pdf", ".docx"]},
                    "website_import": {"max_pages": 25},
                    "models": {"local_first": ["model.ollama"]},
                }
            )
            return
        if self.path == "/console":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><title>RAGRig Web Console</title>Local Pilot</html>")
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/local-pilot/answer-smoke":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        self._write_json(
            {
                "provider": payload.get("provider"),
                "status": "healthy",
                "detail": "deterministic answer smoke ok",
            }
        )

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _write_json(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_pilot_docker_smoke_checks_expected_endpoints() -> None:
    from scripts.pilot_docker_smoke import run_smoke

    server = ThreadingHTTPServer(("127.0.0.1", 0), _PilotSmokeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = run_smoke(
            f"http://127.0.0.1:{server.server_address[1]}",
            timeout_seconds=2.0,
            interval_seconds=0.01,
        )
    finally:
        server.shutdown()
        server.server_close()

    assert result["health"]["status"] == "healthy"
    assert result["console"]["contains_local_pilot"] is True
    assert result["local_pilot_status"]["upload"]["extensions"] == [
        ".md",
        ".txt",
        ".pdf",
        ".docx",
    ]
    assert result["answer_smoke"]["status"] == "healthy"
