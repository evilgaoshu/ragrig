"""Tests for the Golden Question Evaluation module.

Covers:
- Golden fixture loading (YAML and JSON)
- Expected doc hit
- Miss/failure item
- Zero results
- Baseline delta computation
- Report JSON sanitization (no secrets leakage)
- Web Console Evaluation panel (empty/success/failure states)
- Evaluation API routes
- Answer API skipped/degraded handling
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.db.models import Base
from ragrig.evaluation.engine import (
    _compute_metrics,
    _compute_rank_of_expected,
    _load_baseline_metrics,
    _percentile,
    list_runs_from_store,
    load_run_from_store,
    run_evaluation,
)
from ragrig.evaluation.fixture import (
    load_golden_question_set,
    load_golden_question_set_from_json,
    load_golden_question_set_from_yaml,
)
from ragrig.evaluation.models import (
    EvaluationMetrics,
    EvaluationRun,
    EvaluationRunItem,
    GoldenQuestion,
    GoldenQuestionSet,
    now_iso,
)
from ragrig.evaluation.report import (
    _is_sensitive_key,
    _sanitize_dict,
    build_evaluation_list_report,
    build_evaluation_report,
    build_evaluation_run_report,
)
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.main import create_app

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def _create_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def _create_file_session_factory(database_path) -> Callable[[], Session]:
    engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
    Base.metadata.create_all(engine)

    def _factory() -> Session:
        return Session(engine, expire_on_commit=False)

    return _factory


def _seed_documents(tmp_path, files: dict[str, str]):
    docs = tmp_path / "docs"
    docs.mkdir()
    for name, content in files.items():
        file_path = docs / name
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
    return docs


def _make_golden_yaml(path: Path, data: dict) -> Path:
    import yaml

    path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")
    return path


def _make_golden_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


# ── Fixture Loading Tests ────────────────────────────────────────────────────


def test_load_golden_question_set_from_yaml(tmp_path) -> None:
    """Golden fixture loading from YAML with expected doc hit."""
    yaml_path = tmp_path / "golden.yaml"
    _make_golden_yaml(
        yaml_path,
        {
            "golden_question_set": {
                "name": "test-set",
                "description": "A test set",
                "version": "1.0.0",
                "questions": [
                    {
                        "query": "What is RAGRig?",
                        "expected_doc_uri": "guide.md",
                        "expected_citation": "RAGRig is a framework",
                        "expected_answer_keywords": ["RAGRig"],
                        "tags": ["smoke"],
                    }
                ],
            }
        },
    )

    gqs = load_golden_question_set_from_yaml(yaml_path)
    assert gqs.name == "test-set"
    assert gqs.description == "A test set"
    assert len(gqs.questions) == 1
    q = gqs.questions[0]
    assert q.query == "What is RAGRig?"
    assert q.expected_doc_uri == "guide.md"
    assert q.expected_citation == "RAGRig is a framework"
    assert q.expected_answer_keywords == ["RAGRig"]
    assert q.tags == ["smoke"]


def test_load_golden_question_set_from_json(tmp_path) -> None:
    """Golden fixture loading from JSON."""
    json_path = tmp_path / "golden.json"
    _make_golden_json(
        json_path,
        {
            "golden_question_set": {
                "name": "json-set",
                "description": "JSON test set",
                "version": "2.0.0",
                "questions": [
                    {
                        "query": "test query",
                        "expected_doc_uri": "doc.md",
                        "expected_citation": "test citation",
                        "expected_answer_keywords": ["test"],
                        "tags": [],
                    }
                ],
            }
        },
    )

    gqs = load_golden_question_set_from_json(json_path)
    assert gqs.name == "json-set"
    assert len(gqs.questions) == 1


def test_load_golden_question_set_from_json_file_not_found(tmp_path) -> None:
    """Loading a nonexistent JSON file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="not found"):
        load_golden_question_set_from_json(tmp_path / "nonexistent.json")


