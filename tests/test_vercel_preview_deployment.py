from __future__ import annotations

import importlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_vercel_json_routes_all_requests_to_fastapi_function() -> None:
    config_path = REPO_ROOT / "vercel.json"

    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert config["$schema"] == "https://openapi.vercel.sh/vercel.json"
    assert config["rewrites"] == [{"source": "/(.*)", "destination": "/api/index"}]
    assert config["functions"]["api/index.py"]["maxDuration"] >= 30
    assert config["functions"]["api/index.py"]["memory"] >= 1024


def test_vercel_fastapi_entrypoint_exports_ragrig_app() -> None:
    module = importlib.import_module("api.index")

    assert module.app.title == "RAGRig"


def test_vercel_preview_runtime_dependencies_are_available_to_python_builder() -> None:
    requirements = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")

    for dependency in (
        "fastapi",
        "sqlalchemy",
        "psycopg[binary]",
        "pgvector",
        "pydantic-settings",
        "python-multipart",
        "pypdf",
        "python-docx",
    ):
        assert dependency in requirements


def test_vercel_preview_docs_describe_supabase_env_and_migration_boundary() -> None:
    spec = (REPO_ROOT / "docs" / "specs" / "EVI-130-vercel-preview-supabase.md").read_text(
        encoding="utf-8"
    )
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    zh_readme = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

    for text in (spec, readme, zh_readme):
        normalized = " ".join(text.split())
        assert "Vercel Preview" in text
        assert "Supabase" in text
        assert "DATABASE_URL" in text
        assert "DB_RUNTIME_HOST" in text
        assert "DB_HOST_PORT" in text
        assert "no model credentials are required for startup" in normalized


def test_makefile_exposes_vercel_preview_smoke() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "vercel-preview-smoke:" in makefile
    assert "scripts.vercel_preview_smoke" in makefile
    assert "VERCEL_PREVIEW_URL" in makefile


class _PreviewSmokeHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/health":
            self._write_json({"status": "healthy"})
            return
        if self.path == "/local-pilot/status":
            self._write_json({"upload": {"extensions": [".md", ".txt", ".pdf", ".docx"]}})
            return
        if self.path == "/console":
            body = b"<html><title>RAGRig Web Console</title>Local Pilot</html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def _write_json(self, payload: dict[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_vercel_preview_smoke_checks_preview_endpoints() -> None:
    from scripts.vercel_preview_smoke import run_smoke

    server = ThreadingHTTPServer(("127.0.0.1", 0), _PreviewSmokeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = run_smoke(
            f"http://127.0.0.1:{server.server_address[1]}",
            timeout_seconds=2.0,
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
