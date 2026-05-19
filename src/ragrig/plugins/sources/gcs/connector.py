from __future__ import annotations

import os
from typing import TYPE_CHECKING, Mapping
from uuid import UUID

from sqlalchemy.orm import Session

from ragrig.plugins.sources.gcs.errors import GcsAuthError, GcsConfigError

if TYPE_CHECKING:
    from ragrig.ingestion.pipeline import IngestionReport


_GCS_ENDPOINT_URL = "https://storage.googleapis.com"
_GCS_REGION = "auto"


def ingest_gcs_source(
    session: Session,
    *,
    knowledge_base_name: str,
    config: dict[str, object],
    workspace_id: UUID | None = None,
    env: Mapping[str, str] | None = None,
    client=None,
) -> IngestionReport:
    from ragrig.plugins import get_plugin_registry
    from ragrig.plugins.sources.s3.client import build_boto3_client
    from ragrig.plugins.sources.s3.connector import _run_s3_compatible_ingest

    registry = get_plugin_registry()
    validated = registry.validate_config("source.gcs", config)
    _env = env or os.environ

    access_key = _resolve_env_ref(str(validated["access_key"]), _env, "GCS_ACCESS_KEY")
    secret_key = _resolve_env_ref(str(validated["secret_key"]), _env, "GCS_SECRET_KEY")

    s3_client_config: dict[str, object] = {
        "access_key": access_key,
        "secret_key": secret_key,
        "endpoint_url": _GCS_ENDPOINT_URL,
        "region": _GCS_REGION,
        "use_path_style": False,
        "verify_tls": True,
        "max_retries": int(validated.get("max_retries", 3)),
    }
    active_client = client or build_boto3_client(s3_client_config)

    scan_config: dict[str, object] = {
        "bucket": str(validated["bucket"]),
        "prefix": str(validated.get("prefix") or ""),
        "include_patterns": validated.get("include_patterns") or [],
        "exclude_patterns": validated.get("exclude_patterns") or [],
        "max_object_size_mb": float(validated.get("max_object_size_mb", 50.0)),
        "page_size": int(validated.get("page_size", 1000)),
        "max_retries": int(validated.get("max_retries", 3)),
    }

    return _run_s3_compatible_ingest(
        session,
        knowledge_base_name=knowledge_base_name,
        workspace_id=workspace_id,
        source_kind="gcs",
        run_type="gcs_ingest",
        bucket=str(validated["bucket"]),
        prefix=str(validated.get("prefix") or ""),
        scan_config=scan_config,
        client=active_client,
        secret_values=[access_key, secret_key],
    )


def _resolve_env_ref(value: str, env: Mapping[str, str], field_name: str) -> str:
    if value.startswith("env:"):
        env_name = value.removeprefix("env:")
        resolved = env.get(env_name)
        if resolved is None:
            raise GcsAuthError(f"missing required environment variable: {env_name}")
        return resolved
    raise GcsConfigError(f"source.gcs {field_name} must use env: references")
