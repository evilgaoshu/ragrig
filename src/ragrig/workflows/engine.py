from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy.orm import Session

from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.plugins.enterprise import ENTERPRISE_CONNECTORS, probe_enterprise_connector
from ragrig.plugins.sources.database.connector import ingest_database_source
from ragrig.plugins.sources.fileshare.connector import ingest_fileshare_source
from ragrig.plugins.sources.s3.connector import ingest_s3_source


class WorkflowValidationError(ValueError):
    pass


@dataclass(frozen=True)
class WorkflowStep:
    step_id: str
    operation: str
    config: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    max_retries: int = 0
    continue_on_error: bool = False


@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_id: str
    steps: list[WorkflowStep]

    def __post_init__(self) -> None:
        if not self.workflow_id:
            raise WorkflowValidationError("workflow_id is required")
        if not self.steps:
            raise WorkflowValidationError("workflow must contain at least one step")
        _topological_steps(self.steps)


@dataclass(frozen=True)
class WorkflowStepResult:
    step_id: str
    operation: str
    status: str
    attempts: int
    duration_ms: float
    pipeline_run_id: str | None = None
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "operation": self.operation,
            "status": self.status,
            "attempts": self.attempts,
            "duration_ms": self.duration_ms,
            "pipeline_run_id": self.pipeline_run_id,
            "output": self.output,
            "error": self.error,
        }


@dataclass(frozen=True)
class WorkflowRunReport:
    workflow_id: str
    status: str
    dry_run: bool
    steps: list[WorkflowStepResult]

    def as_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "status": self.status,
            "dry_run": self.dry_run,
            "steps": [step.as_dict() for step in self.steps],
        }


def list_workflow_operations() -> list[dict[str, object]]:
    return [
        {
            "operation": "ingest.connector",
            "description": "Validate and dispatch an enterprise source connector.",
            "connector_ids": sorted(ENTERPRISE_CONNECTORS),
            "dry_run_supported": True,
        },
        {
            "operation": "ingest.local",
            "description": "Ingest local Markdown/Text files into a knowledge base.",
            "dry_run_supported": True,
        },
        {
            "operation": "ingest.fileshare",
            "description": "Ingest enterprise fileshare sources through source.fileshare.",
            "dry_run_supported": True,
        },
        {
            "operation": "ingest.s3",
            "description": "Ingest S3-compatible object storage through source.s3.",
            "dry_run_supported": False,
        },
        {
            "operation": "ingest.database",
            "description": "Ingest PostgreSQL/MySQL read-only query rows through source.database.",
            "dry_run_supported": False,
        },
        {
            "operation": "index.knowledge_base",
            "description": "Chunk and embed latest document versions for a knowledge base.",
            "dry_run_supported": True,
        },
        {
            "operation": "noop",
            "description": "No-op step for dependency graph validation.",
            "dry_run_supported": True,
        },
    ]


def run_workflow(
    *,
    session: Session,
    definition: WorkflowDefinition,
    dry_run: bool = False,
) -> WorkflowRunReport:
    steps = _topological_steps(definition.steps)
    for step in steps:
        if step.operation not in _RUNNERS:
            raise WorkflowValidationError(f"unsupported operation: {step.operation}")
    if dry_run:
        return WorkflowRunReport(
            workflow_id=definition.workflow_id,
            status="planned",
            dry_run=True,
            steps=[
                WorkflowStepResult(
                    step_id=step.step_id,
                    operation=step.operation,
                    status="planned",
                    attempts=0,
                    duration_ms=0.0,
                    output={"depends_on": list(step.depends_on)},
                )
                for step in steps
            ],
        )

    results: list[WorkflowStepResult] = []
    failed_steps: set[str] = set()
    for step in steps:
        blocked_by = sorted(dep for dep in step.depends_on if dep in failed_steps)
        if blocked_by:
            failed_steps.add(step.step_id)
            results.append(
                WorkflowStepResult(
                    step_id=step.step_id,
                    operation=step.operation,
                    status="skipped",
                    attempts=0,
                    duration_ms=0.0,
                    output={"blocked_by": blocked_by},
                    error="dependency_failed",
                )
            )
            continue

        result = _run_step(session=session, step=step)
        results.append(result)
        if result.status != "success":
            failed_steps.add(step.step_id)
            if not step.continue_on_error:
                _mark_dependents_skipped(steps, results, failed_steps)
                break

    status = "completed" if all(step.status == "success" for step in results) else "failed"
    return WorkflowRunReport(
        workflow_id=definition.workflow_id,
        status=status,
        dry_run=False,
        steps=results,
    )


