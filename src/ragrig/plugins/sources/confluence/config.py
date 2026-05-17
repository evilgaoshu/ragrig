"""Confluence connector configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConfluenceSourceConfig:
    base_url: str
    space_key: str | None = None
    email: str = ""
    api_token: str = ""
    page_size: int = 50

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "ConfluenceSourceConfig":
        base_url = str(raw.get("base_url") or "").rstrip("/")
        if not base_url:
            from ragrig.plugins.sources.confluence.errors import ConfluenceConfigError

            raise ConfluenceConfigError("base_url is required")
        return cls(
            base_url=base_url,
            space_key=str(raw["space_key"]) if raw.get("space_key") else None,
            email=str(raw.get("email") or ""),
            api_token=str(raw.get("api_token") or ""),
            page_size=int(raw.get("page_size") or 50),
        )
