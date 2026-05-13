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
    GoogleWorkspaceScanResult,
    _resolve_credential,
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

    state: dict[str, Any] = {
        "connector_id": "source.google_workspace",
        "status": credential_status,
        "config_valid": credential_reason is None,
        "schema_version": "1.0.0",
        "last_discovery_at": ts if scan_result else None,
        "skip_reason": credential_reason if credential_status == "skip" else None,
        "degraded_reason": credential_reason if credential_status == "degraded" else None,
        "next_step_command": (
            "ragrig-connectors google-workspace configure --credentials"
            if credential_status != "healthy"
            else "ragrig-connectors google-workspace discover --cursor next"
        ),
    }

    if scan_result:
        state["last_discovery"] = {
            "status": "healthy" if scan_result.discovered else "skip",
            "total_count": scan_result.total_count,
            "skipped_count": len(scan_result.skipped),
            "next_cursor": scan_result.next_cursor,
            "items": [
                {
                    "item_id": item.item_id,
                    "name": item.name,
                    "mime_type": item.mime_type,
                    "modified_at": item.modified_at.isoformat(),
                    "etag": item.etag,
                    "version": item.version,
                }
                for item in scan_result.discovered
            ],
        }
    else:
        state["last_discovery"] = None

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
                lines.append(f"    - {item['item_id']}: {item['name']} ({item['mime_type']})")

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
