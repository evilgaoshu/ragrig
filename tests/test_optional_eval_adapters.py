"""Unit tests for optional evaluation/observability adapters."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ragrig.config import Settings
from ragrig.evaluation import engine
from ragrig.evaluation.engine import run_evaluation
from ragrig.observability.langfuse import emit_langfuse_trace

pytestmark = pytest.mark.unit


def _write_golden(path: Path) -> Path:
    path.write_text(
        """
golden_question_set:
  name: optional-adapters
  version: "1.0"
  questions:
    - query: Who owns the release checklist?
      expected_doc_uri: release.md
      expected_answer: The release lead owns the checklist.
      expected_relevant_citations:
        - release lead owns the checklist
""",
        encoding="utf-8",
    )
    return path


def _fake_search_report(**_: Any) -> SimpleNamespace:
    result = SimpleNamespace(
        document_uri="docs/release.md",
        text="The release lead owns the checklist and publishes the audit notes.",
        distance=0.05,
        score=0.95,
    )
    return SimpleNamespace(results=[result], total_results=1)


def test_ragas_missing_dependency_degrades(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(engine, "search_knowledge_base", _fake_search_report)
    monkeypatch.setitem(sys.modules, "ragas", None)

    run = run_evaluation(
        session=SimpleNamespace(),
        golden_path=_write_golden(tmp_path / "golden.yaml"),
        knowledge_base="kb",
        ragas_enabled=True,
    )

    ragas = run.items[0].evaluation_adapters["ragas"]
    assert ragas["enabled"] is True
    assert ragas["status"] == "degraded"
    assert ragas["degraded_reason"] == "missing_dependency"
    assert run.config_snapshot["ragas"]["enabled"] is True


def test_ragas_fake_module_records_metrics(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(engine, "search_knowledge_base", _fake_search_report)

    def evaluate_single(**kwargs: Any) -> dict[str, float]:
        assert kwargs["question"] == "Who owns the release checklist?"
        assert kwargs["contexts"] == [
            "The release lead owns the checklist and publishes the audit notes."
        ]
        return {
            "faithfulness": 0.91,
            "context_precision": 0.82,
            "context_recall": 0.73,
            "answer_relevancy": 0.64,
        }

    monkeypatch.setitem(sys.modules, "ragas", SimpleNamespace(evaluate_single=evaluate_single))

    run = run_evaluation(
        session=SimpleNamespace(),
        golden_path=_write_golden(tmp_path / "golden.yaml"),
        knowledge_base="kb",
        ragas_enabled=True,
    )

    ragas = run.items[0].evaluation_adapters["ragas"]
    assert ragas["status"] == "completed"
    assert ragas["metrics"] == {
        "faithfulness": 0.91,
        "context_precision": 0.82,
        "context_recall": 0.73,
        "answer_relevancy": 0.64,
    }
    assert "latency_ms" in ragas


def test_langfuse_disabled_is_noop() -> None:
    diagnostics = emit_langfuse_trace(
        Settings(ragrig_langfuse_enabled=False),
        name="evaluation.run",
        metadata={"api_key": "should-not-matter"},
    )

    assert diagnostics == {"enabled": False, "status": "disabled"}


def test_langfuse_missing_credentials_degrades() -> None:
    diagnostics = emit_langfuse_trace(
        Settings(ragrig_langfuse_enabled=True),
        name="evaluation.run",
        metadata={},
    )

    assert diagnostics["enabled"] is True
    assert diagnostics["status"] == "degraded"
    assert diagnostics["degraded_reason"] == "missing_credentials"


def test_langfuse_fake_client_receives_sanitized_trace() -> None:
    calls: list[dict[str, Any]] = []
    client_kwargs: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            client_kwargs.append(kwargs)

        def trace(self, **kwargs: Any) -> None:
            calls.append(kwargs)

        def flush(self) -> None:
            calls.append({"flushed": True})

    diagnostics = emit_langfuse_trace(
        Settings(
            ragrig_langfuse_enabled=True,
            ragrig_langfuse_host="https://cloud.langfuse.com",
            ragrig_langfuse_public_key="pk-test",
            ragrig_langfuse_secret_key="sk-test",
        ),
        name="retrieval.search",
        metadata={
            "knowledge_base": "kb",
            "total_results": 3,
            "secret_key": "sk-test",
        },
        client_factory=FakeClient,
    )

    assert diagnostics["status"] == "sent"
    assert client_kwargs == [
        {
            "public_key": "pk-test",
            "secret_key": "sk-test",
            "host": "https://cloud.langfuse.com",
        }
    ]
    assert calls[0]["name"] == "retrieval.search"
    assert calls[0]["metadata"]["secret_key"] == "[REDACTED]"
    assert calls[-1] == {"flushed": True}
