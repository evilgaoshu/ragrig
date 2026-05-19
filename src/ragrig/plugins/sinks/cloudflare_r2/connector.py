from __future__ import annotations

import os
from typing import Mapping

from sqlalchemy.orm import Session

from ragrig.plugins.object_storage import ObjectStorageClientProtocol
from ragrig.plugins.sinks.object_storage.connector import (
    ExportToObjectStorageReport,
    ResolvedObjectStorageSecrets,
    _export_with_resolved_credentials,
)
from ragrig.plugins.sources.cloudflare_r2.connector import _build_r2_endpoint
from ragrig.plugins.sources.cloudflare_r2.errors import (
    CloudflareR2AuthError,
    CloudflareR2ConfigError,
)


def export_to_cloudflare_r2(
    session: Session,
    *,
    knowledge_base_name: str,
    config: dict[str, object],
    env: Mapping[str, str] | None = None,
    client: ObjectStorageClientProtocol | None = None,
) -> ExportToObjectStorageReport:
    from ragrig.plugins import get_plugin_registry

    registry = get_plugin_registry()
    validated = registry.validate_config("sink.cloudflare_r2", config)
    _env = env or os.environ

    access_key = _resolve_env_ref(str(validated["access_key_id"]), _env, "CF_R2_ACCESS_KEY_ID")
    secret_key = _resolve_env_ref(
        str(validated["secret_access_key"]), _env, "CF_R2_SECRET_ACCESS_KEY"
    )

    account_id = str(validated["account_id"])
    jurisdiction = validated.get("jurisdiction")
    endpoint_url = _build_r2_endpoint(account_id, jurisdiction)

    enriched = dict(validated)
    enriched["access_key"] = access_key
    enriched["secret_key"] = secret_key
    enriched["endpoint_url"] = endpoint_url
    enriched["region"] = "auto"
    enriched["use_path_style"] = False
    enriched["verify_tls"] = True

    secrets = ResolvedObjectStorageSecrets(access_key=access_key, secret_key=secret_key)
    return _export_with_resolved_credentials(
        session,
        knowledge_base_name=knowledge_base_name,
        validated=enriched,
        secrets=secrets,
        source_kind="cloudflare_r2_sink",
        run_type="r2_export",
        client=client,
    )


def _resolve_env_ref(value: str, env: Mapping[str, str], field_name: str) -> str:
    if value.startswith("env:"):
        env_name = value.removeprefix("env:")
        resolved = env.get(env_name)
        if resolved is None:
            raise CloudflareR2AuthError(f"missing required environment variable: {env_name}")
        return resolved
    raise CloudflareR2ConfigError(f"sink.cloudflare_r2 {field_name} must use env: references")
