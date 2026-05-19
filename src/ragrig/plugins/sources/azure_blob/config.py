from __future__ import annotations

from pydantic import Field, field_validator

from ragrig.plugins.manifest import PluginConfigModel


class AzureBlobSourceConfig(PluginConfigModel):
    account_name: str = Field(min_length=1)
    account_key: str
    container: str = Field(min_length=1)
    prefix: str = ""
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    max_object_size_mb: float = Field(default=50.0, gt=0)
    page_size: int = Field(default=1000, gt=0, le=1000)

    @field_validator("account_name")
    @classmethod
    def validate_account_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("account_name must not be empty")
        return cleaned

    @field_validator("container")
    @classmethod
    def validate_container(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("container must not be empty")
        if "/" in cleaned:
            raise ValueError("container must not contain '/' characters")
        return cleaned

    @field_validator("prefix")
    @classmethod
    def normalize_prefix(cls, value: str) -> str:
        return value.strip().strip("/")

    @field_validator("include_patterns", "exclude_patterns")
    @classmethod
    def validate_patterns(cls, value: list[str]) -> list[str]:
        cleaned = [pattern.strip() for pattern in value if pattern.strip()]
        if any(pattern.startswith("/") for pattern in cleaned):
            raise ValueError("glob patterns must be relative")
        return cleaned
