from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_console_contains_local_pilot_wizard() -> None:
    html = Path("src/ragrig/web_console.html").read_text(encoding="utf-8")

    assert "Local Pilot" in html
    assert "data-local-pilot-wizard" in html
    assert "pilot-step-model" in html
    assert "pilot-step-ingest" in html
    assert "pilot-step-review" in html
    assert "pilot-step-playground" in html
    assert "/local-pilot/status" in html
    assert "/knowledge-bases/" in html
    assert "/website-import" in html
    assert "/upload" in html
    assert "/local-pilot/answer-smoke" in html
    assert "/retrieval/answer" in html
    assert ".pdf" in html
    assert ".docx" in html


def test_console_local_pilot_wizard_has_file_and_playground_controls() -> None:
    html = Path("src/ragrig/web_console.html").read_text(encoding="utf-8")

    assert 'id="pilot-file-input"' in html
    assert 'accept=".md,.markdown,.txt,.text,.pdf,.docx"' in html
    assert 'id="pilot-question"' in html
    assert 'id="pilot-run-answer"' in html
    assert 'id="pilot-run-summary"' in html
    assert 'id="pilot-chunk-preview"' in html
    assert "ensurePilotKnowledgeBase" in html
    assert "runPilotFileUpload" in html
    assert "runPilotPlaygroundAnswer" in html


def test_console_local_pilot_wizard_has_model_config_controls() -> None:
    html = Path("src/ragrig/web_console.html").read_text(encoding="utf-8")

    assert 'id="pilot-api-key-ref"' in html
    assert 'id="pilot-model-health"' in html
    assert 'id="pilot-model" value="hash-8d"' in html
    assert "/local-pilot/model-health" in html
    assert "buildPilotModelConfig" in html
    assert "syncPilotProviderDefaults" in html
    assert "env:VARIABLE_NAME" in html
    assert "raw API keys are not accepted" in html


def test_console_local_pilot_playground_uses_selected_model_config() -> None:
    html = Path("src/ragrig/web_console.html").read_text(encoding="utf-8")
    function_body = html.split("async function runPilotPlaygroundAnswer()", 1)[1].split(
        "async function loadInitialData()", 1
    )[0]

    assert "const modelPayload = buildPilotModelPayload();" in function_body
    assert "provider: 'deterministic-local'" in function_body
    assert "answer_provider: modelPayload.provider" in function_body
    assert "answer_model: modelPayload.model" in function_body
    assert "answer_config: modelPayload.config" in function_body
