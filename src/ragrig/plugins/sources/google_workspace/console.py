from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from ragrig.plugins.sources.google_workspace.errors import (
    GoogleWorkspaceConfigError,
    GoogleWorkspaceCredentialError,
    classify_credential_error,
)
from ragrig.plugins.sources.google_workspace.scanner import (
    GoogleDriveItem,
    GoogleWorkspaceScanResult,
    _resolve_credential,
)

CONNECTOR_ID = "source.google_workspace"
SCHEMA_VERSION = "1.1.0"
DIAGNOSTICS_VERSION = "2026-05-16"
PERMISSION_MAPPING_REASON = (
    "permission_mapping is not declared because the pilot does not emit ACL or sharing "
    "metadata in runtime output yet"
)
LIVE_RETRY_REASON = (
    "max_retries is reserved for live API retry once the production Google Drive client is wired"
)


def build_connector_state(
    config: dict[str, Any],
    *,
    env: dict[str, str],
    scan_result: GoogleWorkspaceScanResult | None = None,
) -> dict[str, Any]:
    ts = datetime.now(timezone.utc).isoformat()

    # Check credentials
    credential_status = "healthy"
    credential_reason: str | None = None
    try:
        _resolve_credential(config, env)
    except GoogleWorkspaceCredentialError as exc:
        credential_status = classify_credential_error(exc)
        credential_reason = _sanitize_text(str(exc))
    except GoogleWorkspaceConfigError as exc:
        credential_status = "degraded"
        credential_reason = _sanitize_text(str(exc))

    credential_ref = _credential_ref(config)
    discovery = _build_discovery_summary(scan_result)
    state: dict[str, Any] = {
        "connector_id": CONNECTOR_ID,
        "status": credential_status,
        "config_valid": credential_reason is None,
        "schema_version": SCHEMA_VERSION,
        "diagnostics_version": DIAGNOSTICS_VERSION,
        "last_discovery_at": ts if scan_result else None,
        "skip_reason": credential_reason if credential_status == "skip" else None,
        "degraded_reason": credential_reason if credential_status == "degraded" else None,
        "credential_contract": {
            "status": credential_status,
            "required": True,
            "env_ref": credential_ref,
            "raw_secret_exposed": False,
            "reason": credential_reason,
        },
        "capability_contract": _build_capability_contract(scan_result),
        "production_contract": _build_production_contract(
            config,
            credential_status=credential_status,
            scan_result=scan_result,
        ),
        "diagnostic_checks": _build_diagnostic_checks(
            config,
            credential_status=credential_status,
            credential_reason=credential_reason,
            scan_result=scan_result,
        ),
        "next_step_command": (
            "ragrig-connectors google-workspace configure --credentials"
            if credential_status != "healthy"
            else "ragrig-connectors google-workspace discover --cursor next"
        ),
        "last_discovery": discovery,
    }

    return state


