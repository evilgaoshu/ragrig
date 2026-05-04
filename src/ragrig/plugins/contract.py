from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from ragrig.plugins.registry import PluginRegistry


def assert_registry_contracts(registry: PluginRegistry, *, repo_root: Path) -> None:
    manifests = registry.list()
    assert manifests, "expected at least one plugin manifest"
    assert len({manifest.plugin_id for manifest in manifests}) == len(manifests)

    for manifest in manifests:
        assert manifest.manifest_version == 1
        assert manifest.capabilities
        assert _is_valid_docs_reference(manifest.docs_reference, repo_root=repo_root)
        registry.validate_config(manifest.plugin_id, manifest.example_config or {})


def _is_valid_docs_reference(reference: str, *, repo_root: Path) -> bool:
    parsed = urlparse(reference)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return True
    return (repo_root / reference).exists()
