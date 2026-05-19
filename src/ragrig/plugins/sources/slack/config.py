"""Slack source connector configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SlackSourceConfig:
    bot_token: str
    channel_ids: list[str] = field(default_factory=list)
    include_all_channels: bool = False
    oldest_days: int = 30
    page_size: int = 200

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "SlackSourceConfig":
        from ragrig.plugins.sources.slack.errors import SlackConfigError

        bot_token = str(raw.get("bot_token") or "").strip()
        if not bot_token:
            raise SlackConfigError("bot_token is required (use env:SLACK_BOT_TOKEN)")

        channel_ids = raw.get("channel_ids")
        if channel_ids is None:
            channel_ids = []
        elif not isinstance(channel_ids, list):
            channel_ids = list(channel_ids)  # type: ignore[arg-type]

        return cls(
            bot_token=bot_token,
            channel_ids=list(channel_ids),
            include_all_channels=bool(raw.get("include_all_channels") or False),
            oldest_days=int(raw.get("oldest_days") or 30),
            page_size=int(raw.get("page_size") or 200),
        )
