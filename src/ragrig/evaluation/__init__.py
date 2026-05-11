"""RAGRig Evaluation — Golden Question quality gate for RAG retrieval."""

from ragrig.evaluation.baseline import (
    BaselineCorruptError,
    BaselineError,
    BaselineNotFoundError,
    get_current_baseline_id,
    list_baselines,
    load_baseline_metrics_strict,
    promote_run_to_baseline,
    resolve_baseline_path,
)
from ragrig.evaluation.engine import (
    list_runs_from_store,
    load_run_from_store,
    run_evaluation,
)
from ragrig.evaluation.report import (
    build_evaluation_list_report,
    build_evaluation_report,
    build_evaluation_run_report,
)
from ragrig.evaluation.retention import cleanup_evaluation_runs

__all__ = [
    "run_evaluation",
    "load_run_from_store",
    "list_runs_from_store",
    "build_evaluation_report",
    "build_evaluation_list_report",
    "build_evaluation_run_report",
    "promote_run_to_baseline",
    "resolve_baseline_path",
    "list_baselines",
    "load_baseline_metrics_strict",
    "get_current_baseline_id",
    "BaselineError",
    "BaselineNotFoundError",
    "BaselineCorruptError",
    "cleanup_evaluation_runs",
]
