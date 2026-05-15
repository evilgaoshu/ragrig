from __future__ import annotations

import shutil
import tempfile
import threading
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ragrig.db.models import DocumentVersion, PipelineRun
from ragrig.formats import FormatStatus, get_format_registry
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import _select_parser
from ragrig.parsers.base import ParserTimeoutError, parse_with_timeout
from ragrig.repositories import (
    create_pipeline_run,
    create_pipeline_run_item,
    create_task_record,
    get_knowledge_base_by_name,
    get_next_version_number,
    get_or_create_document,
    get_or_create_source,
    get_task_record,
    update_task_status,
)
from ragrig.workflows import IngestionDagRejected, execute_ingestion_dag_run

TaskJob = Callable[[], None]
_INDEX_LOCKS_GUARD = threading.Lock()
_INDEX_LOCKS: dict[str, threading.Lock] = {}


class TaskExecutor:
    def submit(self, job: TaskJob) -> None:
        raise NotImplementedError


class ThreadPoolTaskExecutor(TaskExecutor):
    def __init__(self, max_workers: int = 4) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ragrig-task")

    def submit(self, job: TaskJob) -> None:
        self._pool.submit(job)


@dataclass(frozen=True)
class UploadAcceptance:
    warnings: list[dict[str, Any]]
    rejected: list[dict[str, Any]]
    staged_files: list[dict[str, str]]
    staging_dir: str | None = None


def default_task_executor() -> TaskExecutor:
    return ThreadPoolTaskExecutor()


def enqueue_task(
    *,
    session_factory: Callable[[], Session],
    task_executor: TaskExecutor,
    task_type: str,
    payload_json: dict[str, Any],
    runner: Callable[[], dict[str, Any]],
) -> str:
    with session_factory() as session:
        task = create_task_record(session, task_type=task_type, payload_json=payload_json)
        session.commit()
        task_id = str(task.id)

    def _wrapped() -> None:
        with session_factory() as session:
            update_task_status(session, task_id=task_id, status="running")
            session.commit()
        try:
            result = runner()
        except Exception as exc:
            with session_factory() as session:
                update_task_status(session, task_id=task_id, status="failed", error=str(exc))
                session.commit()
            return
        with session_factory() as session:
            update_task_status(session, task_id=task_id, status="completed", result_json=result)
            session.commit()

    task_executor.submit(_wrapped)
    return task_id


def serialize_task_record(task) -> dict[str, Any]:
    return {
        "task_id": str(task.id),
        "status": task.status,
        "result": task.result_json,
        "error": task.error,
    }


def get_task_payload(
    *,
    session_factory: Callable[[], Session],
    task_id: str,
) -> dict[str, Any] | None:
    with session_factory() as session:
        task = get_task_record(session, task_id)
        if task is None:
            return None
        return serialize_task_record(task)


def validate_and_stage_uploads(
    *,
    files: list[tuple[str, bytes]],
) -> UploadAcceptance:
    registry = get_format_registry()
    rejected: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    accepted_files: list[tuple[str, bytes, Any]] = []

    for filename, content in files:
        extension = Path(filename).suffix.lower()
        fmt = registry.lookup(extension or "")
        if fmt is None:
            rejected.append(
                {
                    "filename": filename,
                    "extension": extension or "(none)",
                    "reason": "unsupported_format",
                    "message": f"File format {extension or '(no extension)'} is not supported.",
                }
            )
            continue
        if fmt.status == FormatStatus.PLANNED:
            rejected.append(
                {
                    "filename": filename,
                    "extension": extension,
                    "reason": "unsupported_format",
                    "message": (
                        f"{fmt.display_name} support is planned. "
                        f"{fmt.limitations or 'Not yet implemented.'}"
                    ),
                }
            )
            continue
        if fmt.status == FormatStatus.PREVIEW:
            warnings.append(
                {
                    "filename": filename,
                    "extension": extension,
                    "status": "preview",
                    "parser_id": fmt.parser_id,
                    "fallback_policy": fmt.fallback_policy,
                    "message": (
                        f"{fmt.display_name} is in preview status - "
                        f"{fmt.limitations or 'content will be parsed as plain text.'}"
                    ),
                }
            )
        max_size = fmt.max_file_size_mb * 1024 * 1024
        if len(content) > max_size:
            rejected.append(
                {
                    "filename": filename,
                    "extension": extension,
                    "reason": "file_too_large",
                    "message": (
                        f"File '{filename}' exceeds the {fmt.max_file_size_mb} MB size limit for "
                        f"{fmt.display_name}."
                    ),
                }
            )
            continue
        accepted_files.append((filename, content, fmt))

    if len(accepted_files) > 10:
        raise ValueError(f"too many files: {len(accepted_files)}. Maximum 10 files per request.")

    staging_dir = Path(tempfile.mkdtemp(prefix="ragrig-upload-"))
    staged_files: list[dict[str, str]] = []
    for filename, content, _fmt in accepted_files:
        safe_name = sanitize_filename(filename)
        dest = staging_dir / safe_name
        dest.write_bytes(content)
        staged_files.append({"filename": filename, "path": str(dest)})

    return UploadAcceptance(
        warnings=warnings,
        rejected=rejected,
        staged_files=staged_files,
        staging_dir=str(staging_dir),
    )


