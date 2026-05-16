"""Outbound alert webhooks.

Fires JSON POST requests to the configured URL on pipeline failures and completions.
Supports:
  - Generic HTTP endpoints (receives RAGRig event payload)
  - Slack Incoming Webhooks (auto-detected by URL, formats as Slack blocks)

Signing: when RAGRIG_WEBHOOK_SECRET is set, adds X-RAGRig-Signature-256 header
(HMAC-SHA256 of the raw body, matching the GitHub webhook signing convention).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import threading
from datetime import UTC, datetime
from typing import Any

import httpx

from ragrig.config import Settings

logger = logging.getLogger(__name__)

_EVENT_TASK_FAILURE = "task.failure"
_EVENT_TASK_COMPLETE = "task.complete"
_EVENT_PIPELINE_FAILURE = "pipeline.failure"
_EVENT_PIPELINE_COMPLETE = "pipeline.complete"


def _sign(payload_bytes: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode(), payload_bytes, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def _slack_payload(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    emoji = ":x:" if "failure" in event_type else ":white_check_mark:"
    title = event_type.replace(".", " ").title()
    lines = [f"{emoji} *{title}*"]
    for k, v in data.items():
        if v is not None:
            lines.append(f"  • *{k}*: {v}")
    return {"text": "\n".join(lines)}


def _build_payload(event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": event_type,
        "occurred_at": datetime.now(UTC).isoformat(),
        "data": data,
    }


def _fire(settings: Settings, event_type: str, data: dict[str, Any]) -> None:
    url = settings.ragrig_webhook_url
    if not url:
        return

    is_slack = "hooks.slack.com" in url or url.endswith("/slack")
    if is_slack:
        body = _slack_payload(event_type, data)
    else:
        body = _build_payload(event_type, data)

    raw = json.dumps(body, default=str).encode()
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if settings.ragrig_webhook_secret:
        headers["X-RAGRig-Signature-256"] = _sign(raw, settings.ragrig_webhook_secret)

    try:
        resp = httpx.post(url, content=raw, headers=headers, timeout=8)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("webhook delivery failed: %s", exc)


def _fire_async(settings: Settings, event_type: str, data: dict[str, Any]) -> None:
    """Fire the webhook in a daemon thread so it never blocks the caller."""
    t = threading.Thread(target=_fire, args=(settings, event_type, data), daemon=True)
    t.start()


# ── Public helpers ────────────────────────────────────────────────────────────


def notify_task_failure(
    settings: Settings,
    *,
    task_id: str,
    task_type: str,
    error: str,
    knowledge_base_name: str | None = None,
) -> None:
    if not settings.ragrig_webhook_url or not settings.ragrig_webhook_on_failure:
        return
    _fire_async(
        settings,
        _EVENT_TASK_FAILURE,
        {
            "task_id": task_id,
            "task_type": task_type,
            "error": error[:500],
            "knowledge_base": knowledge_base_name,
        },
    )


def notify_task_complete(
    settings: Settings,
    *,
    task_id: str,
    task_type: str,
    knowledge_base_name: str | None = None,
    summary: dict[str, Any] | None = None,
) -> None:
    if not settings.ragrig_webhook_url or not settings.ragrig_webhook_on_completion:
        return
    _fire_async(
        settings,
        _EVENT_TASK_COMPLETE,
        {
            "task_id": task_id,
            "task_type": task_type,
            "knowledge_base": knowledge_base_name,
            **(summary or {}),
        },
    )


def deliver_webhook(settings: Settings, *, payload: dict[str, Any]) -> None:
    """Fire a generic event payload to the configured webhook URL.

    Used by P3+ alert flows (budget thresholds, etc.). No-op when no URL is
    configured. The payload's ``event`` field becomes the event type.
    """
    if not settings.ragrig_webhook_url:
        return
    event_type = str(payload.get("event") or "ragrig.event")
    data = {k: v for k, v in payload.items() if k != "event"}
    _fire_async(settings, event_type, data)


def notify_pipeline_failure(
    settings: Settings,
    *,
    run_id: str,
    knowledge_base_name: str,
    error: str,
) -> None:
    if not settings.ragrig_webhook_url or not settings.ragrig_webhook_on_failure:
        return
    _fire_async(
        settings,
        _EVENT_PIPELINE_FAILURE,
        {
            "run_id": run_id,
            "knowledge_base": knowledge_base_name,
            "error": error[:500],
        },
    )