def _run_step(*, session: Session, step: WorkflowStep) -> WorkflowStepResult:
    runner = _RUNNERS[step.operation]
    attempts = 0
    started = perf_counter()
    last_error: Exception | None = None
    for attempt in range(step.max_retries + 1):
        attempts = attempt + 1
        try:
            pipeline_run_id, output = runner(session, step.config)
            return WorkflowStepResult(
                step_id=step.step_id,
                operation=step.operation,
                status="success",
                attempts=attempts,
                duration_ms=round((perf_counter() - started) * 1000, 3),
                pipeline_run_id=pipeline_run_id,
                output=output,
            )
        except Exception as exc:  # pragma: no cover - exercised through failure paths
            last_error = exc
    return WorkflowStepResult(
        step_id=step.step_id,
        operation=step.operation,
        status="failed",
        attempts=attempts,
        duration_ms=round((perf_counter() - started) * 1000, 3),
        error=str(last_error) if last_error else "unknown workflow step failure",
    )


def _run_ingest_local(
    session: Session, config: dict[str, Any]
) -> tuple[str | None, dict[str, Any]]:
    knowledge_base = _knowledge_base(config)
    report = ingest_local_directory(
        session=session,
        knowledge_base_name=knowledge_base,
        root_path=Path(str(config["root_path"])),
        include_patterns=_optional_string_list(config.get("include_patterns")),
        exclude_patterns=_optional_string_list(config.get("exclude_patterns")),
        max_file_size_bytes=int(config.get("max_file_size_bytes") or 10 * 1024 * 1024),
    )
    return str(report.pipeline_run_id), _report_output(report)


def _run_ingest_fileshare(
    session: Session, config: dict[str, Any]
) -> tuple[str | None, dict[str, Any]]:
    knowledge_base = _knowledge_base(config)
    connector_config = {key: value for key, value in config.items() if key != "knowledge_base"}
    report = ingest_fileshare_source(
        session=session,
        knowledge_base_name=knowledge_base,
        config=connector_config,
    )
    return str(report.pipeline_run_id), _report_output(report)