def cleanup_staged_files(staged_files: list[dict[str, str]]) -> None:
    if not staged_files:
        return
    staging_dir = Path(staged_files[0]["path"]).parent
    shutil.rmtree(staging_dir, ignore_errors=True)


def cleanup_staging_dir(staging_dir: str | None) -> None:
    if not staging_dir:
        return
    shutil.rmtree(staging_dir, ignore_errors=True)


def mark_pipeline_run_failed(
    *,
    session_factory: Callable[[], Session],
    pipeline_run_id: str,
    error_message: str,
) -> None:
    with session_factory() as session:
        run = session.get(PipelineRun, uuid.UUID(pipeline_run_id))
        if run is None:
            return
        run.status = "failed"
        run.error_message = error_message
        run.finished_at = datetime.now(timezone.utc)
        session.commit()


def knowledge_base_index_lock(knowledge_base_name: str) -> threading.Lock:
    with _INDEX_LOCKS_GUARD:
        lock = _INDEX_LOCKS.get(knowledge_base_name)
        if lock is None:
            lock = threading.Lock()
            _INDEX_LOCKS[knowledge_base_name] = lock
        return lock


def sanitize_filename(filename: str) -> str:
    from pathlib import PurePath

    name = PurePath(filename).name
    name = name.replace("/", "_").replace("\\", "_").replace("\0", "")
    if not name or name.startswith("."):
        name = f"upload_{name or 'file'}"
    return name


def create_upload_pipeline_run(
    session: Session,
    *,
    kb_name: str,
    staged_files: list[dict[str, str]],
) -> tuple[str, str]:
    kb = get_knowledge_base_by_name(session, kb_name)
    if kb is None:
        raise ValueError(f"knowledge base '{kb_name}' not found")
    staging_path = str(Path(staged_files[0]["path"]).parent)
    source = get_or_create_source(
        session,
        knowledge_base_id=kb.id,
        uri=staging_path,
        config_json={"kind": "web_upload", "staging_dir": staging_path},
    )
    run = create_pipeline_run(
        session,
        knowledge_base_id=kb.id,
        source_id=source.id,
        run_type="web_upload",
        config_snapshot_json={
            "source": "web_upload",
            "knowledge_base": kb_name,
            "file_count": len(staged_files),
        },
    )
    session.commit()
    return str(run.id), str(source.id)


