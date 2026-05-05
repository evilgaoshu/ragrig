from __future__ import annotations

from pydantic import Field, field_validator, model_validator

from ragrig.plugins.manifest import PluginConfigModel

SUPPORTED_FILESHARE_PROTOCOLS = ("nfs_mounted", "sftp", "smb", "webdav")


class FileshareSourceConfig(PluginConfigModel):
    protocol: str = Field(pattern=r"^(smb|nfs_mounted|webdav|sftp)$")
    host: str | None = None
    port: int | None = Field(default=None, gt=0, le=65535)
    share: str | None = None
    base_url: str | None = None
    root_path: str
    username: str | None = None
    password: str | None = None
    private_key: str | None = None
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    max_file_size_mb: float = Field(default=50, gt=0)
    page_size: int = Field(default=1000, gt=0, le=1000)
    max_retries: int = Field(default=3, ge=0)
    connect_timeout_seconds: int = Field(default=10, gt=0)
    read_timeout_seconds: int = Field(default=30, gt=0)
    cursor: str | None = None
    known_document_uris: list[str] = Field(default_factory=list)

    @field_validator("root_path")
    @classmethod
    def validate_root_path(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("root_path must not be empty")
        return cleaned

    @field_validator("include_patterns", "exclude_patterns")
    @classmethod
    def validate_patterns(cls, value: list[str]) -> list[str]:
        cleaned = [pattern.strip() for pattern in value if pattern.strip()]
        if any(pattern.startswith("/") for pattern in cleaned):
            raise ValueError("glob patterns must be relative")
        return cleaned

    @model_validator(mode="after")
    def validate_protocol_requirements(self) -> "FileshareSourceConfig":
        if self.protocol == "nfs_mounted":
            return self
        if self.protocol == "webdav":
            if not self.base_url:
                raise ValueError("base_url is required for webdav")
            return self
        if not self.host:
            raise ValueError("host is required for remote fileshare protocols")
        if self.protocol == "smb" and not self.share:
            raise ValueError("share is required for smb")
        return self
