from __future__ import annotations

import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_github_actions_ci_workflow_exists_with_required_checks() -> None:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "ci.yml"

    assert workflow_path.exists(), "expected GitHub Actions CI workflow"

    workflow = workflow_path.read_text(encoding="utf-8")

    assert "name: RAGRig CI" in workflow
    assert "lint:" in workflow
    assert "test:" in workflow
    assert "coverage:" in workflow
    assert "db-smoke:" in workflow
    assert "smoke:" in workflow
    assert "docker-build:" in workflow
    assert "supply-chain:" in workflow
    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert "branches: [main]" in workflow
    assert 'python-version: ["3.12"]' in workflow
    # CI intentionally runs on every PR — including docs-only — so the
    # required status checks (test/lint/db-smoke/...) can always satisfy
    # the protected-branch policy. The small extra runtime is preferable
    # to maintaining a parallel stub workflow that emits matching check
    # names.
    assert "paths-ignore:" not in workflow
    lint_job = workflow.split("  test:", maxsplit=1)[0]
    assert "uv sync --dev --frozen" not in lint_job
    assert "uvx ruff format --check ." in workflow
    assert "uvx ruff check ." in workflow
    assert "make test-fast" in workflow
    assert "make coverage" in workflow
    assert "make web-check" in workflow
    assert "npm audit --audit-level=high" in workflow
    assert "npm run test:run" in workflow
    assert "make migrate" in workflow
    assert "make db-check" in workflow
    assert "tests/test_pgvector_postgres_ci.py" in workflow
    assert "RAGRIG_PGVECTOR_TEST_DATABASE_URL" in workflow
    assert "docker build -t ragrig:ci ." in workflow
    assert "aquasecurity/trivy-action@a9c7b0f06e461e9d4b4d1711f154ee024b8d7ab8" in workflow
    assert "image-ref: ragrig:ci" in workflow
    assert "scanners: vuln" in workflow
    assert "vuln-type: os,library" in workflow
    assert "make sqlite-warning-check" not in workflow
    assert "-W always::ResourceWarning" not in workflow


def test_nightly_evidence_smoke_workflow_is_scheduled_and_uploads_artifacts() -> None:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "nightly-evidence-smoke.yml"

    assert workflow_path.exists(), "expected nightly evidence smoke workflow"

    workflow = workflow_path.read_text(encoding="utf-8")

    assert "name: Nightly Evidence Smoke" in workflow
    assert "schedule:" in workflow
    assert 'cron: "17 9 * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" in workflow
    assert "uv sync --dev --extra fileshare --frozen" in workflow
    assert "make nightly-evidence-smoke" in workflow
    assert "actions/upload-artifact@v7" in workflow
    assert "docs/operations/artifacts/nightly-evidence-smoke.json" in workflow
    assert "docs/operations/artifacts/pilot-go-no-go-evidence.json" in workflow
    assert "docs/operations/artifacts/fileshare-live-smoke-record.json" in workflow


def test_github_ci_spec_exists_and_documents_required_scope() -> None:
    spec_path = REPO_ROOT / "docs" / "specs" / "evi-60-cicd-optimization.md"

    assert spec_path.exists(), "expected GitHub CI spec document"

    spec = spec_path.read_text(encoding="utf-8")

    assert "# EVI-60 — ragrig CI/CD 优化" in spec
    assert "pytest markers" in spec
    assert "unit" in spec
    assert "integration" in spec
    assert "smoke" in spec
    assert "live" in spec
    assert "slow" in spec
    assert "optional" in spec


def test_docker_compose_uses_existing_qdrant_image_tag() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "image: qdrant/qdrant:v1.14.1" in compose


