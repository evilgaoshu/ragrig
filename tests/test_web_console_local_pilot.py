from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_console_contains_local_pilot_wizard() -> None:
    html = Path("src/ragrig/web_console.html").read_text(encoding="utf-8")

    assert "Local Pilot" in html
    assert "data-local-pilot-wizard" in html
    assert "/local-pilot/status" in html
    assert "/knowledge-bases/" in html
    assert "/website-import" in html
    assert "/local-pilot/answer-smoke" in html
    assert ".pdf" in html
    assert ".docx" in html
