from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from ragrig.db.models import PipelineRun, PipelineRunItem


def create_pipeline_run(
    session: Session,
    *,
    knowledge_base_id,
    source_id,
    config_snapshot_json: dict[str, object],
) -> PipelineRun:
    run = PipelineRun(
        knowledge_base_id=knowledge_base_id,
        source_id=source_id,
        run_type="local_ingestion",
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
    return item
