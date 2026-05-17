from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import check_required_ci_contexts as check

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_expected_contexts_match_current_workflow_matrix() -> None:
    expected = check.load_expected_contexts(check.DEFAULT_SPEC)
    workflow = check.load_workflow(check.DEFAULT_WORKFLOW)
    actual = check.workflow_contexts(workflow)

    report = check.local_drift_report(expected, actual)

    assert report["status"] == "pass"
    assert report["missing_from_workflow"] == []
    assert report["unexpected_required_matrix_contexts"] == []
    assert "RAGRig CI / detect-changes" in report["non_required_workflow_contexts"]
    assert "RAGRig CI / test (3.12)" in expected
    assert "RAGRig CI / test (3.11)" not in expected


def test_workflow_contexts_expand_python_matrix_without_reintroducing_311() -> None:
    workflow = check.load_workflow(check.DEFAULT_WORKFLOW)

    assert workflow["jobs"]["test"]["strategy"]["matrix"]["python-version"] == ["3.12"]
    contexts = check.workflow_contexts(workflow)

    assert "RAGRig CI / test (3.12)" in contexts
    assert "RAGRig CI / test (3.11)" not in contexts


def test_local_drift_report_fails_on_extra_test_matrix_context() -> None:
    expected = ["RAGRig CI / test (3.12)"]
    actual = ["RAGRig CI / test (3.12)", "RAGRig CI / test (3.11)"]

    report = check.local_drift_report(expected, actual)

    assert report["status"] == "fail"
    assert report["unexpected_required_matrix_contexts"] == ["RAGRig CI / test (3.11)"]


def test_local_drift_report_allows_non_required_workflow_contexts() -> None:
    expected = ["RAGRig CI / lint", "RAGRig CI / test (3.12)"]
    actual = [
        "RAGRig CI / lint",
        "RAGRig CI / test (3.12)",
        "RAGRig CI / detect-changes",
    ]

    report = check.local_drift_report(expected, actual)

    assert report["status"] == "pass"
    assert report["non_required_workflow_contexts"] == ["RAGRig CI / detect-changes"]


def test_remote_drift_report_requires_exact_branch_protection_match() -> None:
    expected = ["RAGRig CI / lint", "RAGRig CI / test (3.12)"]
    remote = ["RAGRig CI / lint", "RAGRig CI / test (3.11)"]

    report = check.remote_drift_report(expected, remote)

    assert report["status"] == "fail"
    assert report["missing_from_branch_protection"] == ["RAGRig CI / test (3.12)"]
    assert report["unexpected_branch_protection_contexts"] == ["RAGRig CI / test (3.11)"]


def test_fetch_remote_required_contexts_degrades_when_gh_api_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="HTTP 403")

    monkeypatch.setattr(check.subprocess, "run", fake_run)

    status, detail = check.fetch_remote_required_contexts()

    assert status == "degraded"
    assert detail == "HTTP 403"


def test_cli_json_report_is_permission_free_by_default() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "scripts.check_required_ci_contexts", "--json"],
        capture_output=True,
        check=False,
        cwd=REPO_ROOT,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["status"] == "pass"
    assert "branch_protection" not in report
