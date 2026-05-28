from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

DEMO_ROOT = Path("examples/local-pilot")


def test_local_pilot_demo_markdown_fixtures_are_groundable() -> None:
    handbook = DEMO_ROOT / "company-handbook.md"
    faq = DEMO_ROOT / "support-faq.md"

    assert handbook.exists()
    assert faq.exists()
    combined = f"{handbook.read_text(encoding='utf-8')}\n{faq.read_text(encoding='utf-8')}"

    for expected_fact in (
        "RAGRig Local Pilot",
        "citation",
        "pipeline run",
        "Ollama",
        "Gemini",
    ):
        assert expected_fact in combined


def test_local_pilot_demo_questions_reference_uploaded_sources() -> None:
    questions_path = DEMO_ROOT / "demo-questions.json"

    questions = json.loads(questions_path.read_text(encoding="utf-8"))

    assert len(questions) >= 3
    for question in questions:
        assert set(question) == {"question", "expected_source", "expected_terms"}
        assert question["expected_source"] in {
            "company-handbook.md",
            "support-faq.md",
        }
        assert question["expected_terms"]


def test_graph_console_demo_runbook_is_one_command() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    runbook = Path("docs/operations/demo-graph-console-runbook.md").read_text(encoding="utf-8")
    script = Path("scripts/demo_graph_console_runbook.py")

    assert script.exists()
    assert "demo-graph-console-runbook:" in makefile
    assert "demo-graph-console:" in makefile
    assert "scripts.demo_graph_console_runbook" in makefile
    assert "make demo-graph-console" in runbook
    assert "Graph Explorer" in runbook
    assert "hybrid_graph" in runbook
    assert "One-page external demo checklist" in runbook
    assert "make demo-graph-console-smoke" in runbook
    assert "make demo-graph-console-cleanup CONFIRM_DELETE=1" in runbook
    assert "docs/operations/external-demo-script.md" in runbook


def test_external_demo_script_keeps_graph_as_supporting_story() -> None:
    script = Path("docs/operations/external-demo-script.md")
    source = script.read_text(encoding="utf-8")

    assert script.exists()
    assert "GraphRAG is" in source
    assert "not the main product surface" in source
    assert "What makes a Local Pilot answer trustworthy?" in source
    assert "Which board compares DenseMode, GraphMode, and HybridGraphMode?" in source
    assert "What should happen to an incorrect graph relation after RelationFeedback?" in source
    assert "Bad-Weather Playbook" in source
    assert "Do Not Demo" in source
    assert "make demo-graph-console-cleanup CONFIRM_DELETE=1" in source


def test_graph_console_demo_browser_smoke_is_registered() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    runner = Path("scripts/demo_graph_console_smoke.py")
    browser_spec = Path("scripts/demo_graph_console_smoke.mjs")
    browser_source = browser_spec.read_text(encoding="utf-8")

    assert runner.exists()
    assert browser_spec.exists()
    assert "demo-graph-console-smoke:" in makefile
    assert "scripts.demo_graph_console_smoke" in makefile
    assert "Graph Explorer" in browser_source
    assert "data-kg-relation-feedback" in browser_source
    assert "suppressed_relation_count" in browser_source
    assert "#compare-retrieval" in browser_source


def test_graph_console_cleanup_is_scoped_to_demo_artifacts(tmp_path: Path) -> None:
    from scripts.demo_graph_console_cleanup import DEMO_ARTIFACTS, run_cleanup

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    for relative in DEMO_ARTIFACTS:
        path = artifacts_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("demo artifact", encoding="utf-8")
    retained = artifacts_dir / "keep-this.md"
    retained.write_text("not a demo artifact", encoding="utf-8")

    dry_run = run_cleanup(artifacts_dir=artifacts_dir, confirm_delete=False)

    assert dry_run["status"] == "dry_run"
    assert dry_run["existing_count"] == len(DEMO_ARTIFACTS)
    assert len(dry_run["would_delete"]) == len(DEMO_ARTIFACTS)
    assert retained.exists()
    assert all((artifacts_dir / relative).exists() for relative in DEMO_ARTIFACTS)

    deleted = run_cleanup(artifacts_dir=artifacts_dir, confirm_delete=True)

    assert deleted["status"] == "success"
    assert deleted["deleted_count"] == len(DEMO_ARTIFACTS)
    assert retained.exists()
    assert not any((artifacts_dir / relative).exists() for relative in DEMO_ARTIFACTS)
