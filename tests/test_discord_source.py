"""Unit tests for the Discord source connector."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
from unittest.mock import MagicMock, patch

import pytest

from ragrig.plugins import build_plugin_registry
from ragrig.plugins.sources.discord.config import DiscordSourceConfig
from ragrig.plugins.sources.discord.connector import (
    _build_headers,
    _check_discord_response,
    _fetch_channel_messages,
    _format_message,
    _resolve_token,
    ingest_discord_source,
)
from ragrig.plugins.sources.discord.errors import (
    DiscordAuthError,
    DiscordConfigError,
    DiscordRateLimitError,
    DiscordSourceError,
)

pytestmark = pytest.mark.unit


def _make_message(message_id: str, text: str) -> dict[str, Any]:
    return {
        "id": message_id,
        "timestamp": "2026-01-01T00:00:00.000000+00:00",
        "author": {"id": "U001", "username": "release-lead"},
        "content": text,
    }


def test_error_hierarchy() -> None:
    assert issubclass(DiscordAuthError, DiscordSourceError)
    assert issubclass(DiscordConfigError, DiscordSourceError)
    assert issubclass(DiscordRateLimitError, DiscordSourceError)


def test_config_from_dict_valid() -> None:
    cfg = DiscordSourceConfig.from_dict(
        {
            "bot_token": "env:DISCORD_BOT_TOKEN",
            "guild_id": "G001",
            "channel_ids": ["C001"],
            "include_threads": True,
            "oldest_days": 14,
            "page_size": 50,
            "max_messages_per_channel": 120,
        }
    )

    assert cfg.bot_token == "env:DISCORD_BOT_TOKEN"
    assert cfg.guild_id == "G001"
    assert cfg.channel_ids == ["C001"]
    assert cfg.include_threads is True
    assert cfg.oldest_days == 14
    assert cfg.page_size == 50
    assert cfg.max_messages_per_channel == 120


def test_config_requires_token_and_channels() -> None:
    with pytest.raises(DiscordConfigError, match="bot_token is required"):
        DiscordSourceConfig.from_dict({})
    with pytest.raises(DiscordConfigError, match="channel_ids"):
        DiscordSourceConfig.from_dict({"bot_token": "x", "channel_ids": []})


def test_resolve_token_env_ref() -> None:
    assert _resolve_token("env:DISCORD_BOT_TOKEN", {"DISCORD_BOT_TOKEN": "bot-secret"}) == (
        "bot-secret"
    )


def test_resolve_token_missing_env_raises() -> None:
    with pytest.raises(DiscordAuthError, match="DISCORD_BOT_TOKEN"):
        _resolve_token("env:DISCORD_BOT_TOKEN", {})


def test_build_headers() -> None:
    headers = _build_headers("bot-secret")
    assert headers["Authorization"] == "Bot bot-secret"
    assert "User-Agent" in headers


def test_check_discord_response_auth_and_rate_limit_errors() -> None:
    with pytest.raises(DiscordAuthError, match="HTTP 401"):
        _check_discord_response(401, {}, "channel")
    with pytest.raises(DiscordRateLimitError, match="rate limited"):
        _check_discord_response(429, {"retry_after": 1.5}, "messages")
    with pytest.raises(DiscordConfigError, match="HTTP 404"):
        _check_discord_response(404, {"message": "Unknown Channel"}, "channel")


def test_format_message_includes_audit_fields() -> None:
    formatted = _format_message(_make_message("M001", "Ship it"), "C001", "announcements")

    assert "announcements" in formatted
    assert "channel_id=C001" in formatted
    assert "message_id=M001" in formatted
    assert "author_id=U001" in formatted
    assert "Ship it" in formatted


def test_fetch_channel_messages_paginates() -> None:
    calls: list[Mapping[str, object] | None] = []

    def transport(method: str, url: str, headers: Mapping[str, str], params: Mapping[str, object]):
        calls.append(params)
        if len(calls) == 1:
            return 200, [_make_message("20", "newer"), _make_message("10", "older")]
        return 200, [_make_message("5", "oldest")]

    messages = _fetch_channel_messages(
        "C001",
        oldest_timestamp=0.0,
        page_size=2,
        max_messages=3,
        headers={},
        transport=transport,
    )

    assert [m["id"] for m in messages] == ["20", "10", "5"]
    assert calls[1]["before"] == "10"


def test_ingest_discord_source_writes_channel_document() -> None:
    channel_body = {"id": "C001", "name": "announcements"}
    messages_body = [_make_message("20", "Release checklist is ready.")]
    captured_files: dict[str, str] = {}

    def transport(method: str, url: str, headers: Mapping[str, str], params: Mapping[str, object]):
        if url.endswith("/channels/C001"):
            return 200, channel_body
        if url.endswith("/channels/C001/messages"):
            return 200, messages_body
        return 404, {"message": "no stub"}

    from ragrig.ingestion.pipeline import IngestionReport

    fake_report = IngestionReport("r", 1, 1, 0, 0)

    def fake_ingest(session, *, knowledge_base_name: str, root_path: Path):
        assert knowledge_base_name == "kb"
        for file_path in root_path.iterdir():
            captured_files[file_path.name] = file_path.read_text(encoding="utf-8")
        return fake_report

    with patch(
        "ragrig.plugins.sources.discord.connector.ingest_local_directory",
        side_effect=fake_ingest,
    ):
        report = ingest_discord_source(
            MagicMock(),
            knowledge_base_name="kb",
            config={"bot_token": "env:BOT", "channel_ids": ["C001"], "oldest_days": 365},
            env={"BOT": "bot-secret"},
            transport=transport,
        )

    assert report is fake_report
    assert "announcements.txt" in captured_files
    assert "Release checklist is ready." in captured_files["announcements.txt"]


def test_plugin_registry_exposes_discord_source() -> None:
    manifest = build_plugin_registry().get("source.discord")

    assert manifest.family == "discord"
    validated = manifest.config_model.model_validate(
        {
            "bot_token": "env:DISCORD_BOT_TOKEN",
            "channel_ids": ["C001"],
        }
    )
    assert validated.bot_token == "env:DISCORD_BOT_TOKEN"
