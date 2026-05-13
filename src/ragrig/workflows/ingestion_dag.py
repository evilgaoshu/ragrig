from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Callable

from sqlalchemy.orm import Session

from ragrig.db.models import PipelineRun
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.ingestion.scanner import scan_paths
from ragrig.repositories import create_pipeline_run, get_or_create_knowledge_base

DAG_NODE_IDS = ("ingest", "parse", "chunk", "embed", "index")
_SECRET_KEY_PARTS = (
    "api_key",
    "access_key",
    "secret",
    "token",
    "password",
    "private_key",
    "credential",
)
_TRANSIENT_STATUSES = {"pending", "running"}
_TERMINAL_STATUSES = {"completed", "failed", "skipped"}


class IngestionDagRejected(ValueError):
    pass


class IngestionDagInjectedFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class IngestionDagReport:
    pipeline_run_id: str
    status: str
    resumed: bool
    nodes: list[dict[str, Any]]
    failure_queue: list[dict[str, Any]]
    failed_node: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "pipeline_run_id": self.pipeline_run_id,
            "status": self.status,
            "resumed": self.resumed,
            "nodes": self.nodes,
            "failure_queue": self.failure_queue,
            "failed_node": self.failed_node,
        }


def run_ingestion_dag(
    session: Session,
    *,
    knowledge_base_name: str,
    root_path: Path,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    max_file_size_bytes: int = 10 * 1024 * 1024,
    failure_node: str | None = None,
) -> IngestionDagReport:
    if failure_node is not None and failure_node not in DAG_NODE_IDS:
        raise IngestionDagRejected(f"unknown DAG failure node: {failure_node}")
    request = {
        "knowledge_base": knowledge_base_name,
        "root_path": str(root_path.resolve()),
        "include_patterns": include_patterns or [],
        "exclude_patterns": exclude_patterns or [],
        "max_file_size_bytes": max_file_size_bytes,
        "failure_node": failure_node,
    }
    _reject_secret_like_payload(request)
    kb = get_or_create_knowledge_base(session, knowledge_base_name)
    run = create_pipeline_run(
        session,
        knowledge_base_id=kb.id,
        source_id=None,
        run_type="ingestion_dag",
        config_snapshot_json={
            "dag": _new_dag_snapshot(request),
            "idempotency_key": _idempotency_key(request),
        },
    )
    session.commit()
    return _execute_dag(session, run=run, resumed=False)


def resume_ingestion_dag(
    session: Session,
    *,
    pipeline_run_id: str,
) -> dict[str, Any] | None:
    run = session.get(PipelineRun, uuid.UUID(pipeline_run_id))
    if run is None or run.run_type != "ingestion_dag":
        return None
    session.refresh(run)
    snapshot = run.config_snapshot_json or {}
    dag = snapshot.get("dag")
    if not isinstance(dag, dict):
        return _rejected(run, "missing_dag_snapshot")
    _ensure_failure_queue(dag)
    if snapshot.get("snapshot_expired"):
        return _rejected(run, "stale_snapshot")
    if run.status == "completed" or (
        not _has_open_failure(dag)
        and all(node.get("status") == "completed" for node in _nodes(dag))
    ):
        return _rejected(run, "duplicate_retry")
    if run.status == "running":
        return _rejected(run, "invalid_state_transition")
    report = _execute_dag(session, run=run, resumed=True)
    return report.as_dict()


def dag_snapshot(run: PipelineRun) -> dict[str, Any] | None:
    dag = (run.config_snapshot_json or {}).get("dag")
    if not isinstance(dag, dict):
        return None
    return _public_dag(dag)


