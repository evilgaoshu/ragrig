"""Unit tests for optional evaluation/observability adapters."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ragrig.config import Settings
from ragrig.evaluation import engine
from ragrig.evaluation.adapters.ragas import _as_mapping, evaluate_ragas_item
from ragrig.evaluation.engine import run_evaluation
from ragrig.observability.langfuse import _load_langfuse_factory, emit_langfuse_trace

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


def test_ragas_disabled_direct_call_is_stable() -> None:
    assert evaluate_ragas_item(
        enabled=False,
        question="ignored",
        contexts=[],
        answer=None,
        reference=None,
    ) == {"enabled": False, "status": "disabled"}


def test_ragas_evaluate_fallback_and_score_coercion(monkeypatch) -> None:
    def evaluate(rows: list[dict[str, Any]]) -> SimpleNamespace:
        assert rows[0]["ground_truth"] == "reference"
        return SimpleNamespace(
            scores=[
                {
                    "faithfulness": "0.92555",
                    "answer_relevance": "0.5",
                    "context_precision": "not-a-number",
                }
            ]
        )

    monkeypatch.setitem(sys.modules, "fake_ragas_eval", SimpleNamespace(evaluate=evaluate))

    result = evaluate_ragas_item(
        enabled=True,
        module_name="fake_ragas_eval",
        question="q",
        contexts=["ctx"],
        answer=None,
        reference="reference",
        metrics=["faithfulness", "answer_relevancy", "context_precision"],
    )

    assert result["status"] == "completed"
    assert result["metrics"] == {"faithfulness": 0.9255, "answer_relevancy": 0.5}


def test_ragas_adapter_error_when_module_lacks_supported_api(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "fake_ragas_empty", SimpleNamespace())

    result = evaluate_ragas_item(
        enabled=True,
        module_name="fake_ragas_empty",
        question="q",
        contexts=[],
        answer="a",
        reference=None,
    )

    assert result["status"] == "degraded"
    assert result["degraded_reason"] == "adapter_error"
    assert result["error"] == "RuntimeError"


def test_ragas_result_mapping_supports_pandas_like_results() -> None:
    class FakeIloc:
        def __getitem__(self, index: int) -> SimpleNamespace:
            assert index == 0
            return SimpleNamespace(to_dict=lambda: {"faithfulness": 0.7})

    class FakeFrame:
        empty = False
        iloc = FakeIloc()

    result = _as_mapping(SimpleNamespace(to_pandas=lambda: FakeFrame()))

    assert result == {"faithfulness": 0.7}


def test_ragas_result_mapping_supports_scores_mapping_and_object_dict() -> None:
    assert _as_mapping(SimpleNamespace(scores={"context_recall": 0.8})) == {"context_recall": 0.8}

    class ScoreObject:
        def __init__(self) -> None:
            self.answer_correctness = 0.6

    assert _as_mapping(ScoreObject()) == {"answer_correctness": 0.6}


def test_ragas_result_mapping_rejects_unsupported_result() -> None:
    with pytest.raises(TypeError, match="unsupported RAGAS result type"):
        _as_mapping(1.23)


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


def test_langfuse_missing_dependency_degrades(monkeypatch) -> None:
    import ragrig.observability.langfuse as langfuse_adapter

    def missing_module(name: str) -> object:
        assert name == "langfuse"
        raise ModuleNotFoundError(name)

    monkeypatch.setattr(langfuse_adapter.importlib, "import_module", missing_module)

    diagnostics = emit_langfuse_trace(
        Settings(
            ragrig_langfuse_enabled=True,
            ragrig_langfuse_public_key="pk-test",
            ragrig_langfuse_secret_key="sk-test",
        ),
        name="answer.generation",
    )

    assert diagnostics["status"] == "degraded"
    assert diagnostics["degraded_reason"] == "missing_dependency"
    assert diagnostics["error"] == "ModuleNotFoundError"


def test_langfuse_start_trace_fallback_and_io_sanitization() -> None:
    calls: list[dict[str, Any]] = []

    class FakeClient:
        def __init__(self, **_: Any) -> None:
            pass

        def start_trace(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    diagnostics = emit_langfuse_trace(
        Settings(
            ragrig_langfuse_enabled=True,
            ragrig_langfuse_public_key="pk-test",
            ragrig_langfuse_secret_key="sk-test",
        ),
        name="evaluation.run",
        input_metadata={"api_key": "input-secret"},
        output_metadata={"token": "output-secret"},
        client_factory=FakeClient,
    )

    assert diagnostics["status"] == "sent"
    assert calls[0]["input"]["api_key"] == "[REDACTED]"
    assert calls[0]["output"]["token"] == "[REDACTED]"


def test_langfuse_adapter_error_when_client_has_no_trace_api() -> None:
    class FakeClient:
        def __init__(self, **_: Any) -> None:
            pass

    diagnostics = emit_langfuse_trace(
        Settings(
            ragrig_langfuse_enabled=True,
            ragrig_langfuse_public_key="pk-test",
            ragrig_langfuse_secret_key="sk-test",
        ),
        name="retrieval.search",
        client_factory=FakeClient,
    )

    assert diagnostics["status"] == "degraded"
    assert diagnostics["degraded_reason"] == "adapter_error"
    assert diagnostics["error"] == "RuntimeError"


def test_langfuse_factory_loader(monkeypatch) -> None:
    import ragrig.observability.langfuse as langfuse_adapter

    class FakeLangfuse:
        pass

    monkeypatch.setattr(
        langfuse_adapter.importlib,
        "import_module",
        lambda name: SimpleNamespace(Langfuse=FakeLangfuse),
    )

    assert _load_langfuse_factory() is FakeLangfuse


def test_langfuse_factory_loader_rejects_module_without_client(monkeypatch) -> None:
    import ragrig.observability.langfuse as langfuse_adapter

    monkeypatch.setattr(
        langfuse_adapter.importlib,
        "import_module",
        lambda name: SimpleNamespace(Langfuse=None),
    )

    with pytest.raises(RuntimeError, match="does not expose Langfuse"):
        _load_langfuse_factory()