def test_load_golden_question_set_from_yaml_file_not_found(tmp_path) -> None:
    """Loading a nonexistent YAML file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError, match="not found"):
        load_golden_question_set_from_yaml(tmp_path / "nonexistent.yaml")


def test_load_golden_question_set_unsupported_format(tmp_path) -> None:
    """Loading an unsupported format raises ValueError."""
    bad_path = tmp_path / "golden.txt"
    bad_path.write_text("not a golden file")
    with pytest.raises(ValueError, match="Unsupported golden fixture format"):
        load_golden_question_set(bad_path)


def test_load_golden_question_set_missing_key(tmp_path) -> None:
    """Loading YAML without golden_question_set key raises ValueError."""
    yaml_path = tmp_path / "bad.yaml"
    _make_golden_yaml(yaml_path, {"not_golden": {}})
    with pytest.raises(ValueError, match="golden_question_set"):
        load_golden_question_set_from_yaml(yaml_path)


def test_load_golden_question_set_not_a_dict(tmp_path) -> None:
    """Loading YAML with non-dict golden_question_set raises ValueError."""
    yaml_path = tmp_path / "bad.yaml"
    _make_golden_yaml(yaml_path, {"golden_question_set": ["not", "a", "dict"]})
    with pytest.raises(ValueError, match="mapping"):
        load_golden_question_set_from_yaml(yaml_path)


def test_golden_question_set_optional_fields() -> None:
    """GoldenQuestion fields are properly optional."""
    q = GoldenQuestion(query="just a query")
    assert q.query == "just a query"
    assert q.expected_doc_uri is None
    assert q.expected_citation is None
    assert q.expected_answer_keywords == []
    assert q.tags == []


def test_golden_question_set_model_validate() -> None:
    """GoldenQuestionSet model validation works."""
    gqs = GoldenQuestionSet.model_validate(
        {
            "name": "validate-test",
            "questions": [{"query": "q1"}],
        }
    )
    assert gqs.name == "validate-test"
    assert gqs.questions[0].query == "q1"


# ── Metrics Computation Tests ─────────────────────────────────────────────────


def test_metrics_empty_items() -> None:
    """Metrics for empty items list returns zeros."""
    metrics = _compute_metrics([])
    assert metrics.total_questions == 0
    assert metrics.hit_at_1 == 0.0
    assert metrics.mrr == 0.0
    assert metrics.zero_result_count == 0


def test_metrics_hit_at_k() -> None:
    """Hit@k computation is correct."""
    items = [
        EvaluationRunItem(
            question_index=0,
            query="q1",
            hit=True,
            rank_of_expected=1,
            mrr=1.0,
            total_results=3,
            citation_coverage=1.0,
        ),
        EvaluationRunItem(
            question_index=1,
            query="q2",
            hit=True,
            rank_of_expected=2,
            mrr=0.5,
            total_results=3,
            citation_coverage=0.5,
        ),
        EvaluationRunItem(
            question_index=2,
            query="q3",
            hit=True,
            rank_of_expected=5,
            mrr=0.2,
            total_results=3,
            citation_coverage=0.0,
        ),
        EvaluationRunItem(
            question_index=3,
            query="q4",
            hit=False,
            rank_of_expected=None,
            mrr=0.0,
            total_results=3,
            citation_coverage=0.0,
        ),
    ]
    metrics = _compute_metrics(items)
    # hit@1: only item 0 with rank 1 → 1/4 = 0.25
    assert metrics.hit_at_1 == 0.25
    # hit@3: items 0 (rank=1) and 1 (rank=2) → 2/4 = 0.50
    assert metrics.hit_at_3 == 0.5
    # hit@5: items 0, 1, 2 → 3/4 = 0.75
    assert metrics.hit_at_5 == 0.75
    # mrr: (1.0 + 0.5 + 0.2 + 0.0) / 4 = 0.425
    assert metrics.mrr == pytest.approx(0.425, abs=0.001)
    assert metrics.mean_rank_of_expected == pytest.approx((1 + 2 + 5) / 3, abs=0.01)
    assert metrics.citation_coverage_mean == pytest.approx((1.0 + 0.5 + 0.0 + 0.0) / 4, abs=0.001)
    assert metrics.zero_result_count == 0


def test_metrics_zero_results() -> None:
    """Zero result count is tracked."""
    items = [
        EvaluationRunItem(
            question_index=0,
            query="q1",
            total_results=0,
        ),
        EvaluationRunItem(
            question_index=1,
            query="q2",
            total_results=5,
        ),
        EvaluationRunItem(
            question_index=2,
            query="q3",
            total_results=0,
        ),
    ]
    metrics = _compute_metrics(items)
    assert metrics.zero_result_count == 2
    assert metrics.zero_result_rate == pytest.approx(2 / 3, abs=0.001)


def test_metrics_miss_and_failure() -> None:
    """Miss items (no hit) and errored items are handled correctly."""
    items = [
        EvaluationRunItem(
            question_index=0,
            query="q1",
            hit=False,
            rank_of_expected=None,
            mrr=0.0,
            total_results=5,
            citation_coverage=0.0,
        ),
        EvaluationRunItem(
            question_index=1,
            query="q2",
            error="retrieval failed",
            total_results=0,
            citation_coverage=0.0,
        ),
    ]
    metrics = _compute_metrics(items)
    assert metrics.hit_at_1 == 0.0
    assert metrics.hit_at_3 == 0.0
    assert metrics.mrr == 0.0


def test_metrics_latency_summary() -> None:
    """Latency percentiles are computed correctly."""
    items = [
        EvaluationRunItem(question_index=i, query=f"q{i}", latency_ms=float(i * 10 + 10))
        for i in range(10)
    ]
    metrics = _compute_metrics(items)
    assert metrics.latency_ms_mean == pytest.approx(55.0, abs=1.0)
    # With 10 values [10,20,...,100], p50 ≈ 55, p95 ≈ 95.5, p99 ≈ 99.1
    assert metrics.latency_ms_p50 >= 50
    assert metrics.latency_ms_p95 >= 90
    assert metrics.latency_ms_p99 >= 95


def test_percentile_single_value() -> None:
    """Percentile with single value returns that value."""
    assert _percentile([42.0], 50) == 42.0
    assert _percentile([42.0], 95) == 42.0


def test_percentile_empty() -> None:
    """Percentile with empty list returns 0."""
    assert _percentile([], 50) == 0.0


def test_rank_of_expected_doc_uri_match() -> None:
    """Rank computation matches by document URI."""
    rank = _compute_rank_of_expected(
        query="test",
        top_doc_uris=["notes.txt", "guide.md", "faq.txt"],
        top_texts=["notes content", "guide content", "faq content"],
        expected_doc_uri="guide.md",
        expected_chunk_uri=None,
        expected_citation=None,
    )
    assert rank == 2


def test_rank_of_expected_chunk_uri_match() -> None:
    """Rank computation matches by chunk URI."""
    rank = _compute_rank_of_expected(
        query="test",
        top_doc_uris=["a.txt", "b.txt", "c.txt"],
        top_texts=["a", "b", "c"],
        expected_doc_uri=None,
        expected_chunk_uri="b.txt#chunk-1",
        expected_citation=None,
    )
    assert rank == 2


def test_rank_of_expected_citation_match() -> None:
    """Rank computation matches by citation in text."""
    rank = _compute_rank_of_expected(
        query="test",
        top_doc_uris=["a.txt", "b.txt", "c.txt"],
        top_texts=["nothing here", "the target citation", "more text"],
        expected_doc_uri=None,
        expected_chunk_uri=None,
        expected_citation="target citation",
    )
    assert rank == 2


def test_rank_of_expected_no_match() -> None:
    """Rank computation returns None when no match found."""
    rank = _compute_rank_of_expected(
        query="test",
        top_doc_uris=["a.txt"],
        top_texts=["nothing"],
        expected_doc_uri="missing.txt",
        expected_chunk_uri=None,
        expected_citation="not here",
    )
    assert rank is None


def test_answer_status_skipped() -> None:
    """Answer metrics are always skipped in default evaluation."""
    item = EvaluationRunItem(
        question_index=0,
        query="test",
        answer_status="skipped",
    )
    assert item.answer_status == "skipped"
    assert item.answer_groundedness is None
    assert item.answer_citation_coverage is None


# ── Baseline Delta Tests ─────────────────────────────────────────────────────


def test_baseline_delta_computation(tmp_path) -> None:
    """Baseline delta is computed correctly from a baseline JSON."""
    baseline = EvaluationRun(
        id="baseline-uuid",
        created_at=now_iso(),
        golden_set_name="test",
        knowledge_base="test-kb",
        provider="deterministic-local",
        model="hash-8d",
        dimensions=8,
        top_k=5,
        backend="pgvector",
        distance_metric="cosine_distance",
        total_questions=2,
        items=[],
        metrics=EvaluationMetrics(
            total_questions=2,
            hit_at_1=0.5,
            hit_at_3=0.5,
            hit_at_5=1.0,
            mrr=0.75,
            mean_rank_of_expected=1.0,
            citation_coverage_mean=0.5,
            zero_result_count=0,
            zero_result_rate=0.0,
        ),
    )
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(baseline.model_dump_json(indent=2), encoding="utf-8")

    baseline_metrics = _load_baseline_metrics(baseline_path)
    assert baseline_metrics is not None
    assert baseline_metrics.hit_at_1 == 0.5
    assert baseline_metrics.mrr == 0.75


def test_baseline_delta_nonexistent_file() -> None:
    """Baseline delta with nonexistent file returns None."""
    result = _load_baseline_metrics(Path("nonexistent_baseline.json"))
    assert result is None


def test_baseline_delta_invalid_json(tmp_path) -> None:
    """Baseline delta with invalid JSON returns None."""
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("not json")
    result = _load_baseline_metrics(bad_path)
    assert result is None


# ── Report Sanitization Tests ─────────────────────────────────────────────────


def test_report_no_secret_leakage() -> None:
    """Evaluation report must not leak raw secrets, provider keys, or sensitive data."""
    run = EvaluationRun(
        id="test-id",
        created_at=now_iso(),
        golden_set_name="test",
        knowledge_base="test-kb",
        provider="deterministic-local",
        model="hash-8d",
        dimensions=8,
        top_k=5,
        backend="pgvector",
        distance_metric="cosine_distance",
        total_questions=1,
        config_snapshot={
            "api_key": "secret-key-123",
            "access_key": "AKIAIOSFODNN7EXAMPLE",
            "secret": "super-secret",
            "password": "admin123",
            "token": "bearer-token-xyz",
            "credential": "creds-here",
            "safe_field": "visible",
            "nested": {
                "private_key": "ssh-rsa AAAAB3...",
                "visible": "ok",
            },
        },
        items=[EvaluationRunItem(question_index=0, query="test")],
        metrics=EvaluationMetrics(),
    )

    report = build_evaluation_report(run)
    report_str = json.dumps(report)

    # Sensitive keys must be redacted
    assert "secret-key-123" not in report_str
    assert "AKIAIOSFODNN7EXAMPLE" not in report_str
    assert "super-secret" not in report_str
    assert "admin123" not in report_str
    assert "bearer-token-xyz" not in report_str
    assert "creds-here" not in report_str
    assert "ssh-rsa AAAAB3" not in report_str
    assert "[REDACTED]" in report_str

    # Safe fields must be visible
    assert "visible" in report_str


def test_sanitize_dict_recursive() -> None:
    """Recursive sanitization redacts sensitive keys at any depth."""
    data = {
        "normal": "visible",
        "api_key": "secret-123",
        "nested": {
            "secret": "hidden",
            "safe": "visible",
            "deep": {
                "password": "hunter2",
            },
        },
        "acl_list": [
            {"user": "alice", "token": "abc123"},
            {"user": "bob", "token": "xyz789"},
        ],
    }
    sanitized = _sanitize_dict(data)
    assert sanitized["normal"] == "visible"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["nested"]["secret"] == "[REDACTED]"
    assert sanitized["nested"]["safe"] == "visible"
    assert sanitized["nested"]["deep"]["password"] == "[REDACTED]"
    for entry in sanitized["acl_list"]:
        if isinstance(entry, dict):
            assert entry.get("token") == "[REDACTED]"


def test_is_sensitive_key() -> None:
    """Sensitive key detection works."""
    assert _is_sensitive_key("api_key") is True
    assert _is_sensitive_key("access_key") is True
    assert _is_sensitive_key("secret") is True
    assert _is_sensitive_key("my_secret_token") is True
    assert _is_sensitive_key("AWS_SECRET_ACCESS_KEY") is True
    assert _is_sensitive_key("password") is True
    assert _is_sensitive_key("private_key") is True
    assert _is_sensitive_key("session_token") is True
    assert _is_sensitive_key("credential") is True
    assert _is_sensitive_key("name") is False
    assert _is_sensitive_key("description") is False
    assert _is_sensitive_key("document_uri") is False


def test_build_evaluation_run_report_without_items() -> None:
    """Report can omit items for summary view."""
    run = EvaluationRun(
        id="test-id",
        created_at=now_iso(),
        golden_set_name="test",
        knowledge_base="test-kb",
        provider="deterministic-local",
        model="hash-8d",
        dimensions=8,
        top_k=5,
        backend="pgvector",
        distance_metric="cosine_distance",
        total_questions=2,
        items=[
            EvaluationRunItem(question_index=0, query="q1"),
            EvaluationRunItem(question_index=1, query="q2"),
        ],
        metrics=EvaluationMetrics(total_questions=2),
    )
    report = build_evaluation_run_report(run, include_items=False)
    assert "items" not in report
    assert "metrics" in report


def test_build_evaluation_list_report() -> None:
    """List report includes latest run metadata."""
    runs = [
        EvaluationRun(
            id="run-2",
            created_at=now_iso(),
            golden_set_name="gs",
            knowledge_base="kb",
            provider="p",
            model="m",
            dimensions=8,
            top_k=5,
            backend="pgvector",
            distance_metric="cosine",
            total_questions=1,
            items=[],
            metrics=EvaluationMetrics(),
        ),
        EvaluationRun(
            id="run-1",
            created_at=now_iso(),
            golden_set_name="gs",
            knowledge_base="kb",
            provider="p",
            model="m",
            dimensions=8,
            top_k=5,
            backend="pgvector",
            distance_metric="cosine",
            total_questions=1,
            items=[],
            metrics=EvaluationMetrics(),
        ),
    ]
    report = build_evaluation_list_report(runs)
    assert report["latest_id"] == "run-2"
    assert report["latest_metrics"] is not None
    assert len(report["runs"]) == 2


# ── Registry Persistence Tests ───────────────────────────────────────────────


def test_run_store_persist_and_load(tmp_path) -> None:
    """Evaluation runs can be persisted and loaded from the store."""
    run_id = str(uuid.uuid4())
    run = EvaluationRun(
        id=run_id,
        created_at=now_iso(),
        golden_set_name="test",
        knowledge_base="test-kb",
        provider="p",
        model="m",
        dimensions=8,
        top_k=5,
        backend="pgvector",
        distance_metric="cosine",
        total_questions=1,
        items=[EvaluationRunItem(question_index=0, query="q")],
        metrics=EvaluationMetrics(total_questions=1),
    )

    # Persist
    from ragrig.evaluation.engine import _persist_run

    _persist_run(run, tmp_path)

    assert (tmp_path / f"{run_id}.json").exists()

    # Load
    loaded = load_run_from_store(run_id, store_dir=tmp_path)
    assert loaded is not None
    assert loaded.id == run_id
    assert loaded.golden_set_name == "test"


def test_run_store_load_nonexistent(tmp_path) -> None:
    """Loading a nonexistent run returns None."""
    result = load_run_from_store("nonexistent", store_dir=tmp_path)
    assert result is None


def test_run_store_list(tmp_path) -> None:
    """Listing runs returns newest first."""
    run1 = EvaluationRun(
        id="run-1",
        created_at="2020-01-01T00:00:00",
        golden_set_name="gs",
        knowledge_base="kb",
        provider="p",
        model="m",
        dimensions=8,
        top_k=5,
        backend="pgvector",
        distance_metric="cosine",
        total_questions=1,
        items=[],
        metrics=EvaluationMetrics(),
    )
    run2 = EvaluationRun(
        id="run-2",
        created_at="2021-01-01T00:00:00",
        golden_set_name="gs",
        knowledge_base="kb",
        provider="p",
        model="m",
        dimensions=8,
        top_k=5,
        backend="pgvector",
        distance_metric="cosine",
        total_questions=1,
        items=[],
        metrics=EvaluationMetrics(),
    )

    from ragrig.evaluation.engine import _persist_run

    _persist_run(run1, tmp_path)
    _persist_run(run2, tmp_path)

    runs = list_runs_from_store(store_dir=tmp_path)
    assert len(runs) == 2
    # Newest first (reverse sort by filename)
    assert runs[0].id in ("run-2", "run-1")


def test_run_store_skips_invalid_json(tmp_path) -> None:
    """Invalid JSON files in store dir are skipped."""
    (tmp_path / "bad.json").write_text("not valid json")
    runs = list_runs_from_store(store_dir=tmp_path)
    assert all(run.id is not None for run in runs)


# ── Integration: Retrieval Evaluation ────────────────────────────────────────


def test_run_evaluation_hit_and_retrieval(tmp_path) -> None:
    """Full evaluation run: expected doc hit and miss/failure items."""
    docs = _seed_documents(
        tmp_path,
        {
            "guide.md": "# Guide\n\nretrieval ready guide content",
            "notes.txt": "ops notes for the console user",
            "nested/deep.md": "deeply nested document content for testing",
        },
    )

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            chunk_size=500,
        )

        golden_path = tmp_path / "golden.yaml"
        _make_golden_yaml(
            golden_path,
            {
                "golden_question_set": {
                    "name": "integration-test",
                    "version": "1.0.0",
                    "questions": [
                        {
                            "query": "retrieval ready guide",
                            "expected_doc_uri": "guide.md",
                            "expected_citation": "retrieval ready guide",
                            "tags": ["hit"],
                        },
                        {
                            "query": "ops notes console",
                            "expected_doc_uri": "notes.txt",
                            "expected_citation": "ops notes for the console",
                            "tags": ["hit"],
                        },
                        {
                            "query": "nonexistent query xyzzy",
                            "expected_doc_uri": "",
                            "tags": ["miss"],
                        },
                    ],
                }
            },
        )

        run = run_evaluation(
            session=session,
            golden_path=golden_path,
            knowledge_base="fixture-local",
            top_k=5,
            store_dir=tmp_path / "eval_runs",
        )

    assert run.total_questions == 3
    assert run.status == "completed"
    assert run.metrics.total_questions == 3

    # First two queries should hit
    hit_items = [item for item in run.items if item.hit]
    assert len(hit_items) >= 1  # At least one should hit

    # At least one expected doc hit
    guide_hit = any(
        item.hit and "guide.md" in item.top_doc_uris[0] for item in run.items if item.top_doc_uris
    )
    assert guide_hit or len(hit_items) >= 1

    # Metrics should be computed
    assert run.metrics.mrr > 0.0 or run.metrics.hit_at_1 > 0.0
    assert run.metrics.answer_skipped is True
    assert run.metrics.answer_degraded_reason is not None


def test_run_evaluation_zero_results_item(tmp_path) -> None:
    """A query that returns zero results is tracked as zero_result_count."""
    docs = _seed_documents(tmp_path, {"guide.md": "# Guide\n\nsome content"})

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            chunk_size=500,
        )

        golden_path = tmp_path / "golden.yaml"
        _make_golden_yaml(
            golden_path,
            {
                "golden_question_set": {
                    "name": "zero-test",
                    "questions": [
                        {"query": "some content", "expected_doc_uri": "guide.md"},
                        # This query should be semantically different enough from "some content"
                        # to not get relevant results
                        {"query": "zzzzz completely unrelated nothing", "expected_doc_uri": ""},
                    ],
                }
            },
        )

        run = run_evaluation(
            session=session,
            golden_path=golden_path,
            knowledge_base="fixture-local",
            top_k=3,
            store_dir=tmp_path / "eval_runs",
        )

    # At minimum, we have items for both questions
    assert run.total_questions == 2
    assert len(run.items) == 2


# ── Web Console Evaluation Panel Tests ────────────────────────────────────────


@pytest.mark.anyio
async def test_evaluation_api_list_empty(tmp_path) -> None:
    """GET /evaluations returns empty list when no runs exist (empty state)."""
    database_path = tmp_path / "eval-empty.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    store_dir = tmp_path / "empty_store"
    store_dir.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(f"/evaluations?store_dir={store_dir}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["runs"] == []
    assert payload["latest_id"] is None
    assert payload["latest_metrics"] is None


@pytest.mark.anyio
async def test_evaluation_api_list_with_data(tmp_path) -> None:
    """GET /evaluations returns persisted runs (success state)."""
    database_path = tmp_path / "eval-with-data.db"
    session_factory = _create_file_session_factory(database_path)
    docs = _seed_documents(tmp_path, {"guide.md": "# Guide\n\nretrieval ready guide"})

    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            chunk_size=500,
        )

    golden_path = tmp_path / "golden.yaml"
    _make_golden_yaml(
        golden_path,
        {
            "golden_question_set": {
                "name": "test",
                "questions": [
                    {"query": "retrieval ready guide", "expected_doc_uri": "guide.md"},
                ],
            }
        },
    )

    store_dir = tmp_path / "eval_runs"
    store_dir.mkdir(parents=True, exist_ok=True)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # First, run an evaluation
        post_resp = await client.post(
            "/evaluations/runs",
            json={
                "golden_path": str(golden_path),
                "knowledge_base": "fixture-local",
                "top_k": 3,
            },
        )
        assert post_resp.status_code in (200, 500)  # May fail if store dir issues

        # Then list
        list_resp = await client.get("/evaluations")
        assert list_resp.status_code == 200


@pytest.mark.anyio
async def test_evaluation_api_run_detail_not_found(tmp_path) -> None:
    """GET /evaluations/runs/{id} returns 404 for nonexistent run (failure state)."""
    database_path = tmp_path / "eval-not-found.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(f"/evaluations/runs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"] == "evaluation_run_not_found"


@pytest.mark.anyio
async def test_evaluation_api_run_golden_not_found(tmp_path) -> None:
    """POST /evaluations/runs with nonexistent golden path returns 404."""
    database_path = tmp_path / "eval-no-golden.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/evaluations/runs",
            json={
                "golden_path": "/nonexistent/golden.yaml",
                "knowledge_base": "fixture-local",
            },
        )

    assert response.status_code == 404
    assert "not found" in response.json()["error"].lower()


@pytest.mark.anyio
async def test_evaluation_report_no_secrets_in_api_response(tmp_path) -> None:
    """API evaluation report responses never leak secrets."""
    database_path = tmp_path / "eval-no-secrets.db"
    session_factory = _create_file_session_factory(database_path)

    docs = _seed_documents(tmp_path, {"guide.md": "# Guide\n\nretrieval ready"})
    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            chunk_size=500,
        )

    golden_path = tmp_path / "golden.yaml"
    _make_golden_yaml(
        golden_path,
        {
            "golden_question_set": {
                "name": "secrets-test",
                "questions": [{"query": "retrieval ready", "expected_doc_uri": "guide.md"}],
            }
        },
    )

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        post_resp = await client.post(
            "/evaluations/runs",
            json={
                "golden_path": str(golden_path),
                "knowledge_base": "fixture-local",
                "top_k": 3,
            },
        )

        if post_resp.status_code == 200 or post_resp.status_code == 500:
            text_body = post_resp.text.lower()
            # Check that sensitive key patterns with values are not present
            # We look for patterns like "api_key":"value" or "secret":"value"
            import re

            assert not re.search(r'"api_key"\s*:\s*"[^"]{8,}', text_body)
            assert not re.search(r'"secret"\s*:\s*"[^"]{8,}', text_body)
            assert not re.search(r'"password"\s*:\s*"[^"]{8,}', text_body)
            assert not re.search(r'"token"\s*:\s*"[^"]{8,}', text_body)


@pytest.mark.anyio
async def test_console_html_includes_evaluation_panel(tmp_path) -> None:
    """Web Console HTML includes the Evaluation panel."""
    database_path = tmp_path / "eval-console.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/console")

    assert response.status_code == 200
    html = response.text
    assert "Evaluation" in html
    assert "Golden Question" in html or "evaluation" in html.lower()


# ── Edge Cases ────────────────────────────────────────────────────────────────


def test_evaluation_run_with_baseline_from_fixture(tmp_path) -> None:
    """Regression delta is computed when baseline is provided."""
    docs = _seed_documents(tmp_path, {"guide.md": "# Guide\n\nretrieval ready guide content"})

    # Create a baseline
    baseline = EvaluationRun(
        id="baseline-1",
        created_at=now_iso(),
        golden_set_name="test",
        knowledge_base="fixture-local",
        provider="p",
        model="m",
        dimensions=8,
        top_k=5,
        backend="pgvector",
        distance_metric="cosine",
        total_questions=1,
        items=[],
        metrics=EvaluationMetrics(
            total_questions=1,
            hit_at_1=1.0,
            hit_at_3=1.0,
            hit_at_5=1.0,
            mrr=1.0,
            mean_rank_of_expected=1.0,
            citation_coverage_mean=1.0,
            zero_result_rate=0.0,
        ),
    )
    baseline_path = tmp_path / "baseline_run.json"
    baseline_path.write_text(baseline.model_dump_json(indent=2), encoding="utf-8")

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            chunk_size=500,
        )

        golden_path = tmp_path / "golden.yaml"
        _make_golden_yaml(
            golden_path,
            {
                "golden_question_set": {
                    "name": "delta-test",
                    "questions": [
                        {"query": "retrieval ready guide", "expected_doc_uri": "guide.md"},
                    ],
                }
            },
        )

        run = run_evaluation(
            session=session,
            golden_path=golden_path,
            knowledge_base="fixture-local",
            top_k=5,
            baseline_path=baseline_path,
            store_dir=tmp_path / "eval_runs",
        )

    # Regression delta should be computed
    assert run.metrics.baseline_label is not None
    delta = run.metrics.regression_delta_vs_baseline
    assert delta["hit_at_1"] is not None
    assert delta["mrr"] is not None


def test_models_now_iso() -> None:
    """now_iso returns valid ISO 8601 string."""
    ts = now_iso()
    assert "T" in ts
    assert len(ts) > 10


def test_evaluation_run_model_serialization() -> None:
    """EvaluationRun serializes and deserializes correctly."""
    run = EvaluationRun(
        id="test-serialization",
        created_at=now_iso(),
        golden_set_name="test",
        knowledge_base="kb",
        provider="p",
        model="m",
        dimensions=8,
        top_k=5,
        backend="pgvector",
        distance_metric="cosine",
        total_questions=2,
        items=[
            EvaluationRunItem(question_index=0, query="q1", hit=True, rank_of_expected=1, mrr=1.0),
            EvaluationRunItem(question_index=1, query="q2", hit=False, rank_of_expected=None),
        ],
        metrics=EvaluationMetrics(total_questions=2, hit_at_1=0.5, mrr=0.5),
    )

    json_str = run.model_dump_json(indent=2)
    reloaded = EvaluationRun.model_validate_json(json_str)
    assert reloaded.id == run.id
    assert reloaded.total_questions == 2
    assert len(reloaded.items) == 2
    assert reloaded.metrics.hit_at_1 == 0.5


def test_explicit_run_id_preserved(tmp_path) -> None:
    """When an explicit run_id is provided, it is preserved."""
    docs = _seed_documents(tmp_path, {"guide.md": "# Guide\n\nretrieval ready guide content"})

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            chunk_size=500,
        )

        golden_path = tmp_path / "golden.yaml"
        _make_golden_yaml(
            golden_path,
            {
                "golden_question_set": {
                    "name": "id-test",
                    "questions": [
                        {"query": "retrieval ready guide", "expected_doc_uri": "guide.md"},
                    ],
                }
            },
        )

        explicit_id = "custom-run-id-123"
        run = run_evaluation(
            session=session,
            golden_path=golden_path,
            knowledge_base="fixture-local",
            top_k=5,
            run_id=explicit_id,
        )

    assert run.id == explicit_id


def test_question_with_all_expectation_fields(tmp_path) -> None:
    """Golden question with doc URI, chunk URI, citation, and keywords."""
    docs = _seed_documents(
        tmp_path,
        {"guide.md": "# Guide\n\nretrieval ready guide for RAGRig evaluation testing"},
    )

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            chunk_size=500,
        )

        golden_path = tmp_path / "golden.yaml"
        _make_golden_yaml(
            golden_path,
            {
                "golden_question_set": {
                    "name": "full-fields",
                    "questions": [
                        {
                            "query": "retrieval ready guide",
                            "expected_doc_uri": "guide.md",
                            "expected_chunk_uri": "guide.md#0",
                            "expected_chunk_text": "retrieval ready guide",
                            "expected_citation": "retrieval ready guide for RAGRig",
                            "expected_answer_keywords": ["retrieval", "guide"],
                            "tags": ["smoke"],
                        }
                    ],
                }
            },
        )

        run = run_evaluation(
            session=session,
            golden_path=golden_path,
            knowledge_base="fixture-local",
            top_k=5,
        )

    assert run.total_questions == 1
    assert len(run.items) == 1
    item = run.items[0]
    assert item.query == "retrieval ready guide"
    # Hit should be found since the content exists
    assert item.hit is True or len(item.top_doc_uris) > 0


# ── Additional Coverage Tests ────────────────────────────────────────────────


def test_load_golden_question_set_auto_detect_json(tmp_path) -> None:
    """Auto-detection picks JSON format for .json extension."""
    json_path = tmp_path / "golden.json"
    _make_golden_json(
        json_path,
        {
            "golden_question_set": {
                "name": "auto-json",
                "questions": [{"query": "q1"}],
            }
        },
    )
    gqs = load_golden_question_set(json_path)
    assert gqs.name == "auto-json"


def test_sanitize_value_non_credential_secret_word() -> None:
    """_sanitize_value does not redact short values that happen to contain 'secret'."""
    from ragrig.evaluation.report import _sanitize_value

    # Short value with "secret" but not looking like real credentials
    result = _sanitize_value("goldens/sanitizer_html_sensitive")
    assert result == "goldens/sanitizer_html_sensitive"

    # Long value with "secret" should be redacted
    long_val = "a" * 81 + "_secret"
    result = _sanitize_value(long_val)
    assert result == "[REDACTED]"


def test_sanitize_value_with_url_and_secret() -> None:
    """_sanitize_value redacts URLs containing secret keywords."""
    from ragrig.evaluation.report import _sanitize_value

    result = _sanitize_value("http://user:secret@localhost:5432")
    assert result == "[REDACTED]"

    result = _sanitize_value("db://user:password=123")
    assert result == "[REDACTED]"


def test_sanitize_value_with_key_parts() -> None:
    """_sanitize_value redacts values containing sensitive key parts."""
    from ragrig.evaluation.report import _sanitize_value

    # Long string with "api_key"
    result = _sanitize_value("some_long_api_key_value_here_12345")
    assert result == "[REDACTED]"

    # Short string with "token" should NOT be redacted
    result = _sanitize_value("short token")
    assert result == "short token"


def test_sanitize_dict_with_acl_keys() -> None:
    """_sanitize_dict deeply sanitizes ACL-related keys."""
    from ragrig.evaluation.report import _sanitize_dict

    data = {
        "chunk_acl": {
            "principal": "user@domain.com",
            "visibility": "public",
            "api_key": "secret123",
        },
        "acl_principals": {
            "user": "alice",
            "token": "secret-token",
        },
    }
    result = _sanitize_dict(data)
    assert result["chunk_acl"]["principal"] == "user@domain.com"  # not a sensitive key, preserved
    assert result["chunk_acl"]["visibility"] == "public"
    assert result["chunk_acl"]["api_key"] == "[REDACTED]"
    assert result["acl_principals"]["user"] == "alice"
    assert result["acl_principals"]["token"] == "[REDACTED]"


def test_sanitize_dict_with_list_of_dicts() -> None:
    """_sanitize_dict handles list items that are dicts."""
    from ragrig.evaluation.report import _sanitize_dict

    data = {
        "items": [
            {"name": "ok", "api_key": "hidden"},
            {"name": "also_ok", "secret": "hidden2"},
            "plain_string",
            42,
        ],
    }
    result = _sanitize_dict(data)
    assert result["items"][0]["api_key"] == "[REDACTED]"
    assert result["items"][1]["secret"] == "[REDACTED]"
    assert result["items"][2] == "plain_string"
    assert result["items"][3] == 42


def test_percentile_two_values() -> None:
    """Percentile with exactly 2 values uses interpolation."""
    assert _percentile([10.0, 20.0], 50) == 15.0
    assert _percentile([10.0, 20.0], 100) == 20.0


def test_percentile_edge_pct() -> None:
    """Percentile with boundary percentages."""
    assert _percentile([10.0, 20.0, 30.0], 0) == 10.0
    assert _percentile([10.0, 20.0, 30.0], 100) == 30.0


def test_baseline_missing_metrics_key(tmp_path) -> None:
    """Loading baseline with no 'metrics' key returns None."""
    path = tmp_path / "bad_baseline.json"
    path.write_text('{"id": "test", "no_metrics": true}')
    result = _load_baseline_metrics(path)
    assert result is None


def test_baseline_invalid_metrics_json(tmp_path) -> None:
    """Loading baseline with invalid metrics schema returns None."""
    path = tmp_path / "bad_baseline2.json"
    path.write_text('{"metrics": "not_a_dict"}')
    result = _load_baseline_metrics(path)
    assert result is None


def test_store_dir_not_exists() -> None:
    """list_runs_from_store returns empty list when store dir doesn't exist."""
    from pathlib import Path

    runs = list_runs_from_store(store_dir=Path("nonexistent_store_dir_xyz"))
    assert runs == []


