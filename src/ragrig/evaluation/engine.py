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
    judge_provider: Any = None,
    answer_provider_name: str | None = None,
    answer_model: str | None = None,
    answer_provider_config: dict[str, Any] | None = None,
    mode: str = "dense",
    lexical_weight: float = 0.3,
    vector_weight: float = 0.7,
    candidate_k: int = 20,
    reranker_provider: str | None = None,
    reranker_model: str | None = None,
    graph_weight: float = 0.35,
    graph_depth: int = 1,
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
            mode=mode,
            lexical_weight=lexical_weight,
            vector_weight=vector_weight,
            candidate_k=candidate_k,
            reranker_provider=reranker_provider,
            reranker_model=reranker_model,
            graph_weight=graph_weight,
            graph_depth=graph_depth,
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

        # Context precision / recall (string-match, no LLM)
        from ragrig.evaluation.answer_judge import score_context_precision, score_context_recall

        expected_citations = list(golden.expected_relevant_citations or [])
        if not expected_citations and golden.expected_citation:
            expected_citations = [golden.expected_citation]

        ctx_precision: float | None = None
        ctx_recall: float | None = None
        if expected_citations:
            ctx_precision = score_context_precision(
                retrieved_texts=text_previews,
                expected_citations=expected_citations,
            )
            ctx_recall = score_context_recall(
                retrieved_texts=text_previews,
                expected_citations=expected_citations,
            )

        # Answer generation + quality scoring (optional)
        answer_status = "skipped"
        answer_correctness: float | None = None
        answer_correctness_reason: str | None = None
        answer_relevance: float | None = None
        answer_relevance_reason: str | None = None

        if answer_provider_name is not None:
            try:
                from ragrig.answer.service import generate_answer
                from ragrig.evaluation.answer_judge import (
                    score_answer_correctness,
                    score_answer_relevance,
                )

                answer_report = generate_answer(
                    session=session,
                    knowledge_base_name=knowledge_base,
                    query=golden.query,
                    top_k=top_k,
                    provider=provider_override or "deterministic-local",
                    model=model_override,
                    answer_provider=answer_provider_name,
                    answer_model=answer_model,
                    answer_provider_config=answer_provider_config,
                    dimensions=dimensions_override,
                    mode=mode,
                    lexical_weight=lexical_weight,
                    vector_weight=vector_weight,
                    candidate_k=candidate_k,
                    reranker_provider=reranker_provider,
                    reranker_model=reranker_model,
                    graph_weight=graph_weight,
                    graph_depth=graph_depth,
                )
                answer_status = answer_report.grounding_status

                if judge_provider is not None:
                    if golden.expected_answer:
                        result = score_answer_correctness(
                            query=golden.query,
                            generated_answer=answer_report.answer,
                            expected_answer=golden.expected_answer,
                            provider=judge_provider,
                        )
                        if result is not None:
                            answer_correctness, answer_correctness_reason = result

                    rel_result = score_answer_relevance(
                        query=golden.query,
                        generated_answer=answer_report.answer,
                        provider=judge_provider,
                    )
                    if rel_result is not None:
                        answer_relevance, answer_relevance_reason = rel_result

            except Exception:
                answer_status = "error"

        return EvaluationRunItem(
            question_index=question_index,
            query=golden.query,
            tags=list(golden.tags or []),
            hit=hit,
            rank_of_expected=rank,
            mrr=mrr,
            total_results=report.total_results,
            citation_coverage=citation_cov,
            context_precision=ctx_precision,
            context_recall=ctx_recall,
            answer_status=answer_status,
            answer_correctness=answer_correctness,
            answer_correctness_reason=answer_correctness_reason,
            answer_relevance=answer_relevance,
            answer_relevance_reason=answer_relevance_reason,
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
            tags=list(getattr(golden, "tags", None) or []),
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


def _mean_or_none(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _compute_tag_metrics(items: list[EvaluationRunItem]) -> dict[str, dict[str, float | None]]:
    """Build per-tag metric breakdown from item tags."""
    tag_items: dict[str, list[EvaluationRunItem]] = {}
    for item in items:
        for tag in item.tags:
            tag_items.setdefault(tag, []).append(item)

    result: dict[str, dict[str, float | None]] = {}
    for tag, tag_item_list in tag_items.items():
        n = len(tag_item_list)
        valid = [i for i in tag_item_list if i.error is None]
        ranks = [i.rank_of_expected for i in valid if i.rank_of_expected is not None]
        prec = [i.context_precision for i in valid if i.context_precision is not None]
        rec = [i.context_recall for i in valid if i.context_recall is not None]
        corr = [i.answer_correctness for i in valid if i.answer_correctness is not None]
        relv = [i.answer_relevance for i in valid if i.answer_relevance is not None]
        result[tag] = {
            "count": float(n),
            "hit_at_1": round(sum(1 for i in valid if i.hit and i.rank_of_expected == 1) / n, 4),
            "hit_at_3": round(
                sum(
                    1
                    for i in valid
                    if i.hit and i.rank_of_expected is not None and i.rank_of_expected <= 3
                )
                / n,
                4,
            ),
            "mrr": round(sum(i.mrr for i in valid) / n, 4) if n else None,
            "mean_rank_of_expected": _mean_or_none(ranks),  # type: ignore[arg-type]
            "context_precision_mean": _mean_or_none(prec),  # type: ignore[arg-type]
            "context_recall_mean": _mean_or_none(rec),  # type: ignore[arg-type]
            "answer_correctness_mean": _mean_or_none(corr),  # type: ignore[arg-type]
            "answer_relevance_mean": _mean_or_none(relv),  # type: ignore[arg-type]
        }
    return result


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

    prec_vals = [i.context_precision for i in hit_items if i.context_precision is not None]
    rec_vals = [i.context_recall for i in hit_items if i.context_recall is not None]
    corr_vals = [i.answer_correctness for i in hit_items if i.answer_correctness is not None]
    relv_vals = [i.answer_relevance for i in hit_items if i.answer_relevance is not None]

    answer_ran = any(i.answer_status not in ("skipped", "error") for i in hit_items)

    zero_results = sum(1 for item in items if item.total_results == 0)

    latencies = sorted(item.latency_ms for item in items)
    latency_mean = sum(latencies) / total if total else 0.0

    per_tag = _compute_tag_metrics(hit_items)

    return EvaluationMetrics(
        total_questions=total,
        hit_at_1=round(hit_at_1, 4),
        hit_at_3=round(hit_at_3, 4),
        hit_at_5=round(hit_at_5, 4),
        mrr=round(mrr, 4),
        mean_rank_of_expected=round(mean_rank, 2) if mean_rank is not None else None,
        citation_coverage_mean=round(citation_mean, 4),
        context_precision_mean=_mean_or_none(prec_vals),  # type: ignore[arg-type]
        context_recall_mean=_mean_or_none(rec_vals),  # type: ignore[arg-type]
        zero_result_count=zero_results,
        zero_result_rate=round(zero_results / total, 4) if total else 0.0,
        latency_ms_mean=round(latency_mean, 2),
        latency_ms_p50=round(_percentile(latencies, 50), 2),
        latency_ms_p95=round(_percentile(latencies, 95), 2),
        latency_ms_p99=round(_percentile(latencies, 99), 2),
        answer_skipped=not answer_ran,
        answer_degraded_reason=("answer provider not configured" if not answer_ran else None),
        answer_correctness_mean=_mean_or_none(corr_vals),  # type: ignore[arg-type]
        answer_relevance_mean=_mean_or_none(relv_vals),  # type: ignore[arg-type]
        per_tag_metrics=per_tag,
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
    judge_provider_name: str | None = None,
    answer_provider_name: str | None = None,
    answer_model: str | None = None,
    answer_provider_config: dict[str, Any] | None = None,
    mode: str = "dense",
    lexical_weight: float = 0.3,
    vector_weight: float = 0.7,
    candidate_k: int = 20,
    reranker_provider: str | None = None,
    reranker_model: str | None = None,
    graph_weight: float = 0.35,
    graph_depth: int = 1,
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
        judge_provider_name: Provider name for the LLM answer judge.  When set,
            answer correctness and relevance scores are computed.
        answer_provider_name: When set, ``generate_answer()`` is called for
            each question so answer quality can be measured.
        answer_model: Optional model override for the answer provider.
        answer_provider_config: Optional config dict for the answer provider.
        mode: Retrieval mode to evaluate, e.g. ``dense`` or ``hybrid_graph``.

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
        judge_provider_name=judge_provider_name,
        answer_provider_name=answer_provider_name,
        answer_model=answer_model,
        answer_provider_config=answer_provider_config,
        mode=mode,
        lexical_weight=lexical_weight,
        vector_weight=vector_weight,
        candidate_k=candidate_k,
        reranker_provider=reranker_provider,
        reranker_model=reranker_model,
        graph_weight=graph_weight,
        graph_depth=graph_depth,
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
    judge_provider_name: str | None = None,
    answer_provider_name: str | None = None,
    answer_model: str | None = None,
    answer_provider_config: dict[str, Any] | None = None,
    mode: str = "dense",
    lexical_weight: float = 0.3,
    vector_weight: float = 0.7,
    candidate_k: int = 20,
    reranker_provider: str | None = None,
    reranker_model: str | None = None,
    graph_weight: float = 0.35,
    graph_depth: int = 1,
) -> EvaluationRun:
    """Internal: run evaluation with an already-loaded GoldenQuestionSet."""
    run_id = run_id or str(uuid.uuid4())

    judge_provider = None
    if judge_provider_name is not None:
        try:
            from ragrig.providers import get_provider_registry

            judge_provider = get_provider_registry().get(judge_provider_name)
        except Exception:
            pass

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
            judge_provider=judge_provider,
            answer_provider_name=answer_provider_name,
            answer_model=answer_model,
            answer_provider_config=answer_provider_config,
            mode=mode,
            lexical_weight=lexical_weight,
            vector_weight=vector_weight,
            candidate_k=candidate_k,
            reranker_provider=reranker_provider,
            reranker_model=reranker_model,
            graph_weight=graph_weight,
            graph_depth=graph_depth,
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
            "judge_provider": judge_provider_name,
            "answer_provider": answer_provider_name,
            "answer_model": answer_model,
            "mode": mode,
            "lexical_weight": lexical_weight,
            "vector_weight": vector_weight,
            "candidate_k": candidate_k,
            "reranker_provider": reranker_provider,
            "reranker_model": reranker_model,
            "graph_weight": graph_weight,
            "graph_depth": graph_depth,
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
        "context_precision_mean": _delta(
            current.context_precision_mean, baseline.context_precision_mean
        ),
        "context_recall_mean": _delta(current.context_recall_mean, baseline.context_recall_mean),
        "answer_correctness_mean": _delta(
            current.answer_correctness_mean, baseline.answer_correctness_mean
        ),
        "answer_relevance_mean": _delta(
            current.answer_relevance_mean, baseline.answer_relevance_mean
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
    from ragrig.evaluation.report import _sanitize_dict

    data = run.model_dump()
    # Recursively sanitize config_snapshot to ensure no secrets leak at any depth
    config = data.get("config_snapshot", {})
    if isinstance(config, dict):
        data["config_snapshot"] = _sanitize_dict(config)
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
