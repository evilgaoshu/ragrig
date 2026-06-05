from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from ragrig.workflows import engine as workflow_engine
from ragrig.workflows.engine import (
    WorkflowDefinition,
    WorkflowStep,
    WorkflowValidationError,
    _knowledge_base,
    _optional_string_list,
    _report_output,
    _retry_delay_seconds,
    _run_ingest_connector,
    list_workflow_operations,
    run_workflow,
)

pytestmark = pytest.mark.unit


def test_workflow_operations_catalog_exposes_retry_and_dry_run_contracts() -> None:
    operations = {item["operation"]: item for item in list_workflow_operations()}

    assert {
        "ingest.connector",
        "ingest.local",
        "ingest.fileshare",
        "ingest.s3",
        "ingest.database",
        "index.knowledge_base",
        "noop",
    } <= set(operations)
    assert operations["ingest.connector"]["dry_run_supported"] is True
    assert operations["ingest.s3"]["dry_run_supported"] is False
    assert all(item["retry_backoff_supported"] is True for item in operations.values())


def test_workflow_definition_validates_required_fields_and_step_shape() -> None:
    valid_step = WorkflowStep(step_id="noop", operation="noop")

    with pytest.raises(WorkflowValidationError, match="workflow_id is required"):
        WorkflowDefinition(workflow_id="", steps=[valid_step])
    with pytest.raises(WorkflowValidationError, match="at least one step"):
        WorkflowDefinition(workflow_id="empty", steps=[])
    with pytest.raises(WorkflowValidationError, match="step_id is required"):
        WorkflowDefinition(
            workflow_id="bad-step", steps=[WorkflowStep(step_id="", operation="noop")]
        )
    with pytest.raises(WorkflowValidationError, match="duplicate step_id"):
        WorkflowDefinition(workflow_id="dup", steps=[valid_step, valid_step])
    with pytest.raises(WorkflowValidationError, match="unknown dependency"):
        WorkflowDefinition(
            workflow_id="missing-dep",
            steps=[WorkflowStep(step_id="a", operation="noop", depends_on=["missing"])],
        )
    with pytest.raises(WorkflowValidationError, match="max_retries"):
        WorkflowDefinition(
            workflow_id="bad-retry",
            steps=[WorkflowStep(step_id="a", operation="noop", max_retries=-1)],
        )
    with pytest.raises(WorkflowValidationError, match="retry_backoff_seconds"):
        WorkflowDefinition(
            workflow_id="bad-delay",
            steps=[WorkflowStep(step_id="a", operation="noop", retry_backoff_seconds=-1)],
        )
    with pytest.raises(WorkflowValidationError, match="retry_backoff_multiplier"):
        WorkflowDefinition(
            workflow_id="bad-multiplier",
            steps=[WorkflowStep(step_id="a", operation="noop", retry_backoff_multiplier=0.5)],
        )


