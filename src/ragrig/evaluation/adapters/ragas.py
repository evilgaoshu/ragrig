"""Optional RAGAS evaluation adapter.

The core evaluation engine imports this module unconditionally, but the
third-party ``ragas`` package is imported only when the adapter is explicitly
enabled for a run.
"""

from __future__ import annotations

import importlib
import time
from collections.abc import Mapping, Sequence
from typing import Any

_SUPPORTED_METRICS = (
    "faithfulness",
    "context_precision",
    "context_recall",
    "answer_relevancy",
    "answer_correctness",
)


def evaluate_ragas_item(
    *,
    enabled: bool,
    question: str,
    contexts: Sequence[str],
    answer: str | None,
    reference: str | None,
    metrics: Sequence[str] | None = None,
    module_name: str = "ragas",
) -> dict[str, Any]:
    """Run optional RAGAS scoring for a single evaluation item.

    Returns a stable diagnostics dict instead of raising when RAGAS or one of
    its runtime dependencies is unavailable.
    """
    if not enabled:
        return {"enabled": False, "status": "disabled"}

    requested_metrics = tuple(metrics or _SUPPORTED_METRICS)
    start = time.perf_counter()
    try:
        ragas = importlib.import_module(module_name)
    except Exception as exc:
        return {
            "enabled": True,
            "status": "degraded",
            "degraded_reason": "missing_dependency",
            "error": type(exc).__name__,
            "metrics": {},
            "latency_ms": _elapsed_ms(start),
        }

    try:
        raw = _call_ragas(
            ragas,
            question=question,
            contexts=list(contexts),
            answer=answer or reference or "",
            reference=reference or "",
            metrics=requested_metrics,
        )
    except Exception as exc:
        return {
            "enabled": True,
            "status": "degraded",
            "degraded_reason": "adapter_error",
            "error": type(exc).__name__,
            "metrics": {},
            "latency_ms": _elapsed_ms(start),
        }

    return {
        "enabled": True,
        "status": "completed",
        "metrics": _coerce_metrics(raw, requested_metrics),
        "latency_ms": _elapsed_ms(start),
    }


def _call_ragas(
    ragas: Any,
    *,
    question: str,
    contexts: list[str],
    answer: str,
    reference: str,
    metrics: Sequence[str],
) -> Mapping[str, Any]:
    """Call a supported RAGAS-like API.

    Tests use a tiny ``evaluate_single`` fake. The fallback ``evaluate`` path
    accepts dict-like results from compatible wrappers without forcing a hard
    dependency on HuggingFace datasets in core RAGRig.
    """
    payload = {
        "question": question,
        "contexts": contexts,
        "answer": answer,
        "reference": reference,
        "ground_truth": reference,
        "metrics": list(metrics),
    }
    evaluate_single = getattr(ragas, "evaluate_single", None)
    if callable(evaluate_single):
        result = evaluate_single(**payload)
        return _as_mapping(result)

    evaluate = getattr(ragas, "evaluate", None)
    if callable(evaluate):
        result = evaluate([payload])
        return _as_mapping(result)

    raise RuntimeError("ragas module does not expose evaluate_single or evaluate")


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "to_pandas"):
        frame = value.to_pandas()
        if not frame.empty:
            return dict(frame.iloc[0].to_dict())
    if hasattr(value, "scores"):
        scores = value.scores
        if isinstance(scores, list) and scores:
            return _as_mapping(scores[0])
        if isinstance(scores, Mapping):
            return scores
    if hasattr(value, "__dict__"):
        return vars(value)
    raise TypeError(f"unsupported RAGAS result type: {type(value).__name__}")


def _coerce_metrics(raw: Mapping[str, Any], requested_metrics: Sequence[str]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for name in requested_metrics:
        raw_value = raw.get(name)
        if raw_value is None and name == "answer_relevancy":
            raw_value = raw.get("answer_relevance")
        if raw_value is None:
            continue
        try:
            metrics[name] = round(float(raw_value), 4)
        except (TypeError, ValueError):
            continue
    return metrics


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 2)