def test_docker_compose_does_not_ship_default_database_secret_or_publish_db_port() -> None:
    compose_text = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    db_port_override = yaml.safe_load(
        (REPO_ROOT / "docker-compose.db-port.yml").read_text(encoding="utf-8")
    )
    compose = yaml.safe_load(compose_text)
    db = compose["services"]["db"]
    app_env = compose["services"]["app"]["environment"]

    assert "ragrig_dev" not in compose_text
    assert db["environment"]["POSTGRES_PASSWORD"].startswith("${RAGRIG_POSTGRES_PASSWORD:?")
    assert "ports" not in db
    assert "${RAGRIG_POSTGRES_PASSWORD:?" in app_env["DATABASE_URL"]
    assert db_port_override["services"]["db"]["ports"] == [
        "${DB_BIND_HOST:-127.0.0.1}:${DB_HOST_PORT:-5432}:5432"
    ]


def test_production_observability_docs_and_compose_defaults_are_wired() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    optional_services = (REPO_ROOT / "docs" / "operations" / "optional-services.md").read_text(
        encoding="utf-8"
    )

    assert "RAGRIG_METRICS_ENABLED: ${RAGRIG_METRICS_ENABLED:-true}" in compose
    assert (
        "RAGRIG_METRICS_WORKSPACE_LABELS_ENABLED: ${RAGRIG_METRICS_WORKSPACE_LABELS_ENABLED:-false}"
    ) in compose
    assert "RAGRIG_LOG_FILE: ${RAGRIG_LOG_FILE:-}" in compose
    assert "restart: unless-stopped" in compose
    assert "mem_limit: ${RAGRIG_APP_MEM_LIMIT:-2g}" in compose
    assert "cpus: ${RAGRIG_APP_CPUS:-2.0}" in compose
    assert "mem_limit: ${RAGRIG_DB_MEM_LIMIT:-2g}" in compose
    assert "cpus: ${RAGRIG_DB_CPUS:-2.0}" in compose
    assert "http://127.0.0.1:8000/health/ready" in compose
    assert "- ragrig_logs:/app/logs" in compose
    assert "ragrig_logs:" in compose
    assert "RAGRIG_POSTGRES_PASSWORD=replace-with-a-strong-postgres-password" in env_example
    assert "# RAGRIG_AUTH_SECRET_PEPPER=replace-with-a-long-random-secret" in env_example
    assert "# RAGRIG_AUTH_LOGIN_RATE_LIMIT_ENABLED=true" in env_example
    assert "# RAGRIG_DB_POOL_SIZE=10" in env_example
    assert "# RAGRIG_METRICS_WORKSPACE_LABELS_ENABLED=false" in env_example
    assert "# RAGRIG_LOG_FILE=/app/logs/ragrig.jsonl" in env_example
    assert "APP_ENV=production" in optional_services
    assert "RAGRIG_AUTH_SECRET_PEPPER" in optional_services
    assert "RAGRIG_AUTH_LOGIN_MAX_FAILURES=5" in optional_services
    assert "/health/live" in optional_services
    assert "/health/ready" in optional_services
    assert "Prometheus metrics are enabled by default" in optional_services
    assert 'workspace="ws_<sha256-prefix>"' in optional_services
    assert "ragrig_db_pool_checked_out" in optional_services
    assert "RAGRIG_DB_POOL_RECYCLE=1800" in optional_services
    assert "HTTPX client instrumentation" in optional_services
    assert "ragrig_pipeline_runs_total" in optional_services
    assert "ragrig_indexing_embeddings_total" in optional_services
    assert "business spans for retrieval and" in optional_services
    assert "# RAGRIG_TASK_BACKEND=threadpool" in env_example
    assert "RAGRIG_LOG_BACKUP_COUNT=5" in optional_services


def test_coverage_omit_scope_stays_intentional() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    coverage_omit = pyproject["tool"]["coverage"]["run"]["omit"]
    core_coverage_spec = (
        REPO_ROOT / "docs" / "specs" / "ragrig-core-coverage-supply-chain-gates.md"
    ).read_text(encoding="utf-8")
    verification = (REPO_ROOT / "docs" / "operations" / "verification.md").read_text(
        encoding="utf-8"
    )
    verification_text = " ".join(verification.split())

    assert coverage_omit == ["src/ragrig/web_console.py"]
    assert not (REPO_ROOT / "src" / "ragrig" / "cleaners" / "__init__.py").exists()
    assert "`make coverage` includes the FastAPI app entrypoint" in verification_text
    assert "`src/ragrig/web_console.py`: active backend workflow facade" in core_coverage_spec
    assert "src/ragrig/main.py" not in core_coverage_spec.split("### Explicit Omits", maxsplit=1)[1]
    assert "src/ragrig/cleaners" not in core_coverage_spec