def run_upload_pipeline(
    *,
    session_factory: Callable[[], Session],
    kb_name: str,
    pipeline_run_id: str,
    staged_files: list[dict[str, str]],
) -> dict[str, Any]:
    retain_staged_files = False
    try:
        with session_factory() as session:
            kb = get_knowledge_base_by_name(session, kb_name)
            if kb is None:
                raise ValueError(f"knowledge base '{kb_name}' not found")
            run = session.get(PipelineRun, uuid.UUID(pipeline_run_id))
            if run is None:
                raise ValueError(f"pipeline run '{pipeline_run_id}' not found")
            run_id = str(run.id)
            source = get_or_create_source(
                session,
                knowledge_base_id=kb.id,
                uri=str(Path(staged_files[0]["path"]).parent),
                config_json={
                    "kind": "web_upload",
                    "staging_dir": str(Path(staged_files[0]["path"]).parent),
                },
            )

            created_documents = 0
            created_versions = 0
            failed_count = 0

            for staged in staged_files:
                dest = Path(staged["path"])
                document = None
                item_status = "success"
                item_error: str | None = None
                item_metadata: dict[str, Any] = {"file_name": dest.name}
                try:
                    parser = _select_parser(dest)
                    parse_result = parse_with_timeout(parser, dest, timeout_seconds=30.0)
                    document, was_created = get_or_create_document(
                        session,
                        knowledge_base_id=kb.id,
                        source_id=source.id,
                        uri=str(dest),
                        content_hash=parse_result.content_hash,
                        mime_type=parse_result.mime_type,
                        metadata_json=parse_result.metadata,
                    )
                    if was_created:
                        created_documents += 1

                    version = DocumentVersion(
                        document_id=document.id,
                        version_number=get_next_version_number(session, document_id=document.id),
                        content_hash=parse_result.content_hash,
                        parser_name=parse_result.parser_name,
                        parser_config_json={"plugin_id": f"parser.{parse_result.parser_name}"},
                        extracted_text=parse_result.extracted_text,
                        metadata_json=parse_result.metadata,
                    )
                    session.add(version)
                    session.flush()
                    created_versions += 1

                    item_metadata["version_number"] = version.version_number
                    item_metadata["parser_name"] = parse_result.parser_name
                    item_metadata["parser_id"] = f"parser.{parse_result.parser_name}"
                    degraded_reason = parse_result.metadata.get("degraded_reason")
                    if degraded_reason:
                        item_status = "degraded"
                        item_metadata["degraded_reason"] = degraded_reason
                except ParserTimeoutError as exc:
                    failed_count += 1
                    item_status = "failed"
                    item_error = str(exc)
                    item_metadata["failure_reason"] = "parser_timeout"
                    if document is None:
                        document, _ = get_or_create_document(
                            session,
                            knowledge_base_id=kb.id,
                            source_id=source.id,
                            uri=str(dest),
                            content_hash="timeout",
                            mime_type="text/plain",
                            metadata_json={"failure_reason": "parser_timeout", "path": str(dest)},
                        )
                except Exception as exc:
                    failed_count += 1
                    item_status = "failed"
                    item_error = str(exc)
                    item_metadata["failure_reason"] = str(exc)
                    if document is None:
                        document, _ = get_or_create_document(
                            session,
                            knowledge_base_id=kb.id,
                            source_id=source.id,
                            uri=str(dest),
                            content_hash="failed",
                            mime_type="text/plain",
                            metadata_json={"failure_reason": str(exc), "path": str(dest)},
                        )

                create_pipeline_run_item(
                    session,
                    pipeline_run_id=run.id,
                    document_id=document.id,
                    status=item_status,
                    error_message=item_error,
                    metadata_json=item_metadata,
                )

            run.total_items = len(staged_files)
            run.success_count = created_versions
            run.failure_count = failed_count
            run.status = "completed_with_failures" if failed_count else "completed"
            run.finished_at = datetime.now(timezone.utc)
            run_status = run.status
            retain_staged_files = failed_count > 0
            session.commit()

        try:
            with knowledge_base_index_lock(kb_name):
                with session_factory() as indexing_session:
                    indexing_report = index_knowledge_base(
                        session=indexing_session,
                        knowledge_base_name=kb_name,
                    )
        except Exception as exc:
            mark_pipeline_run_failed(
                session_factory=session_factory,
                pipeline_run_id=pipeline_run_id,
                error_message=str(exc),
            )
            raise

        return {
            "pipeline_run_id": run_id,
            "accepted_files": len(staged_files),
            "status": run_status,
            "indexing": {
                "pipeline_run_id": str(indexing_report.pipeline_run_id),
                "indexed_count": indexing_report.indexed_count,
                "skipped_count": indexing_report.skipped_count,
                "failed_count": indexing_report.failed_count,
                "chunk_count": indexing_report.chunk_count,
                "embedding_count": indexing_report.embedding_count,
            },
        }
    finally:
        if not retain_staged_files:
            cleanup_staged_files(staged_files)


def run_ingestion_dag_task(
    *,
    session_factory: Callable[[], Session],
    pipeline_run_id: str,
) -> dict[str, Any]:
    with session_factory() as session:
        try:
            report = execute_ingestion_dag_run(session, pipeline_run_id=pipeline_run_id)
        except IngestionDagRejected as exc:
            raise ValueError(str(exc)) from exc
        return report.as_dict()
