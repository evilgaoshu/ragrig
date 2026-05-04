from __future__ import annotations

from ragrig.plugins.builtins import builtin_manifests
from ragrig.plugins.manifest import PluginConfigModel, PluginManifest, SecretRequirement
from ragrig.plugins.official import official_stub_manifests
from ragrig.plugins.registry import PluginConfigValidationError, PluginRegistry
from ragrig.plugins.types import Capability, PluginStatus, PluginTier, PluginType

_REGISTRY: PluginRegistry | None = None


def build_plugin_registry() -> PluginRegistry:
    return PluginRegistry([*builtin_manifests(), *official_stub_manifests()])


def get_plugin_registry() -> PluginRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_plugin_registry()
    return _REGISTRY


__all__ = [
    "Capability",
    "PluginConfigModel",
    "PluginConfigValidationError",
    "PluginManifest",
    "PluginRegistry",
    "PluginStatus",
    "PluginTier",
    "PluginType",
    "SecretRequirement",
    "build_plugin_registry",
    "get_plugin_registry",
]