def _run_ingest_s3(session: Session, config: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    knowledge_base = _knowledge_base(config)
    connector_config = {key: value for key, value in config.items() if key != "knowledge_base"}
    report = ingest_s3_source(
        session=session,
        knowledge_base_name=knowledge_base,
        config=connector_config,
    )
    return str(report.pipeline_run_id), _report_output(report)


def _run_ingest_database(
    session: Session, config: dict[str, Any]
) -> tuple[str | None, dict[str, Any]]:
    knowledge_base = _knowledge_base(config)
    connector_config = {key: value for key, value in config.items() if key != "knowledge_base"}
    report = ingest_database_source(
        session=session,
        knowledge_base_name=knowledge_base,
        config=connector_config,
    )
    return str(report.pipeline_run_id), _report_output(report)


def _run_index(session: Session, config: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    report = index_knowledge_base(
        session=session,
        knowledge_base_name=_knowledge_base(config),
        chunk_size=int(config.get("chunk_size") or 500),
        chunk_overlap=int(config.get("chunk_overlap") or 50),
        embedding_dimensions=int(config.get("embedding_dimensions") or 8),
    )
    return str(report.pipeline_run_id), _report_output(report)


def _run_ingest_connector(
    session: Session, config: dict[str, Any]
) -> tuple[str | None, dict[str, Any]]:
    connector_id = str(config.get("connector_id") or "")
    connector_config = dict(config.get("connector_config") or {})
    if connector_id == "source.local":
        return _run_ingest_local(
            session, {**connector_config, "knowledge_base": _knowledge_base(config)}
        )
    if connector_id == "source.fileshare":
        return _run_ingest_fileshare(
            session, {**connector_config, "knowledge_base": _knowledge_base(config)}
        )
    if connector_id == "source.s3":
        return _run_ingest_s3(
            session, {**connector_config, "knowledge_base": _knowledge_base(config)}
        )
    if connector_id == "source.database":
        return _run_ingest_database(
            session, {**connector_config, "knowledge_base": _knowledge_base(config)}
        )
    probe = probe_enterprise_connector(connector_id, config=connector_config)
    if probe["status"] in {"missing_credentials", "unknown_connector"}:
        raise WorkflowValidationError(str(probe["status"]))
    return None, {"connector_probe": probe}


def _run_noop(_session: Session, config: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    return None, {"config": config}


def _topological_steps(steps: list[WorkflowStep]) -> list[WorkflowStep]:
    by_id: dict[str, WorkflowStep] = {}
    for step in steps:
        if not step.step_id:
            raise WorkflowValidationError("step_id is required")
        if step.step_id in by_id:
            raise WorkflowValidationError(f"duplicate step_id: {step.step_id}")
        by_id[step.step_id] = step
    missing = sorted({dep for step in steps for dep in step.depends_on if dep not in by_id})
    if missing:
        raise WorkflowValidationError(f"unknown dependency: {', '.join(missing)}")

    ordered: list[WorkflowStep] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visited:
            return
        if step_id in visiting:
            raise WorkflowValidationError("workflow dependency cycle detected")
        visiting.add(step_id)
        for dep in by_id[step_id].depends_on:
            visit(dep)
        visiting.remove(step_id)
        visited.add(step_id)
        ordered.append(by_id[step_id])

    for step in steps:
        visit(step.step_id)
    return ordered


def _mark_dependents_skipped(
    steps: list[WorkflowStep],
    results: list[WorkflowStepResult],
    failed_steps: set[str],
) -> None:
    completed = {result.step_id for result in results}
    changed = True
    while changed:
        changed = False
        for step in steps:
            if step.step_id in completed:
                continue
            blocked_by = sorted(dep for dep in step.depends_on if dep in failed_steps)
            if blocked_by:
                failed_steps.add(step.step_id)
                completed.add(step.step_id)
                changed = True
                results.append(
                    WorkflowStepResult(
                        step_id=step.step_id,
                        operation=step.operation,
                        status="skipped",
                        attempts=0,
                        duration_ms=0.0,
                        output={"blocked_by": blocked_by},
                        error="dependency_failed",
                    )
                )


def _knowledge_base(config: dict[str, Any]) -> str:
    value = config.get("knowledge_base") or config.get("knowledge_base_name")
    if not value:
        raise WorkflowValidationError("knowledge_base is required")
    return str(value)


def _optional_string_list(value: object) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise WorkflowValidationError("pattern fields must be lists")
    return [str(item) for item in value]


def _report_output(report: object) -> dict[str, Any]:
    return {key: value for key, value in report.__dict__.items() if key != "pipeline_run_id"}


_RUNNERS = {
    "ingest.connector": _run_ingest_connector,
    "ingest.local": _run_ingest_local,
    "ingest.fileshare": _run_ingest_fileshare,
    "ingest.s3": _run_ingest_s3,
    "ingest.database": _run_ingest_database,
    "index.knowledge_base": _run_index,
    "noop": _run_noop,
}
