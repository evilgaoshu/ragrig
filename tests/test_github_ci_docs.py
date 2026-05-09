from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


pytestmark = pytest.mark.integration

def test_github_actions_ci_workflow_exists_with_required_checks() -> None:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "ci.yml"

    assert workflow_path.exists(), "expected GitHub Actions CI workflow"

    workflow = workflow_path.read_text(encoding="utf-8")

    assert "name: RAGRig CI" in workflow
    assert "checks:" in workflow
    assert "name: RAGRig CI / checks" in workflow
    assert "db-smoke:" in workflow
    assert "docker-build:" in workflow
    assert "permissions:" in workflow
    assert "concurrency:" in workflow
    assert "pull_request:" in workflow
    assert "push:" in workflow
    assert "branches: [main]" in workflow
    assert 'python-version: ["3.11", "3.12"]' in workflow
    assert "uv sync --dev --frozen" in workflow
    assert "uv run ruff format --check ." in workflow
    assert "make lint" in workflow
    assert "make test-fast" in workflow
    assert "make coverage" in workflow
    assert "make web-check" in workflow


def test_github_ci_spec_exists_and_documents_required_scope() -> None:
    spec_path = REPO_ROOT / "docs" / "specs" / "ragrig-github-ci-checks-spec.md"

    assert spec_path.exists(), "expected GitHub CI spec document"

    spec = spec_path.read_text(encoding="utf-8")

    assert "# RAGRig GitHub CI Checks Spec" in spec
    assert "Python 3.11 and 3.12 matrix" in spec
    assert "uv sync --dev --frozen" in spec
    assert "uv run ruff format --check ." in spec
    assert "uv run ruff check ." in spec
    assert "make test" in spec
    assert "make coverage" in spec
    assert "make web-check" in spec
    assert "192.168.3.100" in spec
    assert "EVI-35" in spec


def test_readme_documents_github_ci_scope_and_validation_boundary() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "## GitHub CI" in readme
    assert "RAGRig CI" in readme
    assert "3.11` and `3.12" in readme
    assert "make coverage" in readme
    assert "make web-check" in readme
    assert "192.168.3.100" in readme
    assert "branch protection" in readme


def test_docker_compose_uses_existing_qdrant_image_tag() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "image: qdrant/qdrant:v1.14.1" in compose