def _execute_dag(session: Session, *, run: PipelineRun, resumed: bool) -> IngestionDagReport:
    dag = deepcopy((run.config_snapshot_json or {})["dag"])
    request = dict(dag["request"])
    if resumed:
        request["failure_node"] = None
        dag["request"] = request
    nodes = [dict(node) for node in dag["nodes"]]
    dag["nodes"] = nodes
    original_failures = [dict(entry) for entry in dag.get("failure_queue", [])]
    dag["failure_queue"] = [
        {**entry, "status": "retrying"} if entry.get("status") == "open" else dict(entry)
        for entry in dag.get("failure_queue", [])
    ]
    failed_node: str | None = None
    run.status = "running"
    _store_dag(run, dag)
    session.commit()

    for node in nodes:
        if node["status"] == "completed":
            continue
        node["status"] = "running"
        started = perf_counter()
        try:
            output = _node_runner(node["node_id"])(session, request)
            if request.get("failure_node") == node["node_id"]:
                request["failure_node"] = None
                dag["request"] = request
                raise IngestionDagInjectedFailure(f"{node['node_id']}_failure_fixture")
            node.update(
                {
                    "status": "completed",
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                    "output_summary": _safe_summary(output),
                    "error": None,
                }
            )
        except Exception as exc:
            failed_node = node["node_id"]
            reason = _safe_error(str(exc))
            node.update(
                {
                    "status": "failed",
                    "duration_ms": round((perf_counter() - started) * 1000, 3),
                    "error": reason,
                }
            )
            _upsert_failure(dag, node_id=node["node_id"], reason=reason)
            break
        finally:
            _store_dag(run, dag)
            session.commit()

    if failed_node is None:
        if not dag.get("failure_queue") and original_failures:
            dag["failure_queue"] = [{**entry, "status": "retrying"} for entry in original_failures]
        for entry in dag.get("failure_queue", []):
            if entry.get("status") == "retrying":
                entry["status"] = "resolved"
        run.status = "completed"
    else:
        for node in nodes:
            if node["status"] in _TRANSIENT_STATUSES:
                node["status"] = "pending"
        run.status = "completed_with_failures"
    run.total_items = len(nodes)
    run.success_count = sum(node["status"] == "completed" for node in nodes)
    run.failure_count = sum(entry.get("status") == "open" for entry in dag["failure_queue"])
    run.finished_at = datetime.now(timezone.utc)
    _store_dag(run, dag)
    session.commit()
    public = _public_dag(dag)
    return IngestionDagReport(
        pipeline_run_id=str(run.id),
        status=run.status,
        resumed=resumed,
        nodes=public["nodes"],
        failure_queue=public["failure_queue"],
        failed_node=failed_node,
    )


def _node_runner(node_id: str) -> Callable[[Session, dict[str, Any]], dict[str, Any]]:
    return {
        "ingest": _run_ingest_scan,
        "parse": _run_parse_ingestion,
        "chunk": _run_chunk_summary,
        "embed": _run_embed_summary,
        "index": _run_index,
    }[node_id]


def _run_ingest_scan(_session: Session, request: dict[str, Any]) -> dict[str, Any]:
    scan = scan_paths(
        root_path=Path(request["root_path"]),
        include_patterns=request["include_patterns"],
        exclude_patterns=request["exclude_patterns"],
        max_file_size_bytes=int(request["max_file_size_bytes"]),
    )
    return {"discovered": len(scan.discovered), "skipped": len(scan.skipped)}


def _run_parse_ingestion(session: Session, request: dict[str, Any]) -> dict[str, Any]:
    report = ingest_local_directory(
        session=session,
        knowledge_base_name=str(request["knowledge_base"]),
        root_path=Path(request["root_path"]),
        include_patterns=list(request["include_patterns"]),
        exclude_patterns=list(request["exclude_patterns"]),
        max_file_size_bytes=int(request["max_file_size_bytes"]),
    )
    return {
        "pipeline_run_id": str(report.pipeline_run_id),
        "created_documents": report.created_documents,
        "created_versions": report.created_versions,
        "skipped_count": report.skipped_count,
        "failed_count": report.failed_count,
    }


def _run_chunk_summary(_session: Session, request: dict[str, Any]) -> dict[str, Any]:
    return {"knowledge_base": str(request["knowledge_base"]), "mode": "index_plan"}


def _run_embed_summary(_session: Session, request: dict[str, Any]) -> dict[str, Any]:
    return {"knowledge_base": str(request["knowledge_base"]), "provider": "deterministic-local"}


