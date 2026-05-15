from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def test_local_pilot_console_e2e_runner_is_registered() -> None:
    runner = Path("scripts/local_pilot_console_e2e.py")
    browser_spec = Path("scripts/local_pilot_console_e2e.mjs")
    makefile = Path("Makefile").read_text(encoding="utf-8")

    assert runner.exists()
    assert browser_spec.exists()
    assert "local-pilot-console-e2e:" in makefile
    assert "scripts.local_pilot_console_e2e" in makefile
