"""Discord source connector configuration."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DiscordSourceConfig:
    bot_token: str
    channel_ids: list[str] = field(default_factory=list)
    guild_id: str | None = None
    include_threads: bool = False
    oldest_days: int = 30
    page_size: int = 100
    max_messages_per_channel: int | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "DiscordSourceConfig":
        from ragrig.plugins.sources.discord.errors import DiscordConfigError

        bot_token = str(raw.get("bot_token") or "").strip()
        if not bot_token:
            raise DiscordConfigError("bot_token is required (use env:DISCORD_BOT_TOKEN)")

        channel_ids_raw = raw.get("channel_ids")
        if channel_ids_raw is None:
            channel_ids: list[str] = []
        elif isinstance(channel_ids_raw, list):
            channel_ids = [str(item) for item in channel_ids_raw]
        else:
            channel_ids = [str(item) for item in channel_ids_raw]  # type: ignore[arg-type]
        if not channel_ids:
            raise DiscordConfigError("channel_ids must contain at least one channel ID")

        max_messages_raw = raw.get("max_messages_per_channel")
        max_messages = int(max_messages_raw) if max_messages_raw not in (None, "") else None

        page_size = int(raw.get("page_size") or 100)
        if page_size < 1 or page_size > 100:
            raise DiscordConfigError("page_size must be between 1 and 100 for Discord API")

        oldest_days = int(raw.get("oldest_days") or 30)
        if oldest_days < 0:
            raise DiscordConfigError("oldest_days must be non-negative")

        return cls(
            bot_token=bot_token,
            channel_ids=channel_ids,
            guild_id=str(raw["guild_id"]).strip() if raw.get("guild_id") else None,
            include_threads=bool(raw.get("include_threads") or False),
            oldest_days=oldest_days,
            page_size=page_size,
            max_messages_per_channel=max_messages,
        )
