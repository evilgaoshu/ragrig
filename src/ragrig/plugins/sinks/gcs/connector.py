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
from ragrig.plugins.sources.gcs.errors import GcsAuthError, GcsConfigError

_GCS_ENDPOINT_URL = "https://storage.googleapis.com"
_GCS_REGION = "auto"


def export_to_gcs(
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
    validated = registry.validate_config("sink.gcs", config)
    _env = env or os.environ

    access_key = _resolve_env_ref(str(validated["access_key"]), _env, "GCS_ACCESS_KEY")
    secret_key = _resolve_env_ref(str(validated["secret_key"]), _env, "GCS_SECRET_KEY")

    enriched = dict(validated)
    enriched["access_key"] = access_key
    enriched["secret_key"] = secret_key
    enriched["endpoint_url"] = _GCS_ENDPOINT_URL
    enriched["region"] = _GCS_REGION
    enriched["use_path_style"] = False
    enriched["verify_tls"] = True

    secrets = ResolvedObjectStorageSecrets(access_key=access_key, secret_key=secret_key)
    return _export_with_resolved_credentials(
        session,
        knowledge_base_name=knowledge_base_name,
        workspace_id=workspace_id,
        validated=enriched,
        secrets=secrets,
        source_kind="gcs_sink",
        run_type="gcs_export",
        client=client,
    )


def _resolve_env_ref(value: str, env: Mapping[str, str], field_name: str) -> str:
    if value.startswith("env:"):
        env_name = value.removeprefix("env:")
        resolved = env.get(env_name)
        if resolved is None:
            raise GcsAuthError(f"missing required environment variable: {env_name}")
        return resolved
    raise GcsConfigError(f"sink.gcs {field_name} must use env: references")
