# Discord Source Connector

## Goal

Add an official `source.discord` connector that imports Discord channel
history into a RAGRig knowledge base without adding a default dependency on a
Discord SDK.

## Scope

- Use Discord REST API calls through `httpx`.
- Resolve `bot_token` from literal values or `env:DISCORD_BOT_TOKEN`.
- Fetch configured `channel_ids`.
- Optionally fetch active guild threads when `include_threads=true` and
  `guild_id` is supplied.
- Aggregate each channel or thread into a plain-text document.
- Include timestamp, author ID, author name, channel ID, message ID, channel
  name, and message content in the text document.
- Hand generated files to `ingest_local_directory` so parser/chunker/indexer
  behavior stays shared with local files.

## Configuration

```json
{
  "bot_token": "env:DISCORD_BOT_TOKEN",
  "guild_id": "123456789012345678",
  "channel_ids": ["234567890123456789"],
  "include_threads": true,
  "oldest_days": 30,
  "page_size": 100,
  "max_messages_per_channel": 500
}
```

`page_size` is capped at Discord's REST limit of 100. `max_messages_per_channel`
is optional and bounds ingestion cost for busy channels.

## Failure Contract

- Missing `env:` values raise `DiscordAuthError`.
- HTTP 401/403 raise `DiscordAuthError`.
- HTTP 429 raises `DiscordRateLimitError` with retry metadata when available.
- Other non-2xx responses raise `DiscordConfigError`.
- Tests use fake transports only; no real Discord credentials are required in
  CI.

## Verification

```bash
uv run pytest tests/test_discord_source.py -q
```

The focused suite covers config validation, env resolution, pagination, auth
and rate-limit error mapping, official plugin registry exposure, and the ingest
handoff report path.
