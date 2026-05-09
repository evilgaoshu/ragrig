"""Evaluation engine: run golden questions through retrieval and compute metrics.

The engine orchestrates:
1. Loading a golden question set
2. Running each query through the retrieval system
3. Computing per-item results (hit, rank, citation coverage)
4. Aggregating metrics (hit@k, MRR, latency summary)
5. Loading baseline and computing regression delta
6. Persisting the evaluation run to a JSON file store
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ragrig.evaluation.fixture import load_golden_question_set
from ragrig.evaluation.models import (
    EvaluationMetrics,
    EvaluationRun,
    EvaluationRunItem,
    GoldenQuestionSet,
    now_iso,
)
from ragrig.retrieval import search_knowledge_base

DEFAULT_EVAL_DIR = Path("evaluation_runs")


def _compute_rank_of_expected(
    query: str,
    top_doc_uris: list[str],
    expected_doc_uri: str | None,
    expected_chunk_uri: str | None,
    expected_citation: str | None,
    top_texts: list[str],
) -> int | None:
    """Find the rank (1-based) of the first expected match in results."""
    for i, (uri, text) in enumerate(zip(top_doc_uris, top_texts, strict=False)):
        rank = i + 1
        if expected_doc_uri is not None and expected_doc_uri in uri:
            return rank
        if expected_chunk_uri is not None and (
            expected_chunk_uri in uri or uri in expected_chunk_uri
        ):
            return rank
        if expected_citation is not None and expected_citation.lower() in text.lower():
            return rank
    return None


def _compute_citation_coverage(
    expected_citation: str | None,
    expected_chunk_text: str | None,
    top_texts: list[str],
) -> float:
    """Compute citation coverage: fraction of expected text found in results."""
    target = expected_citation or expected_chunk_text
    if not target:
        return 0.0
    target_lower = target.lower()
    for text in top_texts:
        if target_lower in text.lower():
            return 1.0
    # Partial match: word overlap
    target_words = set(target_lower.split())
    if not target_words:
        return 0.0
    all_words = set()
    for text in top_texts:
        all_words.update(text.lower().split())
    overlap = target_words & all_words
    return round(len(overlap) / len(target_words), 4)


def _evaluate_question(
    session: Session,
    question_index: int,
    golden: Any,
    knowledge_base: str,
    top_k: int,
    provider_override: str | None = None,
    model_override: str | None = None,
    dimensions_override: int | None = None,
) -> EvaluationRunItem:
    """Run a single golden question through retrieval and compute per-item metrics."""
    start = time.perf_counter()
    try:
        report = search_knowledge_base(
            session=session,
            knowledge_base_name=knowledge_base,
            query=golden.query,
            top_k=top_k,
            provider=provider_override,
            model=model_override,
            dimensions=dimensions_override,
        )
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

        doc_uris = [r.document_uri for r in report.results]
        text_previews = [r.text_preview for r in report.results]
        distances = [r.distance for r in report.results]
        scores = [r.score for r in report.results]

        rank = _compute_rank_of_expected(
            golden.query,
            doc_uris,
            golden.expected_doc_uri,
            golden.expected_chunk_uri,
            golden.expected_citation,
            text_previews,
        )
        hit = rank is not None and rank <= top_k

        citation_cov = _compute_citation_coverage(
            golden.expected_citation,
            golden.expected_chunk_text,
            text_previews,
        )

        mrr = 1.0 / rank if rank is not None and rank > 0 else 0.0

        return EvaluationRunItem(
            question_index=question_index,
            query=golden.query,
            hit=hit,
            rank_of_expected=rank,
            mrr=mrr,
            total_results=report.total_results,
            citation_coverage=citation_cov,
            answer_status="skipped",
            latency_ms=elapsed_ms,
            top_doc_uris=doc_uris,
            top_distances=distances,
            top_scores=scores,
        )
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        return EvaluationRunItem(
            question_index=question_index,
            query=golden.query,
            error=str(exc),
            latency_ms=elapsed_ms,
            answer_status="skipped",
        )


def _percentile(sorted_values: list[float], pct: float) -> float:
    """Compute a percentile from sorted values."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (pct / 100.0) * (len(sorted_values) - 1)
    f = int(k)
    c = k - f
    if f + 1 < len(sorted_values):
        return sorted_values[f] + c * (sorted_values[f + 1] - sorted_values[f])
    return sorted_values[-1]


