from __future__ import annotations

import os
from typing import TYPE_CHECKING, Mapping

from sqlalchemy.orm import Session

from ragrig.plugins.sources.cloudflare_r2.errors import (
    CloudflareR2AuthError,
    CloudflareR2ConfigError,
)

if TYPE_CHECKING:
    from ragrig.ingestion.pipeline import IngestionReport


def ingest_cloudflare_r2_source(
    session: Session,
    *,
    knowledge_base_name: str,
    config: dict[str, object],
    env: Mapping[str, str] | None = None,
    client=None,
) -> IngestionReport:
    from ragrig.plugins import get_plugin_registry
    from ragrig.plugins.sources.s3.client import build_boto3_client
    from ragrig.plugins.sources.s3.connector import _run_s3_compatible_ingest

    registry = get_plugin_registry()
    validated = registry.validate_config("source.cloudflare_r2", config)
    _env = env or os.environ

    access_key = _resolve_env_ref(str(validated["access_key_id"]), _env, "CF_R2_ACCESS_KEY_ID")
    secret_key = _resolve_env_ref(
        str(validated["secret_access_key"]), _env, "CF_R2_SECRET_ACCESS_KEY"
    )

    account_id = str(validated["account_id"])
    jurisdiction = validated.get("jurisdiction")
    endpoint_url = _build_r2_endpoint(account_id, jurisdiction)

    s3_client_config: dict[str, object] = {
        "access_key": access_key,
        "secret_key": secret_key,
        "endpoint_url": endpoint_url,
        "region": "auto",
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
        source_kind="cloudflare_r2",
        run_type="r2_ingest",
        bucket=str(validated["bucket"]),
        prefix=str(validated.get("prefix") or ""),
        scan_config=scan_config,
        client=active_client,
        secret_values=[access_key, secret_key],
    )


def _build_r2_endpoint(account_id: str, jurisdiction: object) -> str:
    if jurisdiction == "eu":
        return f"https://{account_id}.eu.r2.cloudflarestorage.com"
    if jurisdiction == "fedramp":
        return f"https://{account_id}.fedramp.r2.cloudflarestorage.com"
    return f"https://{account_id}.r2.cloudflarestorage.com"


def _resolve_env_ref(value: str, env: Mapping[str, str], field_name: str) -> str:
    if value.startswith("env:"):
        env_name = value.removeprefix("env:")
        resolved = env.get(env_name)
        if resolved is None:
            raise CloudflareR2AuthError(f"missing required environment variable: {env_name}")
        return resolved
    raise CloudflareR2ConfigError(f"source.cloudflare_r2 {field_name} must use env: references")
