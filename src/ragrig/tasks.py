from __future__ import annotations

import shutil
import tempfile
import threading
import traceback
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
_TASK_RETRY_LOCKS_GUARD = threading.Lock()
_TASK_RETRY_LOCKS: dict[str, threading.Lock] = {}


class TaskExecutor:
    def submit(self, job: TaskJob) -> None:
        raise NotImplementedError

    def shutdown(self, wait: bool = True) -> None:
        raise NotImplementedError


class ThreadPoolTaskExecutor(TaskExecutor):
    def __init__(self, max_workers: int = 4) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ragrig-task")

    def submit(self, job: TaskJob) -> None:
        self._pool.submit(job)

    def shutdown(self, wait: bool = True) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=not wait)


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
    initial_attempt_count: int = 0,
    on_task_created: Callable[[Session, Any], None] | None = None,
) -> str:
    with session_factory() as session:
        task = create_task_record(
            session,
            task_type=task_type,
            payload_json=payload_json,
            attempt_count=initial_attempt_count,
        )
        if on_task_created is not None:
            on_task_created(session, task)
        session.commit()
        task_id = str(task.id)

    def _wrapped() -> None:
        with session_factory() as session:
            update_task_status(
                session,
                task_id=task_id,
                status="running",
                progress={"current": 0, "total": 1, "message": "Task started."},
            )
            session.commit()
        try:
            result = runner()
        except Exception as exc:
            error_summary = summarize_exception(exc)
            with session_factory() as session:
                update_task_status(
                    session,
                    task_id=task_id,
                    status="failed",
                    error=error_summary,
                    progress={"current": 1, "total": 1, "message": "Task failed."},
                )
                session.commit()
            return
        with session_factory() as session:
            update_task_status(
                session,
                task_id=task_id,
                status="completed",
                result_json=result,
                progress={"current": 1, "total": 1, "message": "Task completed."},
            )
            session.commit()

    task_executor.submit(_wrapped)
    return task_id


def summarize_exception(exc: BaseException, *, max_chars: int = 2000) -> str:
    summary = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()
    if len(summary) <= max_chars:
        return summary
    return summary[: max_chars - 3] + "..."


def serialize_task_record(task) -> dict[str, Any]:
    payload = task.payload_json or {}
    return {
        "task_id": str(task.id),
        "status": task.status,
        "result": task.result_json,
        "error": task.error,
        "attempt_count": task.attempt_count,
        "retryable": is_task_retryable(task),
        "last_error": task_last_error(task),
        "previous_task_id": payload.get("previous_task_id"),
        "next_task_id": payload.get("next_task_id"),
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "progress": task.progress,
    }


class TaskRetryError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def task_last_error(task) -> str | None:
    if task.error:
        return task.error
    result = task.result_json or {}
    if isinstance(result, dict):
        failure_queue = result.get("failure_queue")
        if isinstance(failure_queue, list):
            for entry in failure_queue:
                if isinstance(entry, dict) and entry.get("reason"):
                    return str(entry["reason"])
        failed_node = result.get("failed_node")
        if failed_node:
            return str(failed_node)
    return None


def is_task_retryable(task) -> bool:
    if (task.payload_json or {}).get("next_task_id"):
        return False
    if task.task_type == "pipeline_dag_ingestion":
        result = task.result_json or {}
        return (
            task.status in {"completed", "failed"}
            and isinstance(result, dict)
            and result.get("status") == "completed_with_failures"
        )
    if task.task_type == "knowledge_base_upload":
        return task.status == "failed" and _staged_files_available(task.payload_json or {})
    return False


def retry_task(
    *,
    session_factory: Callable[[], Session],
    task_executor: TaskExecutor,
    task_id: str,
) -> dict[str, Any]:
    with task_retry_lock(task_id):
        with session_factory() as session:
            task = get_task_record(session, task_id)
            if task is None:
                raise TaskRetryError(
                    "task_not_found",
                    "Task not found.",
                    status_code=404,
                )
            if not is_task_retryable(task):
                raise TaskRetryError("task_not_retryable", _not_retryable_reason(task))
            previous_attempt_count = task.attempt_count
            previous_payload = dict(task.payload_json or {})
            previous_pipeline_run_id = previous_payload.get("pipeline_run_id")
            task_type = task.task_type

        if task_type == "pipeline_dag_ingestion":
            prepared = _prepare_pipeline_dag_retry(
                session_factory=session_factory,
                previous_task_id=task_id,
                previous_payload=previous_payload,
            )
        elif task_type == "knowledge_base_upload":
            prepared = _prepare_upload_retry(
                session_factory=session_factory,
                previous_task_id=task_id,
                previous_payload=previous_payload,
            )
        else:
            raise TaskRetryError("unsupported_task_type", f"Task type '{task_type}' cannot retry.")

        payload_json = {
            **prepared["payload_json"],
            "previous_task_id": task_id,
            "previous_pipeline_run_id": previous_pipeline_run_id,
            "retry_idempotency_key": _retry_idempotency_key(
                task_type=task_type,
                previous_task_id=task_id,
                pipeline_run_id=prepared.get("pipeline_run_id"),
            ),
        }

        def _link_previous(session: Session, new_task) -> None:
            previous = get_task_record(session, task_id)
            if previous is None:
                raise TaskRetryError("task_not_found", "Task not found.", status_code=404)
            if (previous.payload_json or {}).get("next_task_id"):
                raise TaskRetryError(
                    "duplicate_retry",
                    "A retry task already exists for this task.",
                )
            previous.payload_json = {
                **(previous.payload_json or {}),
                "next_task_id": str(new_task.id),
                "next_pipeline_run_id": prepared.get("pipeline_run_id"),
            }

        new_task_id = enqueue_task(
            session_factory=session_factory,
            task_executor=task_executor,
            task_type=task_type,
            payload_json=payload_json,
            runner=prepared["runner"],
            initial_attempt_count=previous_attempt_count,
            on_task_created=_link_previous,
        )
        return {
            "task_id": new_task_id,
            "previous_task_id": task_id,
            "pipeline_run_id": prepared.get("pipeline_run_id"),
            "status": "pending",
        }


