from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ragrig.db.models import PipelineRun, PipelineRunItem
from ragrig.metrics import observe_pipeline_item


def create_pipeline_run(
    session: Session,
    *,
    knowledge_base_id,
    source_id,
    run_type: str = "local_ingestion",
    config_snapshot_json: dict[str, object],
) -> PipelineRun:
    run = PipelineRun(
        knowledge_base_id=knowledge_base_id,
        source_id=source_id,
        run_type=run_type,
        status="running",
        config_snapshot_json=config_snapshot_json,
        total_items=0,
        success_count=0,
        failure_count=0,
    )
    session.add(run)
    session.flush()
    return run


def create_pipeline_run_item(
    session: Session,
    *,
    pipeline_run_id,
    document_id,
    status: str,
    metadata_json: dict[str, object],
    error_message: str | None = None,
) -> PipelineRunItem:
    item = PipelineRunItem(
        pipeline_run_id=pipeline_run_id,
        document_id=document_id,
        status=status,
        error_message=error_message,
        metadata_json=metadata_json,
        finished_at=datetime.now(timezone.utc),
    )
    session.add(item)
    session.flush()
    observe_pipeline_item(
        pipeline_type=_pipeline_type(session, pipeline_run_id),
        stage=_pipeline_stage(metadata_json),
        status=status,
    )
    return item


def _pipeline_type(session: Session, pipeline_run_id) -> str:
    run = session.get(PipelineRun, pipeline_run_id)
    return run.run_type if run is not None else "unknown"


def _pipeline_stage(metadata_json: dict[str, object]) -> str:
    stage = metadata_json.get("stage")
    if isinstance(stage, str) and stage.strip():
        return stage
    if "chunk_count" in metadata_json or "embedding_dimensions" in metadata_json:
        return "index"
    if "parser_name" in metadata_json or "parser_id" in metadata_json:
        return "parse"
    if "skip_reason" in metadata_json:
        return "filter"
    return "document"
