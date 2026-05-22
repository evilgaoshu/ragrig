from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.demo_rc_gate import run_demo_rc_gate

pytestmark = [pytest.mark.integration]


def test_demo_rc_gate_passes_with_repository_local_pilot_fixture(tmp_path: Path) -> None:
    report = run_demo_rc_gate(
        database_path=tmp_path / "demo-rc.db",
        generated_at=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )

    assert report["artifact"] == "demo-rc-gate"
    assert report["status"] == "pass"
    assert {check["status"] for check in report["checks"]} == {"pass"}
    assert report["comparison"]["baseline_mode"] == "dense"
    assert "markdown_summary" in report
