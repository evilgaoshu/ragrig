from __future__ import annotations

from pydantic import Field, field_validator

from ragrig.plugins.object_storage.config import S3CompatibleStorageConfig


class S3SourceConfig(S3CompatibleStorageConfig):
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    max_object_size_mb: float = Field(default=50, gt=0)
    page_size: int = Field(default=1000, gt=0, le=1000)

    @field_validator("include_patterns", "exclude_patterns")
    @classmethod
    def validate_patterns(cls, value: list[str]) -> list[str]:
        cleaned = [pattern.strip() for pattern in value if pattern.strip()]
        if any(pattern.startswith("/") for pattern in cleaned):
            raise ValueError("glob patterns must be relative")
        return cleaned