def test_runtime_boundary_docs_match_mcp_and_rate_limiter_implementation() -> None:
    architecture = (REPO_ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    optional_services = (REPO_ROOT / "docs" / "operations" / "optional-services.md").read_text(
        encoding="utf-8"
    )
    architecture_text = " ".join(architecture.split())
    optional_services_text = " ".join(optional_services.split())
    ratelimit_source = (REPO_ROOT / "src" / "ragrig" / "ratelimit.py").read_text(encoding="utf-8")
    mcp_source = (REPO_ROOT / "src" / "ragrig" / "routers" / "mcp.py").read_text(encoding="utf-8")

    assert "HTTP JSON-RPC request/response only" in architecture_text
    assert "bidirectional streaming transport" in architecture
    assert '@router.post("/mcp"' in mcp_source
    assert "token bucket" not in ratelimit_source.lower()
    assert "process-local" in architecture
    assert "sliding-window" in architecture
    assert "ARQ/Redis task execution does not share API request limiter state" in architecture_text
    assert "does not make the API request rate limiter shared" in optional_services_text


def test_troubleshooting_runbook_covers_operational_failure_modes() -> None:
    runbook = (REPO_ROOT / "docs" / "operations" / "troubleshooting.md").read_text(encoding="utf-8")

    assert "# RAGRig Troubleshooting Runbook" in runbook
    assert "/health/live" in runbook
    assert "/health/ready" in runbook
    assert "redis.status=error" in runbook
    assert "auth.login.rate_limited" in runbook
    assert "ragrig_db_pool_checked_out" in runbook
    assert "RAGRIG_DB_MAX_OVERFLOW" in runbook
    assert "ragrig_pipeline_runs_total" in runbook
    assert "HTTPX instrumentation" in runbook
    assert "ragrig.retrieval.vector_search" in runbook
    assert "ragrig.indexing.embed" in runbook
    assert "retry_backoff_multiplier" in runbook


def test_contributing_documents_branch_commit_and_frontend_audit_policy() -> None:
    contributing = (REPO_ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")

    assert "## Branch Strategy" in contributing
    assert "feature/<short-topic>" in contributing
    assert "## Commit Messages" in contributing
    assert "npm audit --audit-level=high" in contributing


def test_pull_request_template_uses_canonical_filename_without_generator_footer() -> None:
    template_path = REPO_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"

    assert template_path.exists(), "expected canonical GitHub PR template filename"
    assert not (REPO_ROOT / ".github" / "pull_request_template.md").exists()

    template = template_path.read_text(encoding="utf-8")
    assert "## Summary" in template
    assert "## Test plan" in template
    assert "Generated with" not in template
    assert "Claude Code" not in template


def test_architecture_decision_records_cover_current_core_choices() -> None:
    adr_dir = REPO_ROOT / "docs" / "adr"

    assert (adr_dir / "README.md").exists()
    assert (adr_dir / "template.md").exists()

    records = {
        "0001-vector-backend-strategy.md": ("pgvector", "Qdrant"),
        "0002-database-test-strategy.md": ("SQLite", "PostgreSQL"),
        "0003-application-boundary.md": ("FastAPI monolith", "microservices"),
        "0004-external-dependency-resilience.md": ("circuit breaker", "HTTPX spans"),
    }
    for filename, expected_terms in records.items():
        content = (adr_dir / filename).read_text(encoding="utf-8")
        assert "Status: Accepted" in content
        for term in expected_terms:
            assert term in content


def test_pytest_configuration_does_not_reintroduce_sqlite_resourcewarning_filter() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "scripts.sqlite_warning_check"],
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["has_sqlite_resourcewarning_suppression"] is False


def test_ruff_configuration_excludes_nested_worktrees_from_repo_lint() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert 'extend-exclude = [".worktrees"]' in pyproject