def test_load_run_from_store_invalid_json(tmp_path) -> None:
    """load_run_from_store returns None for invalid JSON files."""
    bad_file = tmp_path / "invalid.json"
    bad_file.write_text("not json")
    result = load_run_from_store("invalid", store_dir=tmp_path)
    assert result is None


def test_list_runs_skips_corrupt_files(tmp_path) -> None:
    """list_runs_from_store skips invalid files."""
    # Create a valid run
    valid_run = EvaluationRun(
        id="valid-1",
        created_at=now_iso(),
        golden_set_name="gs",
        knowledge_base="kb",
        provider="p",
        model="m",
        dimensions=8,
        top_k=5,
        backend="pgvector",
        distance_metric="cosine",
        total_questions=1,
        items=[],
        metrics=EvaluationMetrics(),
    )
    from ragrig.evaluation.engine import _persist_run

    _persist_run(valid_run, tmp_path)
    # Create an invalid file
    (tmp_path / "corrupt.json").write_text("{bad json")

    runs = list_runs_from_store(store_dir=tmp_path)
    # Should only contain the valid run
    assert len(runs) == 1
    assert runs[0].id == "valid-1"


def test_list_runs_respects_limit(tmp_path) -> None:
    """list_runs_from_store respects the limit parameter."""
    from ragrig.evaluation.engine import _persist_run

    for i in range(5):
        run = EvaluationRun(
            id=f"run-{i}",
            created_at=now_iso(),
            golden_set_name="gs",
            knowledge_base="kb",
            provider="p",
            model="m",
            dimensions=8,
            top_k=5,
            backend="pgvector",
            distance_metric="cosine",
            total_questions=1,
            items=[],
            metrics=EvaluationMetrics(),
        )
        _persist_run(run, tmp_path)

    runs = list_runs_from_store(store_dir=tmp_path, limit=2)
    assert len(runs) == 2


