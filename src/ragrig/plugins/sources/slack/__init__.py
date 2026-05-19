"""Slack source connector.

Ingests messages from Slack channels via the Slack Web API.

Configuration shape::

    {
        "bot_token": "env:SLACK_BOT_TOKEN",
        "channel_ids": ["C01234567", "C09876543"],
        "include_all_channels": false,
        "oldest_days": 30,
        "page_size": 200,
    }
"""

from ragrig.plugins.sources.slack.config import SlackSourceConfig
from ragrig.plugins.sources.slack.connector import ingest_slack_source
from ragrig.plugins.sources.slack.errors import (
    SlackAuthError,
    SlackConfigError,
    SlackSourceError,
)

__all__ = [
    "SlackAuthError",
    "SlackConfigError",
    "SlackSourceConfig",
    "SlackSourceError",
    "ingest_slack_source",
]
