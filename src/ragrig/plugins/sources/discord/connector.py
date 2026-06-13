"""Discord source connector.

Ingests messages from Discord channels via the REST API using ``httpx``.
Messages are aggregated per channel/thread into plain-text documents and sent
through the standard local-directory ingestion pipeline.
"""

from __future__ import annotations

import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from sqlalchemy.orm import Session

from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.plugins.sources.discord.config import DiscordSourceConfig
from ragrig.plugins.sources.discord.errors import (
    DiscordAuthError,
    DiscordConfigError,
    DiscordRateLimitError,
)

HttpTransport = Callable[
    [str, str, Mapping[str, str], Mapping[str, object] | None],
    tuple[int, Any],
]

DISCORD_API_BASE = "https://discord.com/api/v10"


def _resolve_token(token: str, env: Mapping[str, str]) -> str:
    if token.startswith("env:"):
        name = token.removeprefix("env:")
        resolved = env.get(name)
        if resolved is None:
            raise DiscordAuthError(f"missing required environment variable: {name}")
        return resolved
    return token


def _default_transport(
    method: str,
    url: str,
    headers: Mapping[str, str],
    params: Mapping[str, object] | None,
) -> tuple[int, Any]:  # pragma: no cover - real HTTP path
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
        "Authorization": f"Bot {token}",
        "User-Agent": "RAGRig Discord Source (https://github.com/evilgaoshu/ragrig)",
    }


def _check_discord_response(status: int, body: Any, context: str) -> None:
    if status in (401, 403):
        raise DiscordAuthError(f"Discord authentication failed ({context}): HTTP {status}")
    if status == 429:
        retry_after = ""
        if isinstance(body, dict) and body.get("retry_after") is not None:
            retry_after = f" retry_after={body['retry_after']}"
        raise DiscordRateLimitError(f"Discord API rate limited ({context}):{retry_after}")
    if status >= 400:
        detail = ""
        if isinstance(body, dict) and body.get("message"):
            detail = f" {body['message']}"
        raise DiscordConfigError(f"Discord API error ({context}): HTTP {status}{detail}")


def _fetch_channel_info(
    channel_id: str,
    *,
    headers: Mapping[str, str],
    transport: HttpTransport,
) -> dict[str, str]:
    status, body = transport("GET", f"{DISCORD_API_BASE}/channels/{channel_id}", headers, None)
    _check_discord_response(status, body, f"channel={channel_id}")
    if not isinstance(body, dict):
        raise DiscordConfigError(f"Discord channel response was not an object: {channel_id}")
    return {
        "id": str(body.get("id") or channel_id),
        "name": str(body.get("name") or channel_id),
        "parent_id": str(body.get("parent_id") or ""),
    }


def _fetch_active_threads(
    guild_id: str,
    *,
    parent_channel_ids: set[str],
    headers: Mapping[str, str],
    transport: HttpTransport,
) -> list[dict[str, str]]:
    status, body = transport(
        "GET", f"{DISCORD_API_BASE}/guilds/{guild_id}/threads/active", headers, None
    )
    _check_discord_response(status, body, f"guild_threads={guild_id}")
    if not isinstance(body, dict):
        return []
    threads: list[dict[str, str]] = []
    for thread in body.get("threads") or []:
        if not isinstance(thread, dict):
            continue
        parent_id = str(thread.get("parent_id") or "")
        thread_id = str(thread.get("id") or "")
        if thread_id and parent_id in parent_channel_ids:
            threads.append(
                {
                    "id": thread_id,
                    "name": str(thread.get("name") or thread_id),
                    "parent_id": parent_id,
                }
            )
    return threads


def _fetch_channel_messages(
    channel_id: str,
    *,
    oldest_timestamp: float,
    page_size: int,
    max_messages: int | None,
    headers: Mapping[str, str],
    transport: HttpTransport,
) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    before: str | None = None

    while True:
        params: dict[str, object] = {"limit": page_size}
        if before:
            params["before"] = before
        status, body = transport(
            "GET",
            f"{DISCORD_API_BASE}/channels/{channel_id}/messages",
            headers,
            params,
        )
        _check_discord_response(status, body, f"messages channel={channel_id}")
        if not isinstance(body, list):
            raise DiscordConfigError(f"Discord messages response was not a list: {channel_id}")
        if not body:
            break

        stop_for_oldest = False
        for raw in body:
            if not isinstance(raw, dict):
                continue
            created_at = _message_timestamp(raw)
            if created_at is not None and created_at < oldest_timestamp:
                stop_for_oldest = True
                continue
            messages.append(raw)
            if max_messages is not None and len(messages) >= max_messages:
                return messages

        if len(body) < page_size or stop_for_oldest:
            break
        before = str(body[-1].get("id") or "")
        if not before:
            break

    return messages


def _format_message(msg: dict[str, Any], channel_id: str, channel_name: str) -> str:
    author = msg.get("author") if isinstance(msg.get("author"), dict) else {}
    author_id = str(author.get("id") or msg.get("user_id") or "unknown")
    author_name = str(author.get("username") or author_id)
    timestamp = str(msg.get("timestamp") or "")
    message_id = str(msg.get("id") or "")
    content = str(msg.get("content") or "")
    return (
        f"{channel_name} [{timestamp}] channel_id={channel_id} "
        f"message_id={message_id} author_id={author_id} author={author_name}: {content}"
    )


def ingest_discord_source(
    session: Session,
    *,
    knowledge_base_name: str,
    config: dict[str, object] | DiscordSourceConfig,
    env: Mapping[str, str] | None = None,
    transport: HttpTransport | None = None,
) -> object:
    if isinstance(config, dict):
        cfg = DiscordSourceConfig.from_dict(config)
    else:
        cfg = config

    _env = env if env is not None else os.environ
    token = _resolve_token(cfg.bot_token, _env)
    fetch = transport or _default_transport
    headers = _build_headers(token)
    oldest = time.time() - cfg.oldest_days * 86400

    channels = [
        _fetch_channel_info(channel_id, headers=headers, transport=fetch)
        for channel_id in cfg.channel_ids
    ]
    if cfg.include_threads and cfg.guild_id:
        channels.extend(
            _fetch_active_threads(
                cfg.guild_id,
                parent_channel_ids=set(cfg.channel_ids),
                headers=headers,
                transport=fetch,
            )
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_root = Path(tmp_dir)
        for channel in channels:
            channel_id = channel["id"]
            channel_name = channel["name"]
            messages = _fetch_channel_messages(
                channel_id,
                oldest_timestamp=oldest,
                page_size=cfg.page_size,
                max_messages=cfg.max_messages_per_channel,
                headers=headers,
                transport=fetch,
            )
            if not messages:
                continue
            lines = [_format_message(msg, channel_id, channel_name) for msg in messages]
            dest = tmp_root / f"{_safe_filename(channel_name)}.txt"
            dest.write_text("\n".join(lines), encoding="utf-8")

        return ingest_local_directory(
            session,
            knowledge_base_name=knowledge_base_name,
            root_path=tmp_root,
        )


def _message_timestamp(msg: dict[str, Any]) -> float | None:
    raw = msg.get("timestamp")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.timestamp()


def _safe_filename(value: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in value)
    return safe or "discord-channel"
