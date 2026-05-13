from __future__ import annotations

from pydantic import Field, field_validator

from ragrig.plugins.manifest import PluginConfigModel


class GoogleWorkspaceSourceConfig(PluginConfigModel):
    drive_id: str | None = Field(default=None)
    include_shared_drives: bool = Field(default=False)
    include_patterns: list[str] = Field(default_factory=lambda: ["*.pdf", "*.txt", "*.docx"])
    exclude_patterns: list[str] = Field(default_factory=list)
    page_size: int = Field(default=100, gt=0, le=1000)
    max_retries: int = Field(default=3, ge=0)
    service_account_json: str

    @field_validator("include_patterns", "exclude_patterns")
    @classmethod
    def validate_patterns(cls, value: list[str]) -> list[str]:
        cleaned = [pattern.strip() for pattern in value if pattern.strip()]
        return cleaned

    @field_validator("service_account_json")
    @classmethod
    def validate_service_account_json(cls, value: str) -> str:
        if not isinstance(value, str):
            raise ValueError("service_account_json must be a string")
        if not value.startswith("env:"):
            raise ValueError("service_account_json must use env: reference")
        return value
