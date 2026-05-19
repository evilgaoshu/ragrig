from __future__ import annotations

import re

from pydantic import Field, field_validator

from ragrig.plugins.manifest import PluginConfigModel

_REGION_PATTERN = re.compile(r"^[a-z]{2}-[a-z]+-\d{3}$")


class BackblazeB2SourceConfig(PluginConfigModel):
    region: str = Field(min_length=1)
    key_id: str
    application_key: str
    bucket: str = Field(min_length=1)
    prefix: str = ""
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    max_object_size_mb: float = Field(default=50.0, gt=0)
    page_size: int = Field(default=1000, gt=0, le=1000)
    max_retries: int = Field(default=3, ge=0)

    @field_validator("region")
    @classmethod
    def validate_region(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("region must not be empty")
        if not _REGION_PATTERN.match(cleaned):
            raise ValueError("region must match pattern like 'us-west-004' or 'eu-central-003'")
        return cleaned

    @field_validator("bucket")
    @classmethod
    def validate_bucket(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("bucket must not be empty")
        if "/" in cleaned:
            raise ValueError("bucket must not contain '/' characters")
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
