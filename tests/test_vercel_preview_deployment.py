from __future__ import annotations

import importlib
import json
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_vercel_json_routes_all_requests_to_fastapi_function() -> None:
    config_path = REPO_ROOT / "vercel.json"

    config = json.loads(config_path.read_text(encoding="utf-8"))

    assert config["$schema"] == "https://openapi.vercel.sh/vercel.json"
    assert "npm run build" in config["buildCommand"]
    assert "python -m compileall api src scripts" in config["buildCommand"]
    assert config["rewrites"] == [{"source": "/(.*)", "destination": "/api/index"}]
    assert "functions" not in config


def test_vercel_fastapi_entrypoint_exports_ragrig_app() -> None:
    module = importlib.import_module("api.index")

    assert module.app.title == "RAGRig"


def test_vercel_pyproject_declares_fastapi_entrypoint() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["tool"]["vercel"]["entrypoint"] == "api.index:app"


def test_vercel_preview_runtime_dependencies_are_available_to_python_builder() -> None:
    requirements = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")

    for dependency in (
        "bcrypt",
        "defusedxml",
        "email-validator",
        "fastapi",
        "httpx",
        "prometheus-client",
        "sqlalchemy",
        "psycopg[binary]",
        "pgvector",
        "pydantic-settings",
        "python-multipart",
        "pypdf",
        "python-docx",
    ):
        assert dependency in requirements


def test_requirements_txt_matches_default_pyproject_dependencies() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    expected = sorted(pyproject["project"]["dependencies"])
    requirements = sorted(
        line.strip()
        for line in (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )

    assert requirements == expected


def test_auth_and_observability_sdks_are_optional_extras() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = "\n".join(pyproject["project"]["dependencies"])
    extras = pyproject["project"]["optional-dependencies"]

    for dependency in ("ldap3", "joserfc", "pyotp", "qrcode", "opentelemetry-sdk"):
        assert dependency not in dependencies

    assert "ldap3>=2.9.0,<3.0.0" in extras["ldap"]
    assert "joserfc>=1.0.0,<2.0.0" in extras["oidc"]
    assert "pyotp>=2.9.0,<3.0.0" in extras["mfa"]
    assert "qrcode[pil]>=7.4.0,<9.0.0" in extras["mfa"]
    assert "opentelemetry-sdk>=1.25.0,<2.0.0" in extras["otel"]


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


def test_readmes_link_to_hosted_read_only_demo() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    zh_readme = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")

    for text in (readme, zh_readme):
        assert "https://demo.ragrig.dev/" in text
        assert "demo@ragrig.dev" in text
        assert "ragrig-demo-readonly" in text


def test_vercel_git_integration_is_the_only_production_deployment_path() -> None:
    assert not (REPO_ROOT / ".github" / "workflows" / "vercel-demo-deploy.yml").exists()


def test_vercel_docs_describe_git_managed_deployment_lifecycle() -> None:
    spec = (REPO_ROOT / "docs" / "specs" / "EVI-130-vercel-preview-supabase.md").read_text(
        encoding="utf-8"
    )

    assert "Vercel Git integration" in spec
    assert "`demo.ragrig.dev` is a Production Domain" in spec
    assert "Do not add a second GitHub Actions workflow" in spec


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
        if self.path == "/":
            body = b'<html><title>RAGRig Console</title><div id="root"></div></html>'
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
    assert result["console"]["root_contains_ragrig"] is True
    assert result["local_pilot_status"]["upload"]["extensions"] == [
        ".md",
        ".txt",
        ".pdf",
        ".docx",
    ]