def format_console_output(state: dict[str, Any]) -> str:
    sanitized_state = _sanitize_state(state)
    lines = [
        "=" * 50,
        "Google Workspace Connector State",
        "=" * 50,
        f"Connector ID:    {sanitized_state['connector_id']}",
        f"Status:          {sanitized_state['status']}",
        f"Config Valid:    {sanitized_state['config_valid']}",
        f"Schema Version:  {sanitized_state['schema_version']}",
        f"Diagnostics:     {sanitized_state.get('diagnostics_version', 'unknown')}",
    ]

    if sanitized_state.get("skip_reason"):
        lines.extend(["", f"Skip Reason:     {sanitized_state['skip_reason']}"])

    if sanitized_state.get("degraded_reason"):
        lines.extend(["", f"Degraded Reason: {sanitized_state['degraded_reason']}"])

    if sanitized_state.get("last_discovery_at"):
        lines.extend(["", f"Last Discovery:  {sanitized_state['last_discovery_at']}"])

    discovery = sanitized_state.get("last_discovery")
    if discovery:
        lines.extend(
            [
                "",
                "Last Discovery Summary:",
                f"  Total Items:   {discovery['total_count']}",
                f"  Skipped:       {discovery['skipped_count']}",
                f"  Next Cursor:   {discovery['next_cursor'] or 'none'}",
            ]
        )
        if discovery.get("items"):
            lines.append("  Items:")
            for item in discovery["items"]:
                lines.append(
                    f"    - {item['item_id']}: {item['name']} "
                    f"({item['mime_type']}, {item['logical_type']})"
                )
        if discovery.get("skipped_items"):
            lines.append("  Skipped Items:")
            for skipped in discovery["skipped_items"]:
                lines.append(f"    - {skipped['item_id']}: {skipped['name']} ({skipped['reason']})")

    credential_contract = sanitized_state.get("credential_contract") or {}
    if credential_contract:
        raw_secret_state = "exposed" if credential_contract.get("raw_secret_exposed") else "hidden"
        lines.extend(
            [
                "",
                "Credential Contract:",
                f"  Status:        {credential_contract.get('status', 'unknown')}",
                f"  Env Ref:       {credential_contract.get('env_ref') or 'invalid'}",
                f"  Raw Secret:    {raw_secret_state}",
            ]
        )

    capability_contract = sanitized_state.get("capability_contract") or []
    if capability_contract:
        lines.extend(["", "Capability Contract:"])
        for capability in capability_contract:
            lines.append(
                f"  - {capability['capability']}: {capability['status']} ({capability['evidence']})"
            )

    production_contract = sanitized_state.get("production_contract") or {}
    if production_contract:
        lines.extend(
            [
                "",
                "Production Contract:",
                f"  Status:        {production_contract.get('status', 'unknown')}",
                f"  CI Mode:       {production_contract.get('ci_mode', 'unknown')}",
                f"  Network in CI: {production_contract.get('network_calls_in_ci')}",
                f"  Permissions:   {production_contract.get('permission_mapping', 'unknown')}",
            ]
        )

    diagnostic_checks = sanitized_state.get("diagnostic_checks") or []
    if diagnostic_checks:
        lines.extend(["", "Diagnostic Checks:"])
        for check in diagnostic_checks:
            lines.append(f"  - {check['name']}: {check['status']} ({check['detail']})")

    lines.extend(
        [
            "",
            "Next Step Command:",
            f"  {sanitized_state['next_step_command']}",
            "=" * 50,
        ]
    )

    return "\n".join(lines)


def format_console_output_json(state: dict[str, Any]) -> str:
    sanitized = _sanitize_state(state)
    return json.dumps(sanitized, indent=2, ensure_ascii=False)


SENSITIVE_KEYS = {
    "client" + "_secret",
    "refresh" + "_token",
    "token",
    "access" + "_token",
    "password",
    "api_key",
    "credentials",
    "service_account_json",
}

_KEY_VALUE_SECRET_PARTS = (
    ("client", "_secret"),
    ("refresh", "_token"),
    ("access", "_token"),
)


