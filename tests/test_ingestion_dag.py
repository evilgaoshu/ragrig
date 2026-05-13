from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.db.models import Base, DocumentVersion, Embedding, PipelineRun
from ragrig.workflows.ingestion_dag import (
    DAG_NODE_IDS,
    IngestionDagRejected,
    _reject_secret_like_payload,
    resume_ingestion_dag,
    run_ingestion_dag,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def _session(tmp_path: Path) -> Session:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'dag.db'}", future=True)
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def _docs(tmp_path: Path) -> Path:
    root = tmp_path / "docs"
    root.mkdir()
    (root / "guide.md").write_text("# DAG\n\nRunner fixture.", encoding="utf-8")
    return root


def test_ingestion_dag_success_reports_all_nodes(tmp_path) -> None:
    session = _session(tmp_path)
    report = run_ingestion_dag(
        session,
        knowledge_base_name="dag-success",
        root_path=_docs(tmp_path),
    )

    assert report.status == "completed"
    assert [node["node_id"] for node in report.nodes] == list(DAG_NODE_IDS)
    assert {node["status"] for node in report.nodes} == {"completed"}
    assert all("duration_ms" in node and "output_summary" in node for node in report.nodes)
    assert report.failure_queue == []


@pytest.mark.parametrize("failure_node", ["parse", "embed", "index"])
def test_ingestion_dag_failure_queue_and_resume(tmp_path, failure_node: str) -> None:
    session = _session(tmp_path)
    root = _docs(tmp_path)
    first = run_ingestion_dag(
        session,
        knowledge_base_name=f"dag-{failure_node}",
        root_path=root,
        failure_node=failure_node,
    )
    versions_before = session.query(DocumentVersion).count()
    embeddings_before = session.query(Embedding).count()

    assert first.status == "completed_with_failures"
    assert first.failed_node == failure_node
    assert first.failure_queue[0]["node_id"] == failure_node
    assert first.failure_queue[0]["reason"] == f"{failure_node}_failure_fixture"

    resumed = resume_ingestion_dag(session, pipeline_run_id=first.pipeline_run_id)
    assert resumed is not None
    assert resumed["status"] == "completed"
    assert resumed["failure_queue"][0]["status"] == "resolved"
    assert session.query(DocumentVersion).count() == versions_before
    if failure_node == "index":
        assert session.query(Embedding).count() == embeddings_before


def test_ingestion_dag_duplicate_resume_is_rejected(tmp_path) -> None:
    session = _session(tmp_path)
    report = run_ingestion_dag(
        session,
        knowledge_base_name="dag-duplicate",
        root_path=_docs(tmp_path),
    )
    result = resume_ingestion_dag(session, pipeline_run_id=report.pipeline_run_id)
    assert result is not None
    assert result["status"] == "rejected"
    assert result["reason"] == "duplicate_retry"


def test_ingestion_dag_stale_snapshot_is_rejected(tmp_path) -> None:
    session = _session(tmp_path)
    report = run_ingestion_dag(
        session,
        knowledge_base_name="dag-stale",
        root_path=_docs(tmp_path),
        failure_node="embed",
    )
    run = session.get(PipelineRun, uuid.UUID(report.pipeline_run_id))
    assert run is not None
    run.config_snapshot_json = {**run.config_snapshot_json, "snapshot_expired": True}
    session.commit()

    result = resume_ingestion_dag(session, pipeline_run_id=report.pipeline_run_id)
    assert result is not None
    assert result["status"] == "rejected"
    assert result["reason"] == "stale_snapshot"


def test_ingestion_dag_secret_like_payload_is_rejected() -> None:
    with pytest.raises(IngestionDagRejected, match="secret-like value rejected"):
        _reject_secret_like_payload({"config": {"api_key": "sk-live-hidden"}})
