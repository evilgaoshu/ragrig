from __future__ import annotations

import os
from typing import Mapping
from uuid import UUID

from sqlalchemy.orm import Session

from ragrig.plugins.object_storage import ObjectStorageClientProtocol
from ragrig.plugins.sinks.object_storage.connector import (
    ExportToObjectStorageReport,
    ResolvedObjectStorageSecrets,
    _export_with_resolved_credentials,
)
from ragrig.plugins.sources.backblaze_b2.errors import BackblazeB2AuthError, BackblazeB2ConfigError


def export_to_backblaze_b2(
    session: Session,
    *,
    knowledge_base_name: str,
    config: dict[str, object],
    workspace_id: UUID | None = None,
    env: Mapping[str, str] | None = None,
    client: ObjectStorageClientProtocol | None = None,
) -> ExportToObjectStorageReport:
    from ragrig.plugins import get_plugin_registry

    registry = get_plugin_registry()
    validated = registry.validate_config("sink.backblaze_b2", config)
    _env = env or os.environ

    key_id = _resolve_env_ref(str(validated["key_id"]), _env, "B2_APPLICATION_KEY_ID")
    application_key = _resolve_env_ref(
        str(validated["application_key"]), _env, "B2_APPLICATION_KEY"
    )

    region = str(validated["region"])
    endpoint_url = f"https://s3.{region}.backblazeb2.com"

    enriched = dict(validated)
    enriched["access_key"] = key_id
    enriched["secret_key"] = application_key
    enriched["endpoint_url"] = endpoint_url
    enriched["use_path_style"] = False
    enriched["verify_tls"] = True

    secrets = ResolvedObjectStorageSecrets(access_key=key_id, secret_key=application_key)
    return _export_with_resolved_credentials(
        session,
        knowledge_base_name=knowledge_base_name,
        workspace_id=workspace_id,
        validated=enriched,
        secrets=secrets,
        source_kind="backblaze_b2_sink",
        run_type="b2_export",
        client=client,
    )


def _resolve_env_ref(value: str, env: Mapping[str, str], field_name: str) -> str:
    if value.startswith("env:"):
        env_name = value.removeprefix("env:")
        resolved = env.get(env_name)
        if resolved is None:
            raise BackblazeB2AuthError(f"missing required environment variable: {env_name}")
        return resolved
    raise BackblazeB2ConfigError(f"sink.backblaze_b2 {field_name} must use env: references")
