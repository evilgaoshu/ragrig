"""Microsoft 365 connector configuration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Microsoft365SourceConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    site_url: str | None = None
    scope: str = "sharepoint"  # "sharepoint" | "onedrive" | "both"
    page_size: int = 100

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "Microsoft365SourceConfig":
        from ragrig.plugins.sources.microsoft_365.errors import Microsoft365ConfigError

        tenant_id = str(raw.get("tenant_id") or "").strip()
        if not tenant_id:
            raise Microsoft365ConfigError("tenant_id is required")
        client_id = str(raw.get("client_id") or "").strip()
        if not client_id:
            raise Microsoft365ConfigError("client_id is required")
        client_secret = str(raw.get("client_secret") or "").strip()
        if not client_secret:
            raise Microsoft365ConfigError("client_secret is required")
        scope = str(raw.get("scope") or "sharepoint")
        if scope not in ("sharepoint", "onedrive", "both"):
            raise Microsoft365ConfigError(
                f"scope must be 'sharepoint', 'onedrive', or 'both'; got {scope!r}"
            )
        return cls(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
            site_url=str(raw["site_url"]).rstrip("/") if raw.get("site_url") else None,
            scope=scope,
            page_size=int(raw.get("page_size") or 100),
        )
