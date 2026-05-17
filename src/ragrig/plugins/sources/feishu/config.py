"""Feishu / Lark connector configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeishuSourceConfig:
    space_id: str
    app_id: str
    app_secret: str
    base_url: str = "https://open.feishu.cn"
    page_size: int = 50

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "FeishuSourceConfig":
        from ragrig.plugins.sources.feishu.errors import FeishuConfigError

        space_id = str(raw.get("space_id") or "")
        if not space_id:
            raise FeishuConfigError("space_id is required")
        app_id = str(raw.get("app_id") or "")
        app_secret = str(raw.get("app_secret") or "")
        if not app_id or not app_secret:
            raise FeishuConfigError("app_id and app_secret are required (use env:NAME)")
        return cls(
            space_id=space_id,
            app_id=app_id,
            app_secret=app_secret,
            base_url=str(raw.get("base_url") or "https://open.feishu.cn").rstrip("/"),
            page_size=int(raw.get("page_size") or 50),
        )
