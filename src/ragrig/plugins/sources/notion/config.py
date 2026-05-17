"""Notion connector configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NotionSourceConfig:
    api_token: str
    page_size: int = 50
    filter_kind: str | None = None  # "page" | "database" | None
    notion_version: str = "2022-06-28"

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "NotionSourceConfig":
        token = str(raw.get("api_token") or "")
        if not token:
            from ragrig.plugins.sources.notion.errors import NotionConfigError

            raise NotionConfigError("api_token is required")
        filter_kind = raw.get("filter") or raw.get("filter_kind")
        if filter_kind and filter_kind not in ("page", "database"):
            from ragrig.plugins.sources.notion.errors import NotionConfigError

            raise NotionConfigError("filter must be 'page' or 'database'")
        return cls(
            api_token=token,
            page_size=int(raw.get("page_size") or 50),
            filter_kind=str(filter_kind) if filter_kind else None,
            notion_version=str(raw.get("notion_version") or "2022-06-28"),
        )