def test_workflow_failure_skips_all_dependents(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_runner(_session: object, _config: dict[str, Any]) -> tuple[None, dict[str, Any]]:
        raise RuntimeError("boom")

    monkeypatch.setitem(workflow_engine._RUNNERS, "fail", fail_runner)
    workflow = WorkflowDefinition(
        workflow_id="failure-skips-dependents",
        steps=[
            WorkflowStep(step_id="a", operation="fail"),
            WorkflowStep(step_id="b", operation="noop", depends_on=["a"]),
            WorkflowStep(step_id="c", operation="noop", depends_on=["b"]),
        ],
    )

    report = run_workflow(session=object(), definition=workflow)

    assert report.status == "failed"
    assert [step.status for step in report.steps] == ["failed", "skipped", "skipped"]
    assert report.steps[0].error == "boom"
    assert report.steps[1].output == {"blocked_by": ["a"]}
    assert report.steps[2].output == {"blocked_by": ["b"]}
    assert report.as_dict()["steps"][1]["error"] == "dependency_failed"


def test_workflow_continue_on_error_runs_independent_steps_and_blocks_dependents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_runner(_session: object, _config: dict[str, Any]) -> tuple[None, dict[str, Any]]:
        raise RuntimeError("optional source failed")

    monkeypatch.setitem(workflow_engine._RUNNERS, "fail", fail_runner)
    workflow = WorkflowDefinition(
        workflow_id="continue-on-error",
        steps=[
            WorkflowStep(step_id="optional", operation="fail", continue_on_error=True),
            WorkflowStep(step_id="blocked", operation="noop", depends_on=["optional"]),
            WorkflowStep(step_id="independent", operation="noop", config={"ok": True}),
        ],
    )

    report = run_workflow(session=object(), definition=workflow)

    assert report.status == "failed"
    assert [step.status for step in report.steps] == ["failed", "skipped", "success"]
    assert report.steps[1].error == "dependency_failed"
    assert report.steps[2].output == {"config": {"ok": True}}


def test_ingest_connector_dispatches_to_builtin_connector_runners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def make_runner(name: str):
        def runner(_session: object, config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            calls.append((name, config))
            return f"run-{name}", {"runner": name}

        return runner

    monkeypatch.setattr(workflow_engine, "_run_ingest_local", make_runner("local"))
    monkeypatch.setattr(workflow_engine, "_run_ingest_fileshare", make_runner("fileshare"))
    monkeypatch.setattr(workflow_engine, "_run_ingest_s3", make_runner("s3"))
    monkeypatch.setattr(workflow_engine, "_run_ingest_database", make_runner("database"))

    for connector_id, expected in [
        ("source.local", "local"),
        ("source.fileshare", "fileshare"),
        ("source.s3", "s3"),
        ("source.database", "database"),
    ]:
        run_id, output = _run_ingest_connector(
            object(),
            {
                "connector_id": connector_id,
                "knowledge_base": "kb",
                "connector_config": {"path": "/tmp/example"},
            },
        )
        assert run_id == f"run-{expected}"
        assert output == {"runner": expected}

    assert calls == [
        ("local", {"path": "/tmp/example", "knowledge_base": "kb"}),
        ("fileshare", {"path": "/tmp/example", "knowledge_base": "kb"}),
        ("s3", {"path": "/tmp/example", "knowledge_base": "kb"}),
        ("database", {"path": "/tmp/example", "knowledge_base": "kb"}),
    ]


def test_ingest_connector_probes_enterprise_connectors_and_rejects_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def probe(connector_id: str, *, config: dict[str, Any]) -> dict[str, Any]:
        if connector_id == "source.ready":
            return {"status": "ready", "config": config}
        return {"status": "missing_credentials"}

    monkeypatch.setattr(workflow_engine, "probe_enterprise_connector", probe)

    run_id, output = _run_ingest_connector(
        object(),
        {
            "connector_id": "source.ready",
            "knowledge_base_name": "kb",
            "connector_config": {"team": "alpha"},
        },
    )

    assert run_id is None
    assert output == {"connector_probe": {"status": "ready", "config": {"team": "alpha"}}}
    with pytest.raises(WorkflowValidationError, match="missing_credentials"):
        _run_ingest_connector(
            object(),
            {
                "connector_id": "source.missing",
                "knowledge_base": "kb",
                "connector_config": {},
            },
        )


@dataclass
class _Report:
    pipeline_run_id: str
    created: int
    skipped: int


def test_workflow_helper_validation_and_report_output() -> None:
    step = WorkflowStep(
        step_id="retry",
        operation="noop",
        retry_backoff_seconds=0.25,
        retry_backoff_multiplier=4.0,
    )

    assert _knowledge_base({"knowledge_base_name": "kb-alt"}) == "kb-alt"
    assert _optional_string_list(["*.md", 7]) == ["*.md", "7"]
    assert _optional_string_list(None) is None
    assert _report_output(_Report(pipeline_run_id="hidden", created=2, skipped=1)) == {
        "created": 2,
        "skipped": 1,
    }
    assert _retry_delay_seconds(step, 2) == pytest.approx(4.0)
    with pytest.raises(WorkflowValidationError, match="knowledge_base is required"):
        _knowledge_base({})
    with pytest.raises(WorkflowValidationError, match="pattern fields must be lists"):
        _optional_string_list("*.md")