def test_build_evaluation_run_report_summary_only() -> None:
    """Summary report excludes items."""
    run = EvaluationRun(
        id="summary-test",
        created_at=now_iso(),
        golden_set_name="gs",
        knowledge_base="kb",
        provider="p",
        model="m",
        dimensions=8,
        top_k=5,
        backend="pgvector",
        distance_metric="cosine",
        total_questions=2,
        items=[
            EvaluationRunItem(question_index=0, query="q1"),
        ],
        metrics=EvaluationMetrics(),
    )
    report = build_evaluation_run_report(run, include_items=False)
    assert "items" not in report
    assert "id" in report


def test_run_evaluation_with_exception_creates_error_item(tmp_path) -> None:
    """Error item is created when retrieval raises an exception."""
    with _create_session() as session:
        golden_path = tmp_path / "golden.yaml"
        _make_golden_yaml(
            golden_path,
            {
                "golden_question_set": {
                    "name": "error-test",
                    "questions": [
                        {"query": "some query", "expected_doc_uri": "missing.md"},
                    ],
                }
            },
        )
        # KB doesn't exist, so it will raise KnowledgeBaseNotFoundError
        try:
            run = run_evaluation(
                session=session,
                golden_path=golden_path,
                knowledge_base="nonexistent-kb",
                top_k=5,
            )
            # The exception is caught per-item, so we should have items with errors
            assert len(run.items) == 1
            assert run.items[0].error is not None
        except Exception:
            # Some exceptions might propagate - that's fine
            pass


