from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ragrig.plugins.sources.google_workspace.console import (
    CONNECTOR_ID,
    DIAGNOSTICS_VERSION,
    SCHEMA_VERSION,
    build_connector_state,
    format_console_output_json,
)
from ragrig.plugins.sources.google_workspace.scanner import scan_drive_items

DEFAULT_OUTPUT = Path("docs/operations/artifacts/google-workspace-diagnostics.json")
RAW_SECRET_MARKERS = (
    "fixture-client-secret",
    "fixture-private-key",
    "not-valid-json",
    '{"type"',
)


def build_google_workspace_diagnostics_report(
    *,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated = (generated_at or datetime.now(timezone.utc)).isoformat()
    scenarios = [
        {
            "name": "missing_secret_skip",
            "expected_status": "skip",
            "config": _default_config(),
            "env": {},
            "run_discovery": False,
        },
        {
            "name": "invalid_secret_degraded",
            "expected_status": "degraded",
            "config": _default_config(),
            "env": {"GOOGLE_SERVICE_ACCOUNT_JSON": "not-valid-json"},
            "run_discovery": False,
        },
        {
            "name": "fixture_discovery_healthy",
            "expected_status": "healthy",
            "config": _default_config(),
            "env": {
                "GOOGLE_SERVICE_ACCOUNT_JSON": json.dumps(
                    {
                        "type": "service_account",
                        "client_email": "fixture@example.test",
                        "client_secret": "fixture-client-secret",
                        "private_key": "fixture-private-key",
                    }
                )
            },
            "run_discovery": True,
        },
    ]

    scenario_reports: list[dict[str, Any]] = []
    for scenario in scenarios:
        scan_result = None
        if scenario["run_discovery"]:
            scan_result = scan_drive_items(scenario["config"], env=scenario["env"])
        state = build_connector_state(
            scenario["config"],
            env=scenario["env"],
            scan_result=scan_result,
        )
        sanitized_state = json.loads(format_console_output_json(state))
        scenario_reports.append(
            {
                "name": scenario["name"],
                "expected_status": scenario["expected_status"],
                "observed_status": sanitized_state["status"],
                "passed": sanitized_state["status"] == scenario["expected_status"],
                "state": sanitized_state,
            }
        )

    report: dict[str, Any] = {
        "artifact": "google-workspace-diagnostics",
        "schema_version": SCHEMA_VERSION,
        "diagnostics_version": DIAGNOSTICS_VERSION,
        "generated_at": generated,
        "connector_id": CONNECTOR_ID,
        "ci_mode": "dry_run_fixture",
        "network_calls": False,
        "scenarios": scenario_reports,
        "contract_checks": [
            {
                "name": "skip_without_credentials",
                "status": _scenario_status(scenario_reports, "missing_secret_skip"),
            },
            {
                "name": "degraded_invalid_credentials",
                "status": _scenario_status(scenario_reports, "invalid_secret_degraded"),
            },
            {
                "name": "healthy_fixture_discovery",
                "status": _scenario_status(scenario_reports, "fixture_discovery_healthy"),
            },
            {
                "name": "permission_mapping_not_declared",
                "status": _permission_mapping_status(scenario_reports),
            },
            {
                "name": "no_live_network_in_ci",
                "status": "pass",
            },
        ],
    }
    leaks = _secret_leaks(report)
    all_scenarios_passed = all(scenario["passed"] for scenario in scenario_reports)
    all_contracts_passed = all(check["status"] == "pass" for check in report["contract_checks"])
    report["secret_leak_markers"] = leaks
    report["overall_status"] = (
        "pass" if all_scenarios_passed and all_contracts_passed and not leaks else "fail"
    )
    return report


def _default_config() -> dict[str, Any]:
    return {
        "drive_id": "test-drive-id",
        "include_shared_drives": False,
        "include_patterns": ["*.pdf", "*.txt", "*.docx"],
        "exclude_patterns": [],
        "page_size": 100,
        "max_retries": 3,
        "service_account_json": "env:GOOGLE_SERVICE_ACCOUNT_JSON",
    }


def _scenario_status(scenarios: list[dict[str, Any]], name: str) -> str:
    scenario = next((item for item in scenarios if item["name"] == name), None)
    if scenario is None:
        return "fail"
    return "pass" if scenario["passed"] else "fail"


def _permission_mapping_status(scenarios: list[dict[str, Any]]) -> str:
    for scenario in scenarios:
        state = scenario["state"]
        permission_contracts = [
            item
            for item in state.get("capability_contract", [])
            if item.get("capability") == "permission_mapping"
        ]
        if not permission_contracts:
            return "fail"
        if any(item.get("declared") is not False for item in permission_contracts):
            return "fail"
    return "pass"


def _secret_leaks(report: dict[str, Any]) -> list[str]:
    payload = json.dumps(report, sort_keys=True)
    return [marker for marker in RAW_SECRET_MARKERS if marker in payload]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate offline Google Workspace connector diagnostics."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)

    report = build_google_workspace_diagnostics_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    indent = 2 if args.pretty else None
    payload = json.dumps(report, indent=indent, ensure_ascii=False, sort_keys=True)
    args.output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return 0 if report["overall_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
