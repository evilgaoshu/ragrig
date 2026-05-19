"""Unit tests for the Slack source connector."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping
from unittest.mock import MagicMock, patch

import pytest

from ragrig.plugins.sources.slack.config import SlackSourceConfig
from ragrig.plugins.sources.slack.connector import (
    _build_headers,
    _check_slack_response,
    _fetch_channel_messages,
    _format_message,
    _list_all_channels,
    _resolve_token,
    ingest_slack_source,
)
from ragrig.plugins.sources.slack.errors import (
    SlackAuthError,
    SlackConfigError,
    SlackSourceError,
)

pytestmark = pytest.mark.unit


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_message(ts: str, user: str, text: str) -> dict[str, Any]:
    return {"ts": ts, "user": user, "text": text, "type": "message"}


def _make_transport(responses: dict[str, tuple[int, dict[str, Any]]]):
    """Build a stub transport that matches by URL substring."""

    def transport(
        method: str,
        url: str,
        headers: Mapping[str, str],
        params: Mapping[str, object] | None,
    ) -> tuple[int, dict[str, Any]]:
        for key, (status, body) in responses.items():
            if key in url:
                return status, body
        return 200, {"ok": False, "error": f"no_stub_for_{url}"}

    return transport


# ── Error hierarchy ───────────────────────────────────────────────────────────


def test_error_hierarchy() -> None:
    assert issubclass(SlackAuthError, SlackSourceError)
    assert issubclass(SlackConfigError, SlackSourceError)


# ── Config tests ──────────────────────────────────────────────────────────────


def test_config_from_dict_valid() -> None:
    cfg = SlackSourceConfig.from_dict(
        {
            "bot_token": "env:SLACK_BOT_TOKEN",
            "channel_ids": ["C01234567", "C09876543"],
            "include_all_channels": False,
            "oldest_days": 14,
            "page_size": 100,
        }
    )
    assert cfg.bot_token == "env:SLACK_BOT_TOKEN"
    assert cfg.channel_ids == ["C01234567", "C09876543"]
    assert cfg.include_all_channels is False
    assert cfg.oldest_days == 14
    assert cfg.page_size == 100


def test_config_defaults() -> None:
    cfg = SlackSourceConfig.from_dict({"bot_token": "xoxb-test"})
    assert cfg.channel_ids == []
    assert cfg.include_all_channels is False
    assert cfg.oldest_days == 30
    assert cfg.page_size == 200


def test_config_missing_bot_token_raises() -> None:
    with pytest.raises(SlackConfigError, match="bot_token is required"):
        SlackSourceConfig.from_dict({})


def test_config_empty_bot_token_raises() -> None:
    with pytest.raises(SlackConfigError, match="bot_token is required"):
        SlackSourceConfig.from_dict({"bot_token": ""})


# ── Token resolution ──────────────────────────────────────────────────────────


def test_resolve_token_env_ref() -> None:
    assert _resolve_token("env:SLACK_BOT_TOKEN", {"SLACK_BOT_TOKEN": "xoxb-abc"}) == "xoxb-abc"


def test_resolve_token_missing_env_raises() -> None:
    with pytest.raises(SlackAuthError, match="SLACK_BOT_TOKEN"):
        _resolve_token("env:SLACK_BOT_TOKEN", {})


def test_resolve_token_literal_value() -> None:
    assert _resolve_token("xoxb-literal", {}) == "xoxb-literal"


# ── Header building ───────────────────────────────────────────────────────────


def test_build_headers() -> None:
    headers = _build_headers("xoxb-test")
    assert headers["Authorization"] == "Bearer xoxb-test"
    assert "Content-Type" in headers


# ── Response checking ─────────────────────────────────────────────────────────


def test_check_slack_response_ok() -> None:
    # Should not raise
    _check_slack_response(200, {"ok": True}, "test")


def test_check_slack_response_http_401_raises_auth_error() -> None:
    with pytest.raises(SlackAuthError, match="HTTP 401"):
        _check_slack_response(401, {}, "test")


def test_check_slack_response_http_403_raises_auth_error() -> None:
    with pytest.raises(SlackAuthError, match="HTTP 403"):
        _check_slack_response(403, {}, "test")


def test_check_slack_response_http_500_raises_config_error() -> None:
    with pytest.raises(SlackConfigError, match="HTTP 500"):
        _check_slack_response(500, {}, "test")


def test_check_slack_response_ok_false_auth_error() -> None:
    with pytest.raises(SlackAuthError, match="not_authed"):
        _check_slack_response(200, {"ok": False, "error": "not_authed"}, "test")


def test_check_slack_response_ok_false_config_error() -> None:
    with pytest.raises(SlackConfigError, match="channel_not_found"):
        _check_slack_response(200, {"ok": False, "error": "channel_not_found"}, "test")


# ── Message formatting ────────────────────────────────────────────────────────


def test_format_message() -> None:
    msg = _make_message("1234567890.123456", "U01ABCDEF", "Hello world")
    formatted = _format_message(msg, "general")
    assert "general" in formatted
    assert "1234567890.123456" in formatted
    assert "U01ABCDEF" in formatted
    assert "Hello world" in formatted


def test_format_message_no_user_falls_back() -> None:
    msg = {"ts": "111.0", "text": "bot message", "username": "mybot"}
    formatted = _format_message(msg, "random")
    assert "mybot" in formatted


# ── List all channels ─────────────────────────────────────────────────────────


def test_list_all_channels_single_page() -> None:
    body = {
        "ok": True,
        "channels": [
            {"id": "C001", "name": "general"},
            {"id": "C002", "name": "random"},
        ],
        "response_metadata": {"next_cursor": ""},
    }
    transport = _make_transport({"conversations.list": (200, body)})
    headers = _build_headers("xoxb-test")
    channels = _list_all_channels(headers=headers, transport=transport)
    assert len(channels) == 2
    assert channels[0] == {"id": "C001", "name": "general"}
    assert channels[1] == {"id": "C002", "name": "random"}


def test_list_all_channels_auth_error() -> None:
    transport = _make_transport({"conversations.list": (200, {"ok": False, "error": "not_authed"})})
    with pytest.raises(SlackAuthError, match="not_authed"):
        _list_all_channels(headers={}, transport=transport)


# ── Fetch channel messages ────────────────────────────────────────────────────


def test_fetch_channel_messages_single_page() -> None:
    body = {
        "ok": True,
        "messages": [
            _make_message("1000.0", "U001", "Hello"),
            _make_message("2000.0", "U002", "World"),
        ],
        "has_more": False,
    }
    transport = _make_transport({"conversations.history": (200, body)})
    headers = _build_headers("xoxb-test")
    messages = _fetch_channel_messages(
        "C001", oldest=0, page_size=200, headers=headers, transport=transport
    )
    assert len(messages) == 2


def test_fetch_channel_messages_empty() -> None:
    body = {"ok": True, "messages": [], "has_more": False}
    transport = _make_transport({"conversations.history": (200, body)})
    messages = _fetch_channel_messages(
        "C001", oldest=0, page_size=200, headers={}, transport=transport
    )
    assert messages == []


def test_fetch_channel_messages_channel_not_found_raises() -> None:
    body = {"ok": False, "error": "channel_not_found"}
    transport = _make_transport({"conversations.history": (200, body)})
    with pytest.raises(SlackConfigError, match="channel_not_found"):
        _fetch_channel_messages("C999", oldest=0, page_size=200, headers={}, transport=transport)


# ── Full ingest_slack_source ──────────────────────────────────────────────────


def test_ingest_slack_source_with_channel_ids(tmp_path) -> None:
    """ingest_slack_source with explicit channel IDs calls ingest_local_directory."""
    info_body = {"ok": True, "channel": {"id": "C001", "name": "general"}}
    history_body = {
        "ok": True,
        "messages": [_make_message("1000.0", "U001", "Hello!")],
        "has_more": False,
    }

    def transport(method, url, headers, params):
        if "conversations.info" in url:
            return 200, info_body
        if "conversations.history" in url:
            return 200, history_body
        return 200, {"ok": False, "error": "not_found"}

    session = MagicMock()

    from ragrig.ingestion.pipeline import IngestionReport

    fake_report = IngestionReport("r", 1, 1, 0, 0)

    with patch("ragrig.plugins.sources.slack.connector.ingest_local_directory") as mock_ingest:
        mock_ingest.return_value = fake_report
        report = ingest_slack_source(
            session,
            knowledge_base_name="test-kb",
            config={
                "bot_token": "xoxb-fake",
                "channel_ids": ["C001"],
            },
            transport=transport,
        )

    assert report is fake_report
    mock_ingest.assert_called_once()
    call_kwargs = mock_ingest.call_args.kwargs
    assert call_kwargs["knowledge_base_name"] == "test-kb"
    assert isinstance(call_kwargs["root_path"], Path)


def test_ingest_slack_source_include_all_channels(tmp_path) -> None:
    """ingest_slack_source with include_all_channels fetches the channel list."""
    list_body = {
        "ok": True,
        "channels": [{"id": "C001", "name": "eng"}],
        "response_metadata": {"next_cursor": ""},
    }
    history_body = {
        "ok": True,
        "messages": [_make_message("1000.0", "U001", "Build passed!")],
        "has_more": False,
    }

    def transport(method, url, headers, params):
        if "conversations.list" in url:
            return 200, list_body
        if "conversations.history" in url:
            return 200, history_body
        return 200, {"ok": False, "error": "not_found"}

    session = MagicMock()

    from ragrig.ingestion.pipeline import IngestionReport

    fake_report = IngestionReport("r", 1, 1, 0, 0)

    with patch("ragrig.plugins.sources.slack.connector.ingest_local_directory") as mock_ingest:
        mock_ingest.return_value = fake_report
        ingest_slack_source(
            session,
            knowledge_base_name="kb",
            config={
                "bot_token": "xoxb-fake",
                "include_all_channels": True,
            },
            transport=transport,
        )

    mock_ingest.assert_called_once()


def test_ingest_slack_source_env_token(tmp_path) -> None:
    """Bot token is resolved from environment when using env:VAR."""
    list_body = {"ok": True, "channels": [], "response_metadata": {"next_cursor": ""}}

    def transport(method, url, headers, params):
        if "conversations.list" in url:
            return 200, list_body
        return 200, {"ok": False}

    session = MagicMock()

    from ragrig.ingestion.pipeline import IngestionReport

    fake_report = IngestionReport("r", 0, 0, 0, 0)

    with patch("ragrig.plugins.sources.slack.connector.ingest_local_directory") as mock_ingest:
        mock_ingest.return_value = fake_report
        ingest_slack_source(
            session,
            knowledge_base_name="kb",
            config={"bot_token": "env:MY_TOKEN", "include_all_channels": True},
            env={"MY_TOKEN": "xoxb-resolved"},
            transport=transport,
        )


def test_ingest_slack_source_missing_env_token_raises() -> None:
    session = MagicMock()
    with pytest.raises(SlackAuthError, match="MY_TOKEN"):
        ingest_slack_source(
            session,
            knowledge_base_name="kb",
            config={"bot_token": "env:MY_TOKEN", "channel_ids": ["C001"]},
            env={},
            transport=lambda *a, **kw: (200, {"ok": True}),
        )


def test_ingest_slack_source_no_channels_no_all_raises() -> None:
    """Raises SlackConfigError when no channel_ids and include_all_channels is False."""
    session = MagicMock()
    with pytest.raises(SlackConfigError, match="channel_ids"):
        ingest_slack_source(
            session,
            knowledge_base_name="kb",
            config={"bot_token": "xoxb-fake", "channel_ids": []},
            transport=lambda *a, **kw: (200, {"ok": True}),
        )


def test_ingest_slack_source_empty_channel_skipped(tmp_path) -> None:
    """Channels with no messages do not produce output files."""
    info_body = {"ok": True, "channel": {"id": "C001", "name": "quiet"}}
    history_body = {"ok": True, "messages": [], "has_more": False}

    def transport(method, url, headers, params):
        if "conversations.info" in url:
            return 200, info_body
        if "conversations.history" in url:
            return 200, history_body
        return 200, {"ok": False}

    session = MagicMock()

    from ragrig.ingestion.pipeline import IngestionReport

    fake_report = IngestionReport("r", 0, 0, 0, 0)
    written_files: list[Path] = []

    def fake_ingest(session, *, knowledge_base_name, root_path):
        written_files.extend(list(root_path.iterdir()) if root_path.exists() else [])
        return fake_report

    with patch(
        "ragrig.plugins.sources.slack.connector.ingest_local_directory", side_effect=fake_ingest
    ):
        ingest_slack_source(
            session,
            knowledge_base_name="kb",
            config={"bot_token": "xoxb-fake", "channel_ids": ["C001"]},
            transport=transport,
        )

    # No messages => no file written
    assert written_files == []