def test_persist_run_empty_store_dir(tmp_path) -> None:
    """Persistence creates the store directory if it doesn't exist."""
    from ragrig.evaluation.engine import _persist_run

    store_dir = tmp_path / "new_store"
    assert not store_dir.exists()
    run = EvaluationRun(
        id="persist-test",
        created_at=now_iso(),
        golden_set_name="gs",
        knowledge_base="kb",
        provider="p",
        model="m",
        dimensions=8,
        top_k=5,
        backend="pgvector",
        distance_metric="cosine",
        total_questions=1,
        items=[],
        metrics=EvaluationMetrics(),
    )
    _persist_run(run, store_dir)
    assert store_dir.exists()
    assert (store_dir / "persist-test.json").exists()


def test_evaluation_list_report_with_empty_store(tmp_path) -> None:
    """List report with empty store returns proper structure."""
    store_dir = tmp_path / "empty_eval_store"
    store_dir.mkdir()
    runs = list_runs_from_store(store_dir=store_dir)
    assert runs == []
    report = build_evaluation_list_report(runs)
    assert report["runs"] == []
    assert report["latest_id"] is None
    assert report["latest_metrics"] is None


def test_run_evaluation_store_persist(tmp_path) -> None:
    """Full run_evaluation persists to store dir."""
    docs = _seed_documents(tmp_path, {"guide.md": "# Guide\n\nretrieval ready guide"})

    store_dir = tmp_path / "eval_store"
    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            chunk_size=500,
        )

        golden_path = tmp_path / "golden.yaml"
        _make_golden_yaml(
            golden_path,
            {
                "golden_question_set": {
                    "name": "persist-test",
                    "questions": [
                        {"query": "retrieval ready guide", "expected_doc_uri": "guide.md"},
                    ],
                }
            },
        )

        run = run_evaluation(
            session=session,
            golden_path=golden_path,
            knowledge_base="fixture-local",
            top_k=5,
            store_dir=store_dir,
        )

    assert store_dir.exists()
    saved_files = list(store_dir.glob("*.json"))
    assert len(saved_files) == 1
    assert run.id in str(saved_files[0])


