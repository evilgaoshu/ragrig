from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.db.models import KnowledgeBase, PipelineRun, Source

TRACKING_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class Rate:
    input_per_1k_usd: float
    output_per_1k_usd: float = 0.0
    source: str = "configured"


_DEFAULT_RATE_CARD: dict[tuple[str, str], Rate] = {
    ("deterministic-local", "*"): Rate(0.0, 0.0, "local_zero_cost"),
    ("model.bge", "*"): Rate(0.0, 0.0, "local_zero_cost"),
    ("reranker.bge", "*"): Rate(0.0, 0.0, "local_zero_cost"),
    ("fake", "*"): Rate(0.0, 0.0, "local_zero_cost"),
}


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def estimate_model_usage(
    *,
    operation: str,
    provider: str,
    model: str,
    input_text: str | None = None,
    output_text: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    rate_card: dict[tuple[str, str], Rate] | None = None,
) -> dict[str, Any]:
    resolved_input_tokens = (
        estimate_tokens(input_text) if input_tokens is None else max(0, int(input_tokens))
    )
    resolved_output_tokens = (
        estimate_tokens(output_text) if output_tokens is None else max(0, int(output_tokens))
    )
    rate = _resolve_rate(provider, model, rate_card=rate_card)
    input_cost = resolved_input_tokens * rate.input_per_1k_usd / 1000
    output_cost = resolved_output_tokens * rate.output_per_1k_usd / 1000
    return {
        "schema_version": TRACKING_SCHEMA_VERSION,
        "operation": operation,
        "provider": provider,
        "model": model,
        "input_tokens_estimated": resolved_input_tokens,
        "output_tokens_estimated": resolved_output_tokens,
        "total_tokens_estimated": resolved_input_tokens + resolved_output_tokens,
        "input_cost_usd_estimated": round(input_cost, 8),
        "output_cost_usd_estimated": round(output_cost, 8),
        "total_cost_usd_estimated": round(input_cost + output_cost, 8),
        "rate_source": rate.source,
        "estimated": True,
    }


def observe_model_call(
    *,
    operation: str,
    provider: str,
    model: str,
    latency_ms: float,
    input_text: str | None = None,
    output_text: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    usage = estimate_model_usage(
        operation=operation,
        provider=provider,
        model=model,
        input_text=input_text,
        output_text=output_text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    usage["latency_ms"] = round(float(latency_ms), 3)
    if metadata:
        usage["metadata"] = metadata
    return usage


def aggregate_cost_latency(
    operations: list[dict[str, Any]],
    *,
    total_latency_ms: float | None = None,
) -> dict[str, Any]:
    latencies = [float(op.get("latency_ms") or 0.0) for op in operations]
    by_model: dict[str, dict[str, Any]] = {}
    by_operation: dict[str, dict[str, Any]] = {}

    for op in operations:
        model_key = f"{op.get('provider', '')}:{op.get('model', '')}"
        _add_aggregate_row(by_model, model_key, op)
        operation_key = str(op.get("operation") or "unknown")
        _add_aggregate_row(by_operation, operation_key, op)

    return {
        "schema_version": TRACKING_SCHEMA_VERSION,
        "operation_count": len(operations),
        "total_input_tokens_estimated": sum(
            int(op.get("input_tokens_estimated") or 0) for op in operations
        ),
        "total_output_tokens_estimated": sum(
            int(op.get("output_tokens_estimated") or 0) for op in operations
        ),
        "total_tokens_estimated": sum(
            int(op.get("total_tokens_estimated") or 0) for op in operations
        ),
        "total_cost_usd_estimated": round(
            sum(float(op.get("total_cost_usd_estimated") or 0.0) for op in operations),
            8,
        ),
        "total_latency_ms": round(
            float(total_latency_ms) if total_latency_ms is not None else sum(latencies),
            3,
        ),
        "latency_ms_p50": round(_percentile(latencies, 50), 3),
        "latency_ms_p95": round(_percentile(latencies, 95), 3),
        "by_model": by_model,
        "by_operation": by_operation,
    }


def pipeline_run_duration_ms(run: PipelineRun) -> float | None:
    return _duration_ms(run.started_at, run.finished_at)


def summarize_pipeline_cost_latency(
    session: Session,
    *,
    knowledge_base_name: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    statement = (
        select(PipelineRun, KnowledgeBase, Source)
        .join(KnowledgeBase, KnowledgeBase.id == PipelineRun.knowledge_base_id)
        .outerjoin(Source, Source.id == PipelineRun.source_id)
        .order_by(PipelineRun.started_at.desc())
    )
    if knowledge_base_name:
        statement = statement.where(KnowledgeBase.name == knowledge_base_name)
    statement = statement.limit(limit)

    runs: list[dict[str, Any]] = []
    tracked_operations: list[dict[str, Any]] = []
    for run, knowledge_base, source in session.execute(statement):
        summary = (run.config_snapshot_json or {}).get("cost_latency_summary") or {}
        operations = summary.get("operations") if isinstance(summary, dict) else None
        if isinstance(operations, list):
            tracked_operations.extend(op for op in operations if isinstance(op, dict))
        runs.append(
            {
                "id": str(run.id),
                "knowledge_base": knowledge_base.name,
                "source_uri": source.uri if source is not None else None,
                "run_type": run.run_type,
                "status": run.status,
                "started_at": _isoformat(run.started_at),
                "finished_at": _isoformat(run.finished_at),
                "duration_ms": pipeline_run_duration_ms(run),
                "cost_latency_summary": summary,
            }
        )

    aggregate = aggregate_cost_latency(tracked_operations)
    return {
        "schema_version": TRACKING_SCHEMA_VERSION,
        "knowledge_base": knowledge_base_name,
        "run_count": len(runs),
        "tracked_operation_count": len(tracked_operations),
        "aggregate": aggregate,
        "runs": runs,
    }


def _resolve_rate(
    provider: str,
    model: str,
    *,
    rate_card: dict[tuple[str, str], Rate] | None = None,
) -> Rate:
    card = rate_card or _DEFAULT_RATE_CARD
    return (
        card.get((provider, model)) or card.get((provider, "*")) or Rate(0.0, 0.0, "missing_rate")
    )


def _add_aggregate_row(
    target: dict[str, dict[str, Any]],
    key: str,
    operation: dict[str, Any],
) -> None:
    if key not in target:
        target[key] = {
            "operation_count": 0,
            "input_tokens_estimated": 0,
            "output_tokens_estimated": 0,
            "total_tokens_estimated": 0,
            "cost_usd_estimated": 0.0,
            "latency_ms": 0.0,
        }
    row = target[key]
    row["operation_count"] += 1
    row["input_tokens_estimated"] += int(operation.get("input_tokens_estimated") or 0)
    row["output_tokens_estimated"] += int(operation.get("output_tokens_estimated") or 0)
    row["total_tokens_estimated"] += int(operation.get("total_tokens_estimated") or 0)
    row["cost_usd_estimated"] = round(
        float(row["cost_usd_estimated"]) + float(operation.get("total_cost_usd_estimated") or 0.0),
        8,
    )
    row["latency_ms"] = round(
        float(row["latency_ms"]) + float(operation.get("latency_ms") or 0.0),
        3,
    )


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    sorted_values = sorted(values)
    position = (len(sorted_values) - 1) * percentile / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[int(position)]
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _duration_ms(started_at: datetime | None, finished_at: datetime | None) -> float | None:
    if started_at is None or finished_at is None:
        return None
    return round((finished_at - started_at).total_seconds() * 1000, 3)


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
