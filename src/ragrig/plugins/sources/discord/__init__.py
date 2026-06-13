"""Discord source connector."""

from __future__ import annotations

from ragrig.plugins.sources.discord.config import DiscordSourceConfig
from ragrig.plugins.sources.discord.connector import ingest_discord_source
from ragrig.plugins.sources.discord.errors import (
    DiscordAuthError,
    DiscordConfigError,
    DiscordRateLimitError,
    DiscordSourceError,
)

__all__ = [
    "DiscordAuthError",
    "DiscordConfigError",
    "DiscordRateLimitError",
    "DiscordSourceConfig",
    "DiscordSourceError",
    "ingest_discord_source",
]
