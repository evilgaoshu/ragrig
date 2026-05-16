from __future__ import annotations

import json
from datetime import datetime, timezone

from scripts.google_workspace_diagnostics import (
    build_google_workspace_diagnostics_report,
    main,
)


def test_google_workspace_diagnostics_report_covers_contract_scenarios() -> None:
    report = build_google_workspace_diagnostics_report(
        generated_at=datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
    )

    assert report["artifact"] == "google-workspace-diagnostics"
    assert report["overall_status"] == "pass"
    assert report["network_calls"] is False
    statuses = {scenario["name"]: scenario["observed_status"] for scenario in report["scenarios"]}
    assert statuses == {
        "missing_secret_skip": "skip",
        "invalid_secret_degraded": "degraded",
        "fixture_discovery_healthy": "healthy",
    }

    healthy = next(
        scenario
        for scenario in report["scenarios"]
        if scenario["name"] == "fixture_discovery_healthy"
    )
    state = healthy["state"]
    assert state["last_discovery"]["total_count"] == 2
    assert state["production_contract"]["permission_mapping"] == "not_declared"
    permission_contract = next(
        item for item in state["capability_contract"] if item["capability"] == "permission_mapping"
    )
    assert permission_contract["declared"] is False


def test_google_workspace_diagnostics_report_redacts_raw_secret_markers() -> None:
    report = build_google_workspace_diagnostics_report()
    payload = json.dumps(report)

    assert report["secret_leak_markers"] == []
    assert "fixture-client-secret" not in payload
    assert "fixture-private-key" not in payload
    assert "not-valid-json" not in payload
    assert "service_account_json" not in payload


def test_google_workspace_diagnostics_cli_writes_artifact(tmp_path) -> None:
    output = tmp_path / "google-workspace-diagnostics.json"

    exit_code = main(["--output", str(output)])

    assert exit_code == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["overall_status"] == "pass"
    assert data["connector_id"] == "source.google_workspace"