def _run_index(session: Session, request: dict[str, Any]) -> dict[str, Any]:
    report = index_knowledge_base(
        session=session,
        knowledge_base_name=str(request["knowledge_base"]),
    )
    return {
        "pipeline_run_id": str(report.pipeline_run_id),
        "indexed_count": report.indexed_count,
        "skipped_count": report.skipped_count,
        "failed_count": report.failed_count,
        "chunk_count": report.chunk_count,
        "embedding_count": report.embedding_count,
    }


def _new_dag_snapshot(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "ingestion-dag/v1",
        "request": request,
        "nodes": [
            {
                "node_id": node_id,
                "status": "pending",
                "duration_ms": 0.0,
                "input_summary": _safe_summary(
                    {
                        "knowledge_base": request["knowledge_base"],
                        "root_path": (
                            request["root_path"] if node_id == "ingest" else "[prior-node]"
                        ),
                    }
                ),
                "output_summary": {},
                "error": None,
            }
            for node_id in DAG_NODE_IDS
        ],
        "failure_queue": [],
    }


def _store_dag(run: PipelineRun, dag: dict[str, Any]) -> None:
    snapshot = deepcopy(run.config_snapshot_json or {})
    snapshot["dag"] = deepcopy(dag)
    run.config_snapshot_json = snapshot


def _nodes(dag: dict[str, Any]) -> list[dict[str, Any]]:
    return [node for node in dag.get("nodes", []) if isinstance(node, dict)]


def _has_open_failure(dag: dict[str, Any]) -> bool:
    return any(entry.get("status") == "open" for entry in dag.get("failure_queue", []))


def _ensure_failure_queue(dag: dict[str, Any]) -> None:
    if dag.get("failure_queue"):
        return
    for node in _nodes(dag):
        if node.get("status") == "failed":
            dag["failure_queue"] = [
                {
                    "node_id": node.get("node_id"),
                    "reason": node.get("error") or "dag_node_failed",
                    "status": "open",
                    "retryable": True,
                    "retry_count": 0,
                }
            ]
            return


def _upsert_failure(dag: dict[str, Any], *, node_id: str, reason: str) -> None:
    queue = dag.setdefault("failure_queue", [])
    for entry in queue:
        if entry.get("node_id") == node_id and entry.get("status") in {"open", "retrying"}:
            entry.update(
                {"reason": reason, "status": "open", "retry_count": entry["retry_count"] + 1}
            )
            return
    queue.append(
        {
            "node_id": node_id,
            "reason": reason,
            "status": "open",
            "retryable": True,
            "retry_count": 0,
        }
    )


def _rejected(run: PipelineRun, reason: str) -> dict[str, Any]:
    return {
        "pipeline_run_id": str(run.id),
        "status": "rejected",
        "degraded": True,
        "reason": reason,
        "resumed": False,
    }


def _idempotency_key(request: dict[str, Any]) -> str:
    encoded = json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _reject_secret_like_payload(value: Any, path: str = "request") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if any(part in str(key).lower() for part in _SECRET_KEY_PARTS):
                if isinstance(nested, str) and nested.strip() and not nested.startswith("env:"):
                    raise IngestionDagRejected(f"secret-like value rejected at {path}.{key}")
            _reject_secret_like_payload(nested, f"{path}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_secret_like_payload(nested, f"{path}[{index}]")


def _safe_summary(payload: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        if any(part in str(key).lower() for part in _SECRET_KEY_PARTS):
            safe[str(key)] = "[redacted]"
        elif isinstance(value, str):
            safe[str(key)] = _safe_error(value)
        else:
            safe[str(key)] = value
    return safe


def _safe_error(message: str) -> str:
    redacted = message
    for fragment in ("sk-live-", "sk-proj-", "Bearer ", "PRIVATE KEY-----", "ghp_"):
        redacted = redacted.replace(fragment, "[redacted]")
    return redacted[:240]


def _public_dag(dag: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": dag.get("schema_version"),
        "nodes": [_safe_summary(dict(node)) for node in _nodes(dag)],
        "failure_queue": [_safe_summary(dict(entry)) for entry in dag.get("failure_queue", [])],
    }
