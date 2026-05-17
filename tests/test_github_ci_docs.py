from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

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
    assert "make migrate" in workflow
    assert "make db-check" in workflow
    assert "docker build -t ragrig:ci ." in workflow
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
