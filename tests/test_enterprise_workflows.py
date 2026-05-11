from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.db.models import Base, Chunk, KnowledgeBase, PipelineRun
from ragrig.main import create_app

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@contextmanager
def _create_session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def test_enterprise_connector_catalog_covers_mainstream_sources_without_secret_values() -> None:
    from ragrig.plugins.enterprise import list_enterprise_connectors

    connectors = list_enterprise_connectors()
    by_id = {item["plugin_id"]: item for item in connectors}

    assert {
        "source.local",
        "source.fileshare",
        "source.s3",
        "source.google_workspace",
        "source.microsoft_365",
        "source.wiki",
        "source.database",
        "source.collaboration",
        "source.notion",
        "source.slack",
        "source.box",
        "source.dropbox",
        "source.github",
    } <= set(by_id)

    google = by_id["source.google_workspace"]
    assert google["protocols"] == ["google-drive-api"]
    assert google["official_docs_url"].startswith("https://developers.google.com/")
    assert google["workflow_operation"] == "ingest.connector"

    microsoft = by_id["source.microsoft_365"]
    assert "microsoft-graph" in microsoft["protocols"]
    assert microsoft["required_credentials"] == ["MICROSOFT_365_CLIENT_SECRET"]

    for item in connectors:
        assert item["official_docs_url"].startswith("https://")
        assert "secret" not in str(item.get("example_config", {})).lower()
        assert all(not value.startswith("env:") for value in item["required_credentials"])


def test_enterprise_connector_probe_degrades_without_credentials_and_checks_local_paths(
    tmp_path: Path,
) -> None:
    from ragrig.plugins.enterprise import probe_enterprise_connector

    missing = probe_enterprise_connector("source.microsoft_365", config={}, env={})
    assert missing["status"] == "missing_credentials"
    assert missing["missing_credentials"] == ["MICROSOFT_365_CLIENT_SECRET"]
    assert missing["network_called"] is False

    local_missing = probe_enterprise_connector(
        "source.local",
        config={"root_path": str(tmp_path / "missing")},
        env={},
    )
    assert local_missing["status"] == "unavailable"
    assert local_missing["reason"] == "root_path_not_found"

    local_ready = probe_enterprise_connector(
        "source.local",
        config={"root_path": str(tmp_path)},
        env={},
    )
    assert local_ready["status"] == "ready"
    assert local_ready["network_called"] is False


def test_workflow_engine_dry_run_validates_dag_without_mutating_database(tmp_path: Path) -> None:
    from ragrig.workflows.engine import WorkflowDefinition, WorkflowStep, run_workflow

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Guide\n\nAlpha\n", encoding="utf-8")

    workflow = WorkflowDefinition(
        workflow_id="enterprise-local-dry-run",
        steps=[
            WorkflowStep(
                step_id="ingest",
                operation="ingest.local",
                config={"knowledge_base": "wf-kb", "root_path": str(docs)},
            ),
            WorkflowStep(
                step_id="index",
                operation="index.knowledge_base",
                depends_on=["ingest"],
                config={"knowledge_base": "wf-kb"},
            ),
        ],
    )

    with _create_session() as session:
        report = run_workflow(session=session, definition=workflow, dry_run=True)
        knowledge_bases = session.scalars(select(KnowledgeBase)).all()
        pipeline_runs = session.scalars(select(PipelineRun)).all()

    assert report.status == "planned"
    assert [step.status for step in report.steps] == ["planned", "planned"]
    assert [step.operation for step in report.steps] == ["ingest.local", "index.knowledge_base"]
    assert all(step.pipeline_run_id is None for step in report.steps)
    assert knowledge_bases == []
    assert pipeline_runs == []


def test_workflow_engine_runs_local_ingest_then_index(tmp_path: Path) -> None:
    from ragrig.workflows.engine import WorkflowDefinition, WorkflowStep, run_workflow

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Guide\n\nAlpha beta gamma delta\n", encoding="utf-8")

    workflow = WorkflowDefinition(
        workflow_id="enterprise-local",
        steps=[
            WorkflowStep(
                step_id="ingest",
                operation="ingest.local",
                config={"knowledge_base": "wf-kb", "root_path": str(docs)},
            ),
            WorkflowStep(
                step_id="index",
                operation="index.knowledge_base",
                depends_on=["ingest"],
                config={"knowledge_base": "wf-kb", "chunk_size": 12, "chunk_overlap": 2},
            ),
        ],
    )

    with _create_session() as session:
        report = run_workflow(session=session, definition=workflow)
        pipeline_runs = session.scalars(select(PipelineRun).order_by(PipelineRun.started_at)).all()
        chunks = session.scalars(select(Chunk)).all()

    assert report.status == "completed"
    assert [step.status for step in report.steps] == ["success", "success"]
    assert [run.run_type for run in pipeline_runs] == ["local_ingestion", "chunk_embedding"]
    assert len(chunks) >= 1
    assert report.steps[0].output["created_versions"] == 1
    assert report.steps[1].output["chunk_count"] >= 1


def test_workflow_engine_rejects_cycles_and_unknown_operations() -> None:
    from ragrig.workflows.engine import (
        WorkflowDefinition,
        WorkflowStep,
        WorkflowValidationError,
        run_workflow,
    )

    with pytest.raises(WorkflowValidationError, match="cycle"):
        WorkflowDefinition(
            workflow_id="cycle",
            steps=[
                WorkflowStep(step_id="a", operation="noop", depends_on=["b"]),
                WorkflowStep(step_id="b", operation="noop", depends_on=["a"]),
            ],
        )

    with _create_session() as session:
        with pytest.raises(WorkflowValidationError, match="unsupported operation"):
            run_workflow(
                session=session,
                definition=WorkflowDefinition(
                    workflow_id="unknown",
                    steps=[WorkflowStep(step_id="missing", operation="missing.op")],
                ),
            )


@pytest.mark.anyio
async def test_enterprise_connector_and_workflow_api_endpoints(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text("# Guide\n\nAlpha\n", encoding="utf-8")

    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)

    def _session_factory() -> Session:
        return Session(engine, expire_on_commit=False)

    app = create_app(check_database=lambda: None, session_factory=_session_factory)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        connectors = await client.get("/enterprise-connectors")
        probe = await client.post(
            "/enterprise-connectors/source.local/probe",
            json={"config": {"root_path": str(docs)}},
        )
        operations = await client.get("/workflows/operations")
        workflow = await client.post(
            "/workflows/runs",
            json={
                "workflow_id": "api-dry-run",
                "dry_run": True,
                "steps": [
                    {
                        "step_id": "ingest",
                        "operation": "ingest.local",
                        "config": {
                            "knowledge_base": "api-kb",
                            "root_path": str(docs),
                        },
                    }
                ],
            },
        )

    assert connectors.status_code == 200
    assert "source.microsoft_365" in {item["plugin_id"] for item in connectors.json()["items"]}
    assert probe.status_code == 200
    assert probe.json()["status"] == "ready"
    assert operations.status_code == 200
    assert "ingest.local" in {item["operation"] for item in operations.json()["items"]}
    assert workflow.status_code == 200
    assert workflow.json()["status"] == "planned"

    engine.dispose()
