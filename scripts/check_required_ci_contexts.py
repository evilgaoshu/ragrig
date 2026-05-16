from __future__ import annotations

import argparse
import itertools
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DEFAULT_SPEC = REPO_ROOT / "docs" / "specs" / "EVI-140-ci-required-contexts-drift.md"
EXPECTED_START = "<!-- required-ci-contexts:start -->"
EXPECTED_END = "<!-- required-ci-contexts:end -->"
DEFAULT_REMOTE = "repos/evilgaoshu/ragrig/branches/main/protection/required_status_checks"


class ContextCheckError(RuntimeError):
    pass


def load_expected_contexts(spec_path: Path) -> list[str]:
    spec = spec_path.read_text(encoding="utf-8")
    try:
        block = spec.split(EXPECTED_START, maxsplit=1)[1].split(EXPECTED_END, maxsplit=1)[0]
    except IndexError as exc:
        raise ContextCheckError(
            f"{spec_path} must contain {EXPECTED_START} and {EXPECTED_END} markers"
        ) from exc

    lines = [
        line.removeprefix("- ").strip()
        for line in block.splitlines()
        if line.strip().startswith("- ")
    ]
    contexts = [line.strip("`") for line in lines]
    if not contexts:
        raise ContextCheckError(f"{spec_path} does not declare any required CI contexts")
    if len(contexts) != len(set(contexts)):
        raise ContextCheckError(f"{spec_path} declares duplicate required CI contexts")
    return contexts


def load_workflow(path: Path) -> dict[str, Any]:
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(workflow, dict):
        raise ContextCheckError(f"{path} is not a YAML mapping")
    jobs = workflow.get("jobs")
    if not isinstance(jobs, dict):
        raise ContextCheckError(f"{path} does not contain a jobs mapping")
    return workflow


def _matrix_values(matrix: dict[str, Any]) -> list[tuple[str, ...]]:
    axes = {
        key: value
        for key, value in matrix.items()
        if key not in {"include", "exclude"} and isinstance(value, list)
    }
    if not axes:
        return []
    return [tuple(str(value) for value in values) for values in itertools.product(*axes.values())]


def workflow_contexts(workflow: dict[str, Any]) -> list[str]:
    contexts: list[str] = []
    for job_id, job in workflow["jobs"].items():
        if not isinstance(job, dict):
            raise ContextCheckError(f"workflow job {job_id!r} is not a mapping")
        job_name = job.get("name", job_id)
        if not isinstance(job_name, str):
            raise ContextCheckError(f"workflow job {job_id!r} name must be a string")

        strategy = job.get("strategy", {})
        matrix = strategy.get("matrix", {}) if isinstance(strategy, dict) else {}
        values = _matrix_values(matrix) if isinstance(matrix, dict) else []
        if values:
            contexts.extend(f"{job_name} ({', '.join(value_tuple)})" for value_tuple in values)
        else:
            contexts.append(job_name)
    return contexts


def _unexpected_required_matrix_contexts(expected_set: set[str], actual_set: set[str]) -> list[str]:
    return sorted(
        context for context in actual_set - expected_set if context.startswith("RAGRig CI / test (")
    )


def local_drift_report(expected: list[str], actual: list[str]) -> dict[str, Any]:
    expected_set = set(expected)
    actual_set = set(actual)
    missing = sorted(expected_set - actual_set)
    unexpected_matrix = _unexpected_required_matrix_contexts(expected_set, actual_set)
    return {
        "status": "pass" if not missing and not unexpected_matrix else "fail",
        "expected_contexts": expected,
        "workflow_contexts": actual,
        "missing_from_workflow": missing,
        "unexpected_required_matrix_contexts": unexpected_matrix,
        "non_required_workflow_contexts": sorted(
            actual_set - expected_set - set(unexpected_matrix)
        ),
    }


def fetch_remote_required_contexts(resource: str = DEFAULT_REMOTE) -> tuple[str, list[str] | str]:
    command = ["gh", "api", resource, "--jq", ".contexts"]
    result = subprocess.run(command, capture_output=True, check=False, text=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return "degraded", detail or "gh api failed without output"
    try:
        contexts = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return "degraded", f"gh api returned non-JSON contexts: {exc}"
    if not isinstance(contexts, list) or not all(isinstance(item, str) for item in contexts):
        return "degraded", "gh api .contexts response was not a list of strings"
    return "pass", contexts


def remote_drift_report(expected: list[str], remote_contexts: list[str]) -> dict[str, Any]:
    expected_set = set(expected)
    remote_set = set(remote_contexts)
    return {
        "status": "pass" if expected_set == remote_set else "fail",
        "remote_contexts": remote_contexts,
        "missing_from_branch_protection": sorted(expected_set - remote_set),
        "unexpected_branch_protection_contexts": sorted(remote_set - expected_set),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check required GitHub CI contexts against the workflow matrix."
    )
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument(
        "--remote",
        action="store_true",
        help="also compare branch protection via gh api",
    )
    parser.add_argument("--remote-resource", default=DEFAULT_REMOTE)
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        expected = load_expected_contexts(args.spec)
        actual = workflow_contexts(load_workflow(args.workflow))
        report = local_drift_report(expected, actual)
    except ContextCheckError as exc:
        print(f"required CI context check failed: {exc}", file=sys.stderr)
        return 2

    if args.remote:
        remote_status, remote_payload = fetch_remote_required_contexts(args.remote_resource)
        if remote_status == "pass" and isinstance(remote_payload, list):
            remote_report = remote_drift_report(expected, remote_payload)
        else:
            remote_report = {"status": "degraded", "detail": remote_payload}
        report["branch_protection"] = remote_report

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"required CI context workflow check: {report['status']}")
        if report["missing_from_workflow"]:
            print("missing from workflow:")
            for context in report["missing_from_workflow"]:
                print(f"- {context}")
        if report["unexpected_required_matrix_contexts"]:
            print("unexpected required-matrix contexts:")
            for context in report["unexpected_required_matrix_contexts"]:
                print(f"- {context}")
        if report["non_required_workflow_contexts"]:
            print("non-required workflow contexts:")
            for context in report["non_required_workflow_contexts"]:
                print(f"- {context}")
        if args.remote:
            remote_report = report["branch_protection"]
            print(f"branch protection check: {remote_report['status']}")
            if remote_report["status"] == "degraded":
                print(f"branch protection check degraded: {remote_report['detail']}")

    if report["status"] != "pass":
        return 1
    if args.remote and report["branch_protection"]["status"] == "fail":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
