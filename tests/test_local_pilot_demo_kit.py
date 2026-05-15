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