def _compute_metrics(items: list[EvaluationRunItem]) -> EvaluationMetrics:
    """Aggregate per-item results into summary metrics."""
    total = len(items)
    if total == 0:
        return EvaluationMetrics()

    hit_items = [item for item in items if item.error is None]

    hit_at_1 = sum(1 for item in hit_items if item.hit and item.rank_of_expected == 1) / total
    hit_at_3 = (
        sum(
            1
            for item in hit_items
            if item.hit and item.rank_of_expected is not None and item.rank_of_expected <= 3
        )
        / total
    )
    hit_at_5 = (
        sum(
            1
            for item in hit_items
            if item.hit and item.rank_of_expected is not None and item.rank_of_expected <= 5
        )
        / total
    )

    mrr = sum(item.mrr for item in hit_items) / total if total else 0.0

    ranks = [item.rank_of_expected for item in hit_items if item.rank_of_expected is not None]
    mean_rank = sum(ranks) / len(ranks) if ranks else None

    citation_mean = sum(item.citation_coverage for item in hit_items) / total if total else 0.0

    zero_results = sum(1 for item in items if item.total_results == 0)

    latencies = sorted(item.latency_ms for item in items)
    latency_mean = sum(latencies) / total if total else 0.0

    return EvaluationMetrics(
        total_questions=total,
        hit_at_1=round(hit_at_1, 4),
        hit_at_3=round(hit_at_3, 4),
        hit_at_5=round(hit_at_5, 4),
        mrr=round(mrr, 4),
        mean_rank_of_expected=round(mean_rank, 2) if mean_rank is not None else None,
        citation_coverage_mean=round(citation_mean, 4),
        zero_result_count=zero_results,
        zero_result_rate=round(zero_results / total, 4) if total else 0.0,
        latency_ms_mean=round(latency_mean, 2),
        latency_ms_p50=round(_percentile(latencies, 50), 2),
        latency_ms_p95=round(_percentile(latencies, 95), 2),
        latency_ms_p99=round(_percentile(latencies, 99), 2),
        answer_skipped=True,
        answer_degraded_reason="answer API not available in default local evaluation",
    )


def run_evaluation(
    session: Session,
    golden_path: Path,
    knowledge_base: str,
    top_k: int = 5,
    provider: str | None = None,
    model: str | None = None,
    dimensions: int | None = None,
    baseline_path: Path | None = None,
    run_id: str | None = None,
    store_dir: Path | None = None,
) -> EvaluationRun:
    """Run a full evaluation against a golden question set.

    Args:
        session: Database session for retrieval queries.
        golden_path: Path to YAML/JSON golden question set fixture.
        knowledge_base: Name of the knowledge base to query.
        top_k: Number of results to retrieve per query.
        provider: Optional provider override for retrieval.
        model: Optional model override for retrieval.
        dimensions: Optional dimensions override for retrieval.
        baseline_path: Optional path to a baseline evaluation run JSON for
            regression delta computation.
        run_id: Optional explicit run ID (generated if not provided).
        store_dir: Optional directory to persist the evaluation run JSON.

    Returns:
        An EvaluationRun with all items and aggregated metrics.
    """
    golden_set = load_golden_question_set(golden_path)
    return _run_evaluation_with_set(
        session=session,
        golden_set=golden_set,
        knowledge_base=knowledge_base,
        top_k=top_k,
        provider=provider,
        model=model,
        dimensions=dimensions,
        baseline_path=baseline_path,
        run_id=run_id,
        store_dir=store_dir,
    )


