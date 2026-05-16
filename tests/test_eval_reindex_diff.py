from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from scripts.eval_reindex_diff import (
    build_reindex_diff_report,
    main,
    run_reindex_diff_workflow,
)


def _run_report(run_id: str, *, hit: bool = True, rank: int | None = 1) -> dict:
    mrr = 1.0 / rank if rank else 0.0
    return {
        "id": run_id,
        "created_at": "2026-05-16T12:00:00+00:00",
        "status": "completed",
        "metrics": {
            "total_questions": 1,
            "hit_at_1": 1.0 if hit and rank == 1 else 0.0,
            "hit_at_3": 1.0 if hit and rank is not None and rank <= 3 else 0.0,
            "hit_at_5": 1.0 if hit and rank is not None and rank <= 5 else 0.0,
            "mrr": mrr,
            "mean_rank_of_expected": rank,
            "citation_coverage_mean": 1.0 if hit else 0.0,
            "zero_result_count": 0 if hit else 1,
            "zero_result_rate": 0.0 if hit else 1.0,
            "latency_ms_mean": 10.0,
            "latency_ms_p50": 10.0,
            "latency_ms_p95": 10.0,
            "latency_ms_p99": 10.0,
        },
        "items": [
            {
                "question_index": 0,
                "query": "Where is the guide?",
                "hit": hit,
                "rank_of_expected": rank,
                "mrr": mrr,
                "total_results": 1 if hit else 0,
                "citation_coverage": 1.0 if hit else 0.0,
                "top_doc_uris": ["guide.md"] if hit else [],
                "error": None,
            }
        ],
    }


def test_build_reindex_diff_report_marks_no_drift_pass() -> None:
    report = build_reindex_diff_report(
        before_run=_run_report("before"),
        after_run=_run_report("after"),
        before_index={"pipeline_run_id": "before-index", "failed_count": 0},
        after_index={"pipeline_run_id": "after-index", "failed_count": 0},
        workflow={"knowledge_base": "fixture-local"},
        generated_at=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
    )

    assert report["artifact"] == "evaluation-reindex-diff"
    assert report["status"] == "pass"
    assert report["summary"]["regressed_items"] == 0
    assert report["item_diffs"][0]["status"] == "unchanged"
    assert "Metric Deltas" in report["markdown_summary"]


def test_build_reindex_diff_report_marks_regression_degraded() -> None:
    report = build_reindex_diff_report(
        before_run=_run_report("before", hit=True, rank=1),
        after_run=_run_report("after", hit=True, rank=3),
        before_index={"pipeline_run_id": "before-index", "failed_count": 0},
        after_index={"pipeline_run_id": "after-index", "failed_count": 0},
        workflow={"knowledge_base": "fixture-local"},
    )

    assert report["status"] == "degraded"
    assert report["summary"]["regressed_items"] == 1
    assert "mrr" in report["summary"]["regressed_metrics"]


def test_run_reindex_diff_workflow_uses_force_reindex_and_passes_fixture() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    report = run_reindex_diff_workflow(
        golden_path=repo_root / "tests" / "fixtures" / "evaluation_golden.yaml",
        ingest_root=repo_root / "tests" / "fixtures" / "local_ingestion",
        knowledge_base="fixture-local",
        top_k=5,
        before_chunk_size=500,
        after_chunk_size=500,
        chunk_overlap=50,
        embedding_dimensions=8,
        generated_at=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc),
    )

    assert report["status"] == "pass"
    assert report["before"]["indexing"]["indexed_count"] > 0
    assert report["after"]["indexing"]["indexed_count"] > 0
    assert (
        report["after"]["indexing"]["indexed_count"]
        == report["before"]["indexing"]["indexed_count"]
    )
    assert report["summary"]["regressed_items"] == 0


def test_eval_reindex_diff_cli_writes_json_and_markdown(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    output = tmp_path / "eval-reindex-diff.json"
    markdown = tmp_path / "eval-reindex-diff.md"

    exit_code = main(
        [
            "--golden",
            str(repo_root / "tests" / "fixtures" / "evaluation_golden.yaml"),
            "--ingest-root",
            str(repo_root / "tests" / "fixtures" / "local_ingestion"),
            "--output",
            str(output),
            "--markdown-output",
            str(markdown),
        ]
    )

    assert exit_code == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["status"] == "pass"
    assert markdown.read_text(encoding="utf-8").startswith("# Evaluation Reindex Diff")
