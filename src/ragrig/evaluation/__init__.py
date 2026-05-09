"""RAGRig Evaluation — Golden Question quality gate for RAG retrieval."""

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

__all__ = [
    "run_evaluation",
    "load_run_from_store",
    "list_runs_from_store",
    "build_evaluation_report",
    "build_evaluation_list_report",
    "build_evaluation_run_report",
]
