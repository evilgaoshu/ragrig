from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ragrig.plugins import guards
from ragrig.plugins.manifest import PluginManifest
from ragrig.plugins.types import PluginStatus


class PluginConfigValidationError(ValueError):
    pass


class PluginRegistry:
    def __init__(self, manifests: list[PluginManifest] | None = None) -> None:
        self._manifests: dict[str, PluginManifest] = {}
        for manifest in manifests or []:
            self.register(manifest)

    def register(self, manifest: PluginManifest) -> None:
        if manifest.plugin_id in self._manifests:
            raise ValueError(f"plugin '{manifest.plugin_id}' is already registered")
        self._manifests[manifest.plugin_id] = manifest

    def get(self, plugin_id: str) -> PluginManifest:
        return self._manifests[plugin_id]

    def list(self) -> list[PluginManifest]:
        return [self._manifests[plugin_id] for plugin_id in sorted(self._manifests)]

    def validate_config(self, plugin_id: str, config: dict[str, Any] | None) -> dict[str, Any]:
        manifest = self.get(plugin_id)
        payload = config or {}
        if manifest.config_model is None:
            if payload:
                raise PluginConfigValidationError(f"plugin '{plugin_id}' is not configurable")
            return {}
        try:
            validated = manifest.config_model.model_validate(payload).model_dump()
        except ValidationError as exc:
            raise PluginConfigValidationError(str(exc)) from exc
        self._validate_secret_references(manifest, validated)
        return validated

    def list_discovery(self) -> list[dict[str, Any]]:
        return [self._build_discovery_item(manifest) for manifest in self.list()]

    def _build_discovery_item(self, manifest: PluginManifest) -> dict[str, Any]:
        missing_dependencies = guards.list_missing_dependencies(manifest.optional_dependencies)
        status = manifest.status
        reason = manifest.unavailable_reason
        if missing_dependencies:
            degraded_missing = set(manifest.degraded_missing_dependencies)
            if degraded_missing and set(missing_dependencies).issubset(degraded_missing):
                status = PluginStatus.DEGRADED
            else:
                status = PluginStatus.UNAVAILABLE
            reason = f"Missing optional dependencies: {', '.join(missing_dependencies)}"
        item = {
            "plugin_id": manifest.plugin_id,
            "manifest_version": manifest.manifest_version,
            "display_name": manifest.display_name,
            "description": manifest.description,
            "plugin_type": manifest.plugin_type,
            "family": manifest.family,
            "version": manifest.version,
            "owner": manifest.owner,
            "tier": manifest.tier,
            "status": status,
            "reason": reason,
            "capabilities": list(manifest.capabilities),
            "configurable": manifest.config_model is not None,
            "example_config": manifest.example_config or {},
            "missing_dependencies": missing_dependencies,
            "secret_requirements": [secret.name for secret in manifest.secret_requirements],
            "docs_reference": manifest.docs_reference,
        }
        if manifest.plugin_id == "source.fileshare":
            protocol_dependencies = {
                "nfs_mounted": (),
                "sftp": ("paramiko",),
                "smb": ("smbprotocol",),
                "webdav": ("httpx",),
            }
            missing_dependencies = sorted(
                {
                    dependency
                    for dependencies in protocol_dependencies.values()
                    for dependency in guards.list_missing_dependencies(dependencies)
                }
            )
            protocol_statuses = {
                protocol: (
                    PluginStatus.READY
                    if not guards.list_missing_dependencies(dependencies)
                    else PluginStatus.UNAVAILABLE
                )
                for protocol, dependencies in protocol_dependencies.items()
            }
            protocol_example_configs = {
                "nfs_mounted": {
                    "protocol": "nfs_mounted",
                    "root_path": "/mnt/share/docs",
                },
                "smb": {
                    "protocol": "smb",
                    "host": "files.example.internal",
                    "share": "knowledge",
                    "root_path": "/docs",
                    "username": "env:FILESHARE_USERNAME",
                    "password": "env:FILESHARE_PASSWORD",
                },
                "webdav": {
                    "protocol": "webdav",
                    "base_url": "https://webdav.example.com",
                    "root_path": "/docs",
                    "username": "env:FILESHARE_USERNAME",
                    "password": "env:FILESHARE_PASSWORD",
                },
                "sftp": {
                    "protocol": "sftp",
                    "host": "sftp.example.com",
                    "root_path": "/docs",
                    "username": "env:FILESHARE_USERNAME",
                    "password": "env:FILESHARE_PASSWORD",
                    "private_key": "env:FILESHARE_PRIVATE_KEY",
                },
            }
            protocol_secret_requirements = {
                "nfs_mounted": [],
                "smb": ["FILESHARE_USERNAME", "FILESHARE_PASSWORD"],
                "webdav": ["FILESHARE_USERNAME", "FILESHARE_PASSWORD"],
                "sftp": [
                    "FILESHARE_USERNAME",
                    "FILESHARE_PASSWORD",
                    "FILESHARE_PRIVATE_KEY",
                ],
            }
            protocol_missing_dependencies = {
                protocol: sorted(guards.list_missing_dependencies(dependencies))
                for protocol, dependencies in protocol_dependencies.items()
            }
            item["missing_dependencies"] = missing_dependencies
            item["supported_protocols"] = sorted(protocol_dependencies)
            item["protocol_statuses"] = protocol_statuses
            item["protocol_example_configs"] = protocol_example_configs
            item["protocol_secret_requirements"] = protocol_secret_requirements
            item["protocol_missing_dependencies"] = protocol_missing_dependencies
        return item

    def _validate_secret_references(self, manifest: PluginManifest, value: Any) -> None:
        declared = {secret.name for secret in manifest.secret_requirements}
        found = sorted(set(self._collect_secret_references(value)))
        undeclared = [name for name in found if name not in declared]
        if undeclared:
            raise PluginConfigValidationError(
                f"undeclared secret reference(s): {', '.join(undeclared)}"
            )

    def _collect_secret_references(self, value: Any) -> list[str]:
        if isinstance(value, dict):
            references: list[str] = []
            for nested in value.values():
                references.extend(self._collect_secret_references(nested))
            return references
        if isinstance(value, list):
            references: list[str] = []
            for nested in value:
                references.extend(self._collect_secret_references(nested))
            return references
        if isinstance(value, str) and value.startswith("env:"):
            return [value.removeprefix("env:")]
        return []