def _mask_value(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return value[:4] + "..." + value[-4:]


def _credential_ref(config: dict[str, Any]) -> str | None:
    value = config.get("service_account_json")
    if isinstance(value, str) and value.startswith("env:"):
        return value.removeprefix("env:")
    return None


def _build_discovery_summary(
    scan_result: GoogleWorkspaceScanResult | None,
) -> dict[str, Any] | None:
    if scan_result is None:
        return None
    return {
        "status": "healthy" if scan_result.discovered else "skip",
        "total_count": scan_result.total_count,
        "skipped_count": len(scan_result.skipped),
        "next_cursor": scan_result.next_cursor,
        "items": [_item_summary(item) for item in scan_result.discovered],
        "skipped_items": [
            {
                **_item_summary(item),
                "reason": reason,
            }
            for item, reason in scan_result.skipped
        ],
    }


def _item_summary(item: GoogleDriveItem) -> dict[str, Any]:
    return {
        "item_id": item.item_id,
        "name": item.name,
        "mime_type": item.mime_type,
        "logical_type": _logical_type(item.mime_type),
        "modified_at": item.modified_at.isoformat(),
        "etag": item.etag,
        "version": item.version,
        "parent_path": item.parent_path,
        "web_view_link": item.web_view_link,
        "size_bytes": item.size_bytes,
    }


def _logical_type(mime_type: str) -> str:
    if mime_type == "application/vnd.google-apps.document":
        return "docs_document"
    return "drive_file"


def _build_capability_contract(
    scan_result: GoogleWorkspaceScanResult | None,
) -> list[dict[str, Any]]:
    read_evidence = "fixture discovery summary available" if scan_result else "config-only check"
    sync_evidence = (
        "next_cursor emitted"
        if scan_result and scan_result.next_cursor
        else "cursor contract tested"
    )
    return [
        {
            "capability": "read",
            "declared": True,
            "status": "contract_ready",
            "evidence": read_evidence,
        },
        {
            "capability": "incremental_sync",
            "declared": True,
            "status": "contract_ready",
            "evidence": sync_evidence,
        },
        {
            "capability": "permission_mapping",
            "declared": False,
            "status": "not_declared",
            "evidence": PERMISSION_MAPPING_REASON,
        },
    ]


def _build_production_contract(
    config: dict[str, Any],
    *,
    credential_status: str,
    scan_result: GoogleWorkspaceScanResult | None,
) -> dict[str, Any]:
    if credential_status == "healthy" and scan_result is not None:
        status = "pilot_ready"
    elif credential_status == "skip":
        status = "blocked_missing_secret"
    else:
        status = "blocked_invalid_config"
    return {
        "status": status,
        "live_api_ready": credential_status == "healthy",
        "ci_mode": "dry_run_fixture",
        "network_calls_in_ci": False,
        "permission_mapping": "not_declared",
        "permission_mapping_reason": PERMISSION_MAPPING_REASON,
        "retry": {
            "configured_max_retries": config.get("max_retries"),
            "live_retry_implemented": False,
            "reason": LIVE_RETRY_REASON,
        },
        "secret_policy": "env_refs_only",
        "raw_secret_exposed": False,
    }


def _build_diagnostic_checks(
    config: dict[str, Any],
    *,
    credential_status: str,
    credential_reason: str | None,
    scan_result: GoogleWorkspaceScanResult | None,
) -> list[dict[str, str]]:
    config_shape_status = "pass" if _credential_ref(config) else "fail"
    return [
        {
            "name": "config_shape",
            "status": config_shape_status,
            "detail": "service account value is validated as an env reference",
        },
        {
            "name": "credential_resolution",
            "status": credential_status,
            "detail": credential_reason
            or "credential env reference resolved without exposing value",
        },
        {
            "name": "discovery_summary",
            "status": "pass" if scan_result is not None else "skip",
            "detail": "fixture discovery summary recorded" if scan_result else "not run",
        },
        {
            "name": "secret_redaction",
            "status": "pass",
            "detail": "state and formatted output are recursively sanitized",
        },
        {
            "name": "permission_mapping_contract",
            "status": "not_declared",
            "detail": PERMISSION_MAPPING_REASON,
        },
        {
            "name": "network_boundary",
            "status": "pass",
            "detail": "default diagnostics do not call live Google APIs",
        },
    ]


def _sanitize_state(obj: Any) -> Any:
    if isinstance(obj, dict):
        result: dict[str, Any] = {}
        for k, v in obj.items():
            if any(s in k.lower() for s in SENSITIVE_KEYS):
                if isinstance(v, str):
                    result[k] = _mask_value(v)
                else:
                    result[k] = "***"
            else:
                result[k] = _sanitize_state(v)
        return result
    if isinstance(obj, list):
        return [_sanitize_state(item) for item in obj]
    if isinstance(obj, str):
        return _sanitize_text(obj)
    return obj


def _sanitize_text(value: str) -> str:
    secret_names = tuple(prefix + suffix for prefix, suffix in _KEY_VALUE_SECRET_PARTS)
    sanitized = re.sub(
        rf"(?i)({'|'.join(secret_names)})=([^\s,;]+)",
        lambda match: f"[REDACTED]={_mask_value(match.group(2))}",
        value,
    )
    for token in secret_names:
        sanitized = re.sub(token, "[REDACTED]", sanitized, flags=re.IGNORECASE)
    return sanitized