def _run_evaluation_with_set(
    session: Session,
    golden_set: GoldenQuestionSet,
    knowledge_base: str,
    top_k: int = 5,
    provider: str | None = None,
    model: str | None = None,
    dimensions: int | None = None,
    baseline_path: Path | None = None,
    run_id: str | None = None,
    store_dir: Path | None = None,
) -> EvaluationRun:
    """Internal: run evaluation with an already-loaded GoldenQuestionSet."""
    run_id = run_id or str(uuid.uuid4())

    items: list[EvaluationRunItem] = []
    for i, question in enumerate(golden_set.questions):
        item = _evaluate_question(
            session=session,
            question_index=i,
            golden=question,
            knowledge_base=knowledge_base,
            top_k=top_k,
            provider_override=provider,
            model_override=model,
            dimensions_override=dimensions,
        )
        items.append(item)

    metrics = _compute_metrics(items)

    # Compute regression delta vs baseline
    baseline_metrics = _load_baseline_metrics(baseline_path) if baseline_path else None
    if baseline_metrics is not None:
        metrics.regression_delta_vs_baseline = _compute_regression_delta(metrics, baseline_metrics)
        metrics.baseline_label = baseline_path.stem if baseline_path else None

    # Determine provider/model/dimensions from first successful item
    resolved_provider = provider or "deterministic-local"
    resolved_model = model or "hash-8d"
    resolved_dimensions = dimensions or 8

    run = EvaluationRun(
        id=run_id,
        created_at=now_iso(),
        golden_set_name=golden_set.name,
        knowledge_base=knowledge_base,
        provider=resolved_provider,
        model=resolved_model,
        dimensions=resolved_dimensions,
        top_k=top_k,
        backend="pgvector",
        distance_metric="cosine_distance",
        status="completed",
        total_questions=len(golden_set.questions),
        items=items,
        metrics=metrics,
        config_snapshot={
            "golden_set_name": golden_set.name,
            "golden_set_version": golden_set.version,
            "golden_set_description": golden_set.description,
            "knowledge_base": knowledge_base,
            "top_k": top_k,
            "provider": resolved_provider,
            "model": resolved_model,
            "dimensions": resolved_dimensions,
        },
    )

    if store_dir is not None:
        _persist_run(run, store_dir)

    return run


def _load_baseline_metrics(path: Path) -> EvaluationMetrics | None:
    """Load baseline metrics from a persisted evaluation run JSON."""
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    metrics_raw = raw.get("metrics")
    if not metrics_raw:
        return None
    try:
        return EvaluationMetrics.model_validate(metrics_raw)
    except Exception:
        return None


def _compute_regression_delta(
    current: EvaluationMetrics,
    baseline: EvaluationMetrics,
) -> dict[str, float | None]:
    """Compute delta between current and baseline metrics."""

    def _delta(current_val: float | None, baseline_val: float | None) -> float | None:
        if current_val is None or baseline_val is None:
            return None
        return round(current_val - baseline_val, 4)

    return {
        "hit_at_1": _delta(current.hit_at_1, baseline.hit_at_1),
        "hit_at_3": _delta(current.hit_at_3, baseline.hit_at_3),
        "hit_at_5": _delta(current.hit_at_5, baseline.hit_at_5),
        "mrr": _delta(current.mrr, baseline.mrr),
        "mean_rank_of_expected": _delta(
            current.mean_rank_of_expected, baseline.mean_rank_of_expected
        ),
        "citation_coverage_mean": _delta(
            current.citation_coverage_mean, baseline.citation_coverage_mean
        ),
        "zero_result_rate": _delta(current.zero_result_rate, baseline.zero_result_rate),
    }


def _persist_run(run: EvaluationRun, store_dir: Path) -> None:
    """Persist an evaluation run to a JSON file in the store directory."""
    store_dir.mkdir(parents=True, exist_ok=True)
    file_path = store_dir / f"{run.id}.json"
    file_path.write_text(
        json.dumps(_serialize_run_for_persistence(run), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _serialize_run_for_persistence(run: EvaluationRun) -> dict[str, Any]:
    """Serialize an evaluation run for JSON persistence, without secrets."""
    data = run.model_dump()
    # Ensure no sensitive fields leak
    sensitive_keys = {
        "api_key",
        "secret",
        "password",
        "token",
        "credential",
        "private_key",
        "access_key",
    }
    config = data.get("config_snapshot", {})
    if isinstance(config, dict):
        for key in list(config.keys()):
            key_lower = key.lower()
            if any(sk in key_lower for sk in sensitive_keys):
                config[key] = "[REDACTED]"
    return data


def load_run_from_store(run_id: str, store_dir: Path | None = None) -> EvaluationRun | None:
    """Load a previously persisted evaluation run."""
    store_dir = store_dir or DEFAULT_EVAL_DIR
    file_path = store_dir / f"{run_id}.json"
    if not file_path.exists():
        return None
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
        return EvaluationRun.model_validate(raw)
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def list_runs_from_store(
    store_dir: Path | None = None,
    limit: int = 50,
) -> list[EvaluationRun]:
    """List evaluation runs persisted in the store directory, newest first."""
    store_dir = store_dir or DEFAULT_EVAL_DIR
    if not store_dir.exists():
        return []
    runs = []
    for file_path in sorted(store_dir.glob("*.json"), reverse=True):
        try:
            raw = json.loads(file_path.read_text(encoding="utf-8"))
            run = EvaluationRun.model_validate(raw)
            runs.append(run)
        except (json.JSONDecodeError, OSError, ValueError):
            continue
        if len(runs) >= limit:
            break
    return runs
