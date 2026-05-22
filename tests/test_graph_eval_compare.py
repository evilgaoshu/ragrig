from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.graph_retrieval_eval_compare import run_graph_eval_compare_workflow

pytestmark = [pytest.mark.integration]


def _seed_docs(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text(
        "# Guide\n\nAlphaProject uses BillingPolicy evidence citations for trusted retrieval.",
        encoding="utf-8",
    )
    (docs / "faq.md").write_text(
        "# FAQ\n\nBillingPolicy explains how AlphaProject answers cite source chunks.",
        encoding="utf-8",
    )
    return docs


def _seed_golden(tmp_path: Path) -> Path:
    golden = tmp_path / "golden.yaml"
    golden.write_text(
        "golden_question_set:\n"
        "  name: graph-compare-test\n"
        "  questions:\n"
        "    - query: AlphaProject BillingPolicy citations\n"
        "      expected_doc_uri: guide.md\n"
        "      expected_citation: evidence citations\n",
        encoding="utf-8",
    )
    return golden


def test_graph_retrieval_eval_compare_workflow(tmp_path: Path) -> None:
    report = run_graph_eval_compare_workflow(
        golden_path=_seed_golden(tmp_path),
        ingest_root=_seed_docs(tmp_path),
        knowledge_base="graph-compare-test",
        modes=("dense", "graph"),
        top_k=3,
        generated_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )

    assert report["artifact"] == "graph-retrieval-eval-compare"
    assert report["baseline_mode"] == "dense"
    assert [result["mode"] for result in report["results"]] == ["dense", "graph"]
    assert all(result["item_error_count"] == 0 for result in report["results"])
    assert report["knowledge_graph"]["stats"]["entity_count"] >= 2
    assert "markdown_summary" in report
