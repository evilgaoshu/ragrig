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
from ragrig.plugins.sources.azure_blob.errors import AzureBlobAuthError, AzureBlobConfigError


def export_to_azure_blob(
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
    validated = registry.validate_config("sink.azure_blob", config)
    _env = env or os.environ

    account_name = str(validated["account_name"])
    account_key = _resolve_env_ref(str(validated["account_key"]), _env, "AZURE_STORAGE_ACCOUNT_KEY")

    # Build a synthetic S3-like validated dict so _export_with_resolved_credentials can
    # extract bucket, prefix, path_template, etc. from standard keys.
    enriched = dict(validated)
    enriched["bucket"] = str(validated["container"])
    enriched["access_key"] = account_key
    enriched["secret_key"] = account_key  # placeholder — not used by azure client
    enriched["session_token"] = None

    # Defer building the Azure client until after the dry_run early-exit check inside
    # _export_with_resolved_credentials.  If no client is provided and we are NOT in
    # dry_run mode the base helper will call build_boto3_object_storage_client which
    # would fail for Azure; we therefore supply a lazy wrapper that is only
    # materialised on first use.
    is_dry_run = bool(validated.get("dry_run", False))
    if client is None and not is_dry_run:
        client = _build_azure_object_storage_client(account_name, account_key)

    secrets = ResolvedObjectStorageSecrets(access_key=account_key, secret_key=account_key)
    return _export_with_resolved_credentials(
        session,
        knowledge_base_name=knowledge_base_name,
        workspace_id=workspace_id,
        validated=enriched,
        secrets=secrets,
        source_kind="azure_blob_sink",
        run_type="azure_blob_export",
        client=client,
    )


def _resolve_env_ref(value: str, env: Mapping[str, str], field_name: str) -> str:
    if value.startswith("env:"):
        env_name = value.removeprefix("env:")
        resolved = env.get(env_name)
        if resolved is None:
            raise AzureBlobAuthError(f"missing required environment variable: {env_name}")
        return resolved
    raise AzureBlobConfigError(f"sink.azure_blob {field_name} must use env: references")


def _build_azure_object_storage_client(
    account_name: str, account_key: str
) -> ObjectStorageClientProtocol:
    try:
        from azure.core.exceptions import AzureError, ClientAuthenticationError
        from azure.storage.blob import BlobServiceClient
    except ImportError as exc:  # pragma: no cover
        raise AzureBlobConfigError("azure-storage-blob is required for sink.azure_blob") from exc

    from datetime import datetime, timezone

    from ragrig.plugins.object_storage import (
        FakeStoredObject,
        ObjectStorageCredentialError,
        ObjectStoragePermanentError,
        ObjectStorageRetryableError,
    )

    class _AzureObjectStorageClientImpl:
        def __init__(self) -> None:
            connection_string = (
                f"DefaultEndpointsProtocol=https;"
                f"AccountName={account_name};"
                f"AccountKey={account_key};"
                f"EndpointSuffix=core.windows.net"
            )
            self._service_client = BlobServiceClient.from_connection_string(connection_string)

        def check_bucket_access(self, *, bucket: str, prefix: str) -> None:
            try:
                container_client = self._service_client.get_container_client(bucket)
                items = container_client.list_blobs(name_starts_with=prefix or None)
                next(iter(items), None)
            except ClientAuthenticationError as exc:
                raise ObjectStorageCredentialError(
                    "Azure Blob credentials were rejected for sink.azure_blob"
                ) from exc
            except AzureError as exc:
                raise ObjectStorageRetryableError(
                    f"Azure Blob container access check failed: {exc}"
                ) from exc

        def get_object(self, *, bucket: str, key: str) -> FakeStoredObject | None:
            try:
                container_client = self._service_client.get_container_client(bucket)
                blob_client = container_client.get_blob_client(key)
                props = blob_client.get_blob_properties()
                return FakeStoredObject(
                    key=key,
                    body=b"",
                    content_type=props.content_settings.content_type or "application/octet-stream",
                    metadata={str(k): str(v) for k, v in (props.metadata or {}).items()},
                    last_modified=props.last_modified or datetime.now(timezone.utc),
                )
            except ClientAuthenticationError as exc:
                raise ObjectStorageCredentialError(
                    "Azure Blob credentials were rejected for sink.azure_blob"
                ) from exc
            except AzureError:
                return None

        def put_object(
            self,
            *,
            bucket: str,
            key: str,
            body: bytes,
            content_type: str,
            metadata: dict[str, str],
        ) -> None:
            try:
                container_client = self._service_client.get_container_client(bucket)
                blob_client = container_client.get_blob_client(key)
                from azure.storage.blob import ContentSettings

                blob_client.upload_blob(
                    body,
                    overwrite=True,
                    content_settings=ContentSettings(content_type=content_type),
                    metadata=metadata,
                )
            except ClientAuthenticationError as exc:
                raise ObjectStorageCredentialError(
                    "Azure Blob credentials were rejected for sink.azure_blob"
                ) from exc
            except AzureError as exc:
                raise ObjectStoragePermanentError(
                    f"Azure Blob put_object failed for {key}: {exc}"
                ) from exc

    return _AzureObjectStorageClientImpl()
