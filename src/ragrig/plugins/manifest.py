from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from ragrig.plugins.types import (
    ALLOWED_CAPABILITIES,
    Capability,
    PluginStatus,
    PluginTier,
    PluginType,
)

PLUGIN_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")


class PluginConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SecretRequirement(BaseModel):
    name: str
    description: str
    required: bool = True


class PluginManifest(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    manifest_version: int = 1
    plugin_id: str
    display_name: str
    description: str
    plugin_type: PluginType
    family: str
    version: str
    owner: str
    tier: PluginTier
    status: PluginStatus
    capabilities: tuple[Capability, ...] = ()
    docs_reference: str
    config_model: type[PluginConfigModel] | None = None
    example_config: dict[str, Any] | None = None
    secret_requirements: tuple[SecretRequirement, ...] = ()
    optional_dependencies: tuple[str, ...] = ()
    unavailable_reason: str | None = None

    @field_validator("plugin_id")
    @classmethod
    def validate_plugin_id(cls, value: str) -> str:
        if not PLUGIN_ID_PATTERN.match(value):
            raise ValueError("plugin_id must use documented short ids such as 'source.local'")
        return value

    @field_validator("manifest_version")
    @classmethod
    def validate_manifest_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("manifest_version must be 1")
        return value

    @model_validator(mode="after")
    def validate_capabilities(self) -> "PluginManifest":
        allowed = ALLOWED_CAPABILITIES[self.plugin_type]
        invalid = sorted(
            capability for capability in self.capabilities if capability not in allowed
        )
        if invalid:
            raise ValueError(
                f"capabilities {invalid} are not valid for plugin type '{self.plugin_type}'"
            )
        if self.config_model is None and self.example_config not in (None, {}):
            raise ValueError("example_config requires a config_model")
        return self