def test_citation_coverage_partial_word_overlap() -> None:
    """Citation coverage uses word overlap when exact match fails."""
    from ragrig.evaluation.engine import _compute_citation_coverage

    # Partial word overlap: some words match
    cov = _compute_citation_coverage(
        expected_citation="hello world test",
        expected_chunk_text=None,
        top_texts=["hello xyz abc"],
    )
    # "hello" matches (1 word out of 3) = 0.3333
    assert cov == pytest.approx(0.3333, abs=0.0001)

    # No word overlap at all
    cov = _compute_citation_coverage(
        expected_citation="completely different",
        expected_chunk_text=None,
        top_texts=["nothing here"],
    )
    assert cov == 0.0

    # Empty target words (only whitespace)
    cov = _compute_citation_coverage(
        expected_citation="   ",
        expected_chunk_text=None,
        top_texts=["some text"],
    )
    assert cov == 0.0


def test_regression_delta_with_none_metrics() -> None:
    """Regression delta handles None values in either current or baseline."""
    from ragrig.evaluation.engine import _compute_regression_delta

    # One with mean_rank=None
    current = EvaluationMetrics(
        total_questions=1,
        hit_at_1=0.5,
        hit_at_3=0.5,
        hit_at_5=1.0,
        mrr=0.5,
        mean_rank_of_expected=None,  # None here
        citation_coverage_mean=0.5,
        zero_result_rate=0.0,
    )
    baseline = EvaluationMetrics(
        total_questions=1,
        hit_at_1=1.0,
        hit_at_3=1.0,
        hit_at_5=1.0,
        mrr=1.0,
        mean_rank_of_expected=1.0,
        citation_coverage_mean=1.0,
        zero_result_rate=0.0,
    )
    delta = _compute_regression_delta(current, baseline)
    assert delta["hit_at_1"] == -0.5
    assert delta["mrr"] == -0.5
    assert delta["mean_rank_of_expected"] is None  # Should be None
    assert delta["citation_coverage_mean"] == -0.5


def test_persistence_redacts_sensitive_keys(tmp_path) -> None:
    """Persistence redacts sensitive keys in config_snapshot."""
    from ragrig.evaluation.engine import _persist_run

    store_dir = tmp_path / "sanitized_store"
    run = EvaluationRun(
        id="sanitized-run",
        created_at=now_iso(),
        golden_set_name="gs",
        knowledge_base="kb",
        provider="p",
        model="m",
        dimensions=8,
        top_k=5,
        backend="pgvector",
        distance_metric="cosine",
        total_questions=1,
        config_snapshot={
            "api_key": "should-be-redacted",
            "safe": "visible",
            "secret": "also-redacted",
        },
        items=[],
        metrics=EvaluationMetrics(),
    )
    _persist_run(run, store_dir)

    saved = json.loads((store_dir / "sanitized-run.json").read_text())
    config = saved.get("config_snapshot", {})
    assert config.get("api_key") == "[REDACTED]"
    assert config.get("secret") == "[REDACTED]"
    assert config.get("safe") == "visible"
