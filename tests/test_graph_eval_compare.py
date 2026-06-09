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
        "      expected_citation: evidence citations\n"
        "      tags: [graph, multi-hop]\n",
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
    graph_result = next(result for result in report["results"] if result["mode"] == "graph")
    assert "per_tag_delta_vs_baseline" in graph_result
    assert graph_result["items"][0]["query"] == "AlphaProject BillingPolicy citations"
    assert report["graph_value_summary"]["modes"][0]["mode"] == "graph"
    assert report["question_diffs"][0]["mode"] == "graph"
    assert report["quality_gate"]["status"] in {"pass", "warn"}
    assert report["quality_gate"]["mode_results"][0]["mode"] == "graph"
    assert report["knowledge_graph"]["stats"]["entity_count"] >= 2
    assert report["knowledge_graph"]["trace"]["pipeline_run_id"]
    assert report["contract_gate"]["status"] == "pass"
    assert all(report["contract_gate"]["checks"].values())
    assert "markdown_summary" in report
    assert "Graph Value Summary" in report["markdown_summary"]
    assert "Question-Level Movement" in report["markdown_summary"]
    assert "Graph-Focused Per-Tag Delta" in report["markdown_summary"]
    assert "Graph-RAG Contract Gate" in report["markdown_summary"]
