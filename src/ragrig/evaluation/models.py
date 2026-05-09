"""Domain models for Golden Question Evaluation.

GoldenQuestionSet, GoldenQuestion, EvaluationRun, and EvaluationRunItem
represent the core evaluation domain. These models are immutable where
possible and use Pydantic for validation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class GoldenQuestion(BaseModel):
    """A single golden question with expected retrieval/answer targets."""

    query: str
    expected_doc_uri: str | None = None
    expected_chunk_uri: str | None = None
    expected_chunk_text: str | None = None
    expected_citation: str | None = None
    expected_answer_keywords: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class GoldenQuestionSet(BaseModel):
    """A named collection of golden questions loaded from a fixture."""

    name: str = "default"
    description: str = ""
    version: str = "1.0.0"
    questions: list[GoldenQuestion]


class EvaluationRunItem(BaseModel):
    """Per-question result within an evaluation run."""

    question_index: int
    query: str
    hit: bool = False
    rank_of_expected: int | None = None
    mrr: float = 0.0
    total_results: int = 0
    citation_coverage: float = 0.0
    answer_status: str = "skipped"
    answer_groundedness: float | None = None
    answer_citation_coverage: float | None = None
    latency_ms: float = 0.0
    top_doc_uris: list[str] = Field(default_factory=list)
    top_distances: list[float] = Field(default_factory=list)
    top_scores: list[float] = Field(default_factory=list)
    error: str | None = None


class EvaluationMetrics(BaseModel):
    """Aggregated metrics for an evaluation run."""

    total_questions: int = 0
    hit_at_1: float = 0.0
    hit_at_3: float = 0.0
    hit_at_5: float = 0.0
    mrr: float = 0.0
    mean_rank_of_expected: float | None = None
    citation_coverage_mean: float = 0.0
    zero_result_count: int = 0
    zero_result_rate: float = 0.0
    latency_ms_mean: float = 0.0
    latency_ms_p50: float = 0.0
    latency_ms_p95: float = 0.0
    latency_ms_p99: float = 0.0
    answer_skipped: bool = True
    answer_degraded_reason: str | None = None
    regression_delta_vs_baseline: dict[str, float | None] = Field(
        default_factory=lambda: {
            "hit_at_1": None,
            "hit_at_3": None,
            "hit_at_5": None,
            "mrr": None,
            "mean_rank_of_expected": None,
            "citation_coverage_mean": None,
            "zero_result_rate": None,
        }
    )
    baseline_label: str | None = None


class EvaluationRun(BaseModel):
    """A complete evaluation run with metadata, items, and metrics."""

    id: str
    created_at: str
    golden_set_name: str
    knowledge_base: str
    provider: str
    model: str
    dimensions: int
    top_k: int
    backend: str
    distance_metric: str
    status: str = "completed"
    total_questions: int = 0
    items: list[EvaluationRunItem] = Field(default_factory=list)
    metrics: EvaluationMetrics = Field(default_factory=EvaluationMetrics)
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class EvaluationListResponse(BaseModel):
    """Response for listing all evaluation runs."""

    runs: list[EvaluationRun]
    latest_id: str | None = None
    latest_metrics: EvaluationMetrics | None = None


def now_iso() -> str:
    """Return current UTC timestamp as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()