def task_retry_lock(task_id: str) -> threading.Lock:
    with _TASK_RETRY_LOCKS_GUARD:
        lock = _TASK_RETRY_LOCKS.get(task_id)
        if lock is None:
            lock = threading.Lock()
            _TASK_RETRY_LOCKS[task_id] = lock
        return lock


def _prepare_pipeline_dag_retry(
    *,
    session_factory: Callable[[], Session],
    previous_task_id: str,
    previous_payload: dict[str, Any],
) -> dict[str, Any]:
    from ragrig.workflows import create_ingestion_dag_run

    request = {
        "knowledge_base": previous_payload.get("knowledge_base", "fixture-local"),
        "root_path": previous_payload["root_path"],
        "include_patterns": previous_payload.get("include_patterns"),
        "exclude_patterns": previous_payload.get("exclude_patterns"),
        "max_file_size_bytes": previous_payload.get("max_file_size_bytes", 10 * 1024 * 1024),
        "failure_node": None,
    }
    with session_factory() as session:
        run = create_ingestion_dag_run(
            session,
            knowledge_base_name=str(request["knowledge_base"]),
            root_path=Path(str(request["root_path"])),
            include_patterns=request["include_patterns"],
            exclude_patterns=request["exclude_patterns"],
            max_file_size_bytes=int(request["max_file_size_bytes"]),
            failure_node=None,
        )
        pipeline_run_id = str(run.id)
    payload_json = {
        **request,
        "pipeline_run_id": pipeline_run_id,
        "retry_of": previous_task_id,
    }
    return {
        "payload_json": payload_json,
        "pipeline_run_id": pipeline_run_id,
        "runner": lambda: run_ingestion_dag_task(
            session_factory=session_factory,
            pipeline_run_id=pipeline_run_id,
        ),
    }


def _prepare_upload_retry(
    *,
    session_factory: Callable[[], Session],
    previous_task_id: str,
    previous_payload: dict[str, Any],
) -> dict[str, Any]:
    staged_files = list(previous_payload.get("staged_files") or [])
    knowledge_base = str(previous_payload["knowledge_base"])
    with session_factory() as session:
        pipeline_run_id, _source_id = create_upload_pipeline_run(
            session,
            kb_name=knowledge_base,
            staged_files=staged_files,
        )
    payload_json = {
        "knowledge_base": knowledge_base,
        "pipeline_run_id": pipeline_run_id,
        "staged_files": staged_files,
        "retry_of": previous_task_id,
    }
    return {
        "payload_json": payload_json,
        "pipeline_run_id": pipeline_run_id,
        "runner": lambda: run_upload_pipeline(
            session_factory=session_factory,
            kb_name=knowledge_base,
            pipeline_run_id=pipeline_run_id,
            staged_files=staged_files,
        ),
    }


def _staged_files_available(payload_json: dict[str, Any]) -> bool:
    staged_files = payload_json.get("staged_files")
    if not isinstance(staged_files, list) or not staged_files:
        return False
    return all(
        isinstance(staged, dict)
        and isinstance(staged.get("path"), str)
        and Path(staged["path"]).exists()
        for staged in staged_files
    )


def _not_retryable_reason(task) -> str:
    if (task.payload_json or {}).get("next_task_id"):
        return "A retry task already exists for this task."
    if task.task_type == "knowledge_base_upload" and task.status == "failed":
        return "Upload retry requires retained staged files, but they are not available."
    if task.task_type not in {"pipeline_dag_ingestion", "knowledge_base_upload"}:
        return f"Task type '{task.task_type}' cannot retry."
    return f"Task status '{task.status}' is not retryable."


def _retry_idempotency_key(
    *,
    task_type: str,
    previous_task_id: str,
    pipeline_run_id: str | None,
) -> str:
    return f"{task_type}:{previous_task_id}:{pipeline_run_id}"


def get_task_payload(
    *,
    session_factory: Callable[[], Session],
    task_id: str,
    include_pipeline_run: bool = False,
) -> dict[str, Any] | None:
    with session_factory() as session:
        task = get_task_record(session, task_id)
        if task is None:
            return None
        payload = serialize_task_record(task)
        if include_pipeline_run:
            pipeline_run_id = (task.payload_json or {}).get("pipeline_run_id")
            try:
                run_uuid = uuid.UUID(str(pipeline_run_id))
            except (TypeError, ValueError, AttributeError):
                run_uuid = None
            if run_uuid is not None:
                run = session.get(PipelineRun, run_uuid)
                if run is not None:
                    payload["pipeline_run"] = {
                        "pipeline_run_id": str(run.id),
                        "status": run.status,
                        "run_type": run.run_type,
                        "started_at": run.started_at.isoformat(),
                        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                        "error_message": run.error_message,
                    }
        return payload


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
