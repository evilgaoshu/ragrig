from __future__ import annotations

import io
import json
import logging
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ragrig.answer import generate_answer
from ragrig.config import Settings
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.main import create_app
from ragrig.observability import StructuredJsonFormatter, bind_log_context, log_event
from ragrig.observability.logging import sanitize_log_fields
from ragrig.retrieval import search_knowledge_base


def _events(records) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for record in records:
        event = getattr(record, "event", None)
        if event is None:
            continue
        grouped.setdefault(event, []).append(getattr(record, "structured_fields", {}))
    return grouped


def _seed_docs(tmp_path: Path) -> Path:
    docs = tmp_path / "sensitive-root-sk-test123"
    docs.mkdir()
    (docs / "guide.txt").write_text(
        "RAGRig is a retrieval platform with structured logging evidence.",
        encoding="utf-8",
    )
    return docs


def test_structured_json_formatter_includes_context_and_redacts_sensitive_fields() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredJsonFormatter())
    logger = logging.getLogger("tests.structured_logging")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    try:
        with bind_log_context(request_id="req-123"):
            log_event(
                logger,
                logging.INFO,
                "test.event",
                api_key="sk-live-secret",
                query="alice@example.com ssn 123-45-6789",
                file_path="/tmp/customer-secret/report.pdf",
            )
    finally:
        logger.removeHandler(handler)
        logger.propagate = True

    payload = json.loads(stream.getvalue())
    assert payload["event"] == "test.event"
    assert payload["request_id"] == "req-123"
    assert payload["api_key"] == "[REDACTED]"
    assert payload["query"]["length"] == len("alice@example.com ssn 123-45-6789")
    assert payload["file_path"]["basename"] == "report.pdf"
    assert "alice@example.com" not in stream.getvalue()
    assert "customer-secret" not in stream.getvalue()
    assert "sk-live-secret" not in stream.getvalue()


def test_sanitize_log_fields_redacts_secrets_queries_and_paths() -> None:
    sanitized = sanitize_log_fields(
        {
            "authorization": "Bearer secret-token",
            "query": "personal email bob@example.com",
            "root_path": "/tmp/private/customer/docs",
            "nested": {"password": "p@ssw0rd"},
        }
    )

    assert sanitized["authorization"] == "[REDACTED]"
    assert sanitized["query"]["length"] == len("personal email bob@example.com")
    assert sanitized["root_path"]["basename"] == "docs"
    assert sanitized["nested"]["password"] == "[REDACTED]"
    assert "bob@example.com" not in repr(sanitized)
    assert "/tmp/private/customer" not in repr(sanitized)


def test_request_logging_middleware_propagates_request_id(caplog, sqlite_session: Session) -> None:
    app = create_app(
        check_database=lambda: None,
        session_factory=lambda: sqlite_session,
        settings=Settings(
            ragrig_auth_enabled=False,
            ragrig_log_format="plain",
            ragrig_metrics_enabled=False,
        ),
    )

    with caplog.at_level(logging.INFO):
        response = TestClient(app).get("/health", headers={"X-Request-ID": "demo-req"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "demo-req"
    events = _events(caplog.records)
    assert events["api.request.start"][0]["request_id"] == "demo-req"
    assert events["api.request.completed"][0]["request_id"] == "demo-req"
    assert events["api.request.completed"][0]["status_code"] == 200


def test_core_paths_emit_structured_logs_without_raw_query_or_paths(
    caplog, tmp_path: Path, sqlite_session: Session
) -> None:
    docs = _seed_docs(tmp_path)
    query = "What is RAGRig for alice@example.com?"

    with caplog.at_level(logging.INFO):
        ingest_local_directory(
            session=sqlite_session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(
            session=sqlite_session,
            knowledge_base_name="fixture-local",
            chunk_size=80,
        )
        search_knowledge_base(
            session=sqlite_session,
            knowledge_base_name="fixture-local",
            query=query,
            top_k=1,
        )
        generate_answer(
            session=sqlite_session,
            knowledge_base_name="fixture-local",
            query=query,
            top_k=1,
        )

    events = _events(caplog.records)
    assert "ingest.local.start" in events
    assert "ingest.local.completed" in events
    assert "index.knowledge_base.start" in events
    assert "index.document" in events
    assert "index.embedding_batch.completed" in events
    assert "retrieval.search.start" in events
    assert "retrieval.search.completed" in events
    assert "answer.generate.start" in events
    assert "answer.generate.completed" in events

    assert events["ingest.local.start"][0]["pipeline_run_id"]
    assert events["index.knowledge_base.start"][0]["pipeline_run_id"]
    assert events["index.embedding_batch.completed"][0]["batch_size"] >= 1
    assert events["retrieval.search.start"][0]["mode"] == "dense"
    assert events["retrieval.search.start"][0]["top_k"] == 1
    assert events["retrieval.search.start"][0]["query_length"] == len(query)
    assert events["answer.generate.completed"][0]["grounding_status"] == "grounded"

    serialized_fields = "\n".join(
        repr(getattr(record, "structured_fields", {})) for record in caplog.records
    )
    assert "alice@example.com" not in serialized_fields
    assert str(docs) not in serialized_fields
    assert "sensitive-root-sk-test123" not in serialized_fields
