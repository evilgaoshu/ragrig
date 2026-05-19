"""Slack source connector.

Ingests messages from Slack channels via the Slack Web API. All HTTP calls
use ``httpx`` which is already a project dependency — no Slack SDK required.

Authentication uses a bot token supplied via an ``env:VAR`` reference. The
bot must have ``channels:read`` and ``channels:history`` (or the equivalent
private-channel scopes) granted.

The connector:
1. Resolves channels — either from ``channel_ids`` or from
   ``conversations.list`` when ``include_all_channels=True``.
2. For each channel fetches messages newer than ``oldest_days`` using
   ``conversations.history``, paginating via ``cursor``.
3. Formats each message as ``{channel_name} [{timestamp}]: {user_id}: {text}``
   and aggregates all messages per channel into a single plain-text document.
4. Writes one ``.txt`` file per channel to a temporary directory and calls
   ``ingest_local_directory``.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from sqlalchemy.orm import Session

from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.plugins.sources.slack.config import SlackSourceConfig
from ragrig.plugins.sources.slack.errors import SlackAuthError, SlackConfigError

# HTTP transport type: (method, url, headers, params) -> (status_code, json_body)
HttpTransport = Callable[
    [str, str, Mapping[str, str], Mapping[str, object] | None],
    tuple[int, dict[str, Any]],
]


def _resolve_token(token: str, env: Mapping[str, str]) -> str:
    """Resolve an env:VAR reference or return the value as-is."""
    if token.startswith("env:"):
        name = token.removeprefix("env:")
        resolved = env.get(name)
        if resolved is None:
            raise SlackAuthError(f"missing required environment variable: {name}")
        return resolved
    return token


def _default_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    params: Mapping[str, object] | None,
) -> tuple[int, dict[str, Any]]:  # pragma: no cover - real HTTP path
    import httpx

    resp = httpx.request(
        method.upper(),
        url,
        headers=dict(headers),
        params=dict(params) if params else None,
        timeout=30,
    )
    return resp.status_code, resp.json() if resp.content else {}


def _build_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _check_slack_response(status: int, body: dict[str, Any], context: str) -> None:
    """Raise appropriate errors for non-OK Slack API responses."""
    if status in (401, 403):
        raise SlackAuthError(f"Slack authentication failed ({context}): HTTP {status}")
    if status >= 400:
        raise SlackConfigError(f"Slack API error ({context}): HTTP {status}")
    # Slack returns HTTP 200 for most errors but sets ok=False
    if not body.get("ok"):
        error = str(body.get("error") or "unknown_error")
        if error in ("not_authed", "invalid_auth", "account_inactive", "token_revoked"):
            raise SlackAuthError(f"Slack authentication error ({context}): {error}")
        raise SlackConfigError(f"Slack API error ({context}): {error}")


def _list_all_channels(
    *,
    headers: dict[str, str],
    transport: HttpTransport,
) -> list[dict[str, str]]:
    """List all channels the bot has access to via conversations.list."""
    channels: list[dict[str, str]] = []
    cursor: str | None = None

    while True:
        params: dict[str, object] = {"limit": 200, "types": "public_channel,private_channel"}
        if cursor:
            params["cursor"] = cursor

        status, body = transport("GET", "https://slack.com/api/conversations.list", headers, params)
        _check_slack_response(status, body, "conversations.list")

        for ch in body.get("channels") or []:
            if isinstance(ch, dict) and ch.get("id"):
                channels.append({"id": str(ch["id"]), "name": str(ch.get("name") or ch["id"])})

        next_cursor = (body.get("response_metadata") or {}).get("next_cursor") or ""
        if not next_cursor:
            break
        cursor = next_cursor

    return channels


def _fetch_channel_info(
    channel_id: str,
    *,
    headers: dict[str, str],
    transport: HttpTransport,
) -> str:
    """Get the channel name for a given channel ID."""
    params: dict[str, object] = {"channel": channel_id}
    status, body = transport("GET", "https://slack.com/api/conversations.info", headers, params)
    if status >= 400 or not body.get("ok"):
        return channel_id  # Fall back to using the ID as the name
    channel = body.get("channel") or {}
    return str(channel.get("name") or channel_id)


def _fetch_channel_messages(
    channel_id: str,
    *,
    oldest: float,
    page_size: int,
    headers: dict[str, str],
    transport: HttpTransport,
) -> list[dict[str, Any]]:
    """Fetch all messages for a channel newer than oldest timestamp."""
    messages: list[dict[str, Any]] = []
    cursor: str | None = None

    while True:
        params: dict[str, object] = {
            "channel": channel_id,
            "oldest": str(oldest),
            "limit": page_size,
        }
        if cursor:
            params["cursor"] = cursor

        status, body = transport(
            "GET", "https://slack.com/api/conversations.history", headers, params
        )
        _check_slack_response(status, body, f"conversations.history channel={channel_id}")

        for msg in body.get("messages") or []:
            if isinstance(msg, dict):
                messages.append(msg)

        has_more = bool(body.get("has_more"))
        if not has_more:
            break
        next_cursor = (body.get("response_metadata") or {}).get("next_cursor") or ""
        if not next_cursor:
            break
        cursor = next_cursor

    return messages


def _format_message(msg: dict[str, Any], channel_name: str) -> str:
    """Format a Slack message into a readable string."""
    ts = str(msg.get("ts") or "")
    user = str(msg.get("user") or msg.get("username") or "unknown")
    text = str(msg.get("text") or "")
    return f"{channel_name} [{ts}]: {user}: {text}"


def ingest_slack_source(
    session: Session,
    *,
    knowledge_base_name: str,
    config: dict[str, object] | SlackSourceConfig,
    env: Mapping[str, str] | None = None,
    transport: HttpTransport | None = None,
) -> object:
    """Ingest Slack channel messages into a knowledge base.

    Aggregates messages per channel into a single text document, writes to a
    temporary directory, and runs them through the standard local-directory
    ingestion pipeline.

    Returns an ``IngestionReport``.
    """
    if isinstance(config, dict):
        cfg = SlackSourceConfig.from_dict(config)
    else:
        cfg = config

    _env = env if env is not None else os.environ
    token = _resolve_token(cfg.bot_token, _env)
    fetch = transport or _default_transport
    headers = _build_headers(token)

    oldest = time.time() - cfg.oldest_days * 86400

    # Resolve channels
    if cfg.include_all_channels:
        channel_list = _list_all_channels(headers=headers, transport=fetch)
    else:
        if not cfg.channel_ids:
            raise SlackConfigError(
                "Either channel_ids must be non-empty or include_all_channels must be True"
            )
        channel_list = []
        for ch_id in cfg.channel_ids:
            name = _fetch_channel_info(ch_id, headers=headers, transport=fetch)
            channel_list.append({"id": ch_id, "name": name})

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_root = Path(tmp_dir)
        for channel in channel_list:
            channel_id = channel["id"]
            channel_name = channel["name"]

            messages = _fetch_channel_messages(
                channel_id,
                oldest=oldest,
                page_size=cfg.page_size,
                headers=headers,
                transport=fetch,
            )

            if not messages:
                continue

            lines = [_format_message(msg, channel_name) for msg in messages]
            content = "\n".join(lines)

            # Use a safe filename derived from the channel name
            safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in channel_name)
            dest = tmp_root / f"{safe_name}.txt"
            dest.write_text(content, encoding="utf-8")

        report = ingest_local_directory(
            session,
            knowledge_base_name=knowledge_base_name,
            root_path=tmp_root,
        )

    return report
