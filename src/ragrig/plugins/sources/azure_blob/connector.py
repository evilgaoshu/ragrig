from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Mapping, Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from ragrig.db.models import DocumentVersion
from ragrig.ingestion.pipeline import IngestionReport, _parser_plugin_id, _select_parser
from ragrig.ingestion.scanner import DEFAULT_INCLUDE_PATTERNS
from ragrig.plugins import get_plugin_registry
from ragrig.plugins.sources.azure_blob.errors import AzureBlobAuthError, AzureBlobConfigError
from ragrig.repositories import (
    create_pipeline_run,
    create_pipeline_run_item,
    get_document_by_uri,
    get_next_version_number,
    get_or_create_document,
    get_or_create_knowledge_base,
    get_or_create_source,
)


@dataclass(frozen=True)
class AzureBlobMetadata:
    key: str
    etag: str
    last_modified: datetime
    size: int
    content_type: str | None


class AzureBlobClientProtocol(Protocol):
    def list_blobs(
        self,
        *,
        container: str,
        prefix: str,
        max_results: int,
    ) -> list[AzureBlobMetadata]: ...

    def download_blob(self, *, container: str, key: str) -> bytes: ...


@dataclass
class FakeAzureBlobClient:
    blobs: list[tuple[str, bytes, str, datetime, str | None]] = field(default_factory=list)
    # Each entry: (key, body, etag, last_modified, content_type)
    list_error: Exception | None = None
    download_failures: dict[str, list[Exception]] = field(default_factory=dict)

    def list_blobs(
        self,
        *,
        container: str,
        prefix: str,
        max_results: int,
    ) -> list[AzureBlobMetadata]:
        del container
        if self.list_error is not None:
            raise self.list_error
        results = []
        for key, body, etag, last_modified, content_type in self.blobs:
            if key.startswith(prefix) or not prefix:
                results.append(
                    AzureBlobMetadata(
                        key=key,
                        etag=etag,
                        last_modified=last_modified,
                        size=len(body),
                        content_type=content_type,
                    )
                )
        return results

    def download_blob(self, *, container: str, key: str) -> bytes:
        del container
        failures = self.download_failures.get(key, [])
        if failures:
            error = failures.pop(0)
            raise error
        for blob_key, body, _etag, _last_modified, _content_type in self.blobs:
            if blob_key == key:
                return body
        raise AzureBlobConfigError(f"blob not found: {key}")


def _build_azure_client(account_name: str, account_key: str) -> AzureBlobClientProtocol:
    try:
        from azure.core.exceptions import (
            AzureError,
            ClientAuthenticationError,
            ResourceNotFoundError,
        )
        from azure.storage.blob import BlobServiceClient
    except ImportError as exc:  # pragma: no cover
        raise AzureBlobConfigError("azure-storage-blob is required for source.azure_blob") from exc

    class _AzureBlobClientImpl:
        def __init__(self) -> None:
            connection_string = (
                f"DefaultEndpointsProtocol=https;"
                f"AccountName={account_name};"
                f"AccountKey={account_key};"
                f"EndpointSuffix=core.windows.net"
            )
            self._service_client = BlobServiceClient.from_connection_string(connection_string)

        def list_blobs(
            self,
            *,
            container: str,
            prefix: str,
            max_results: int,
        ) -> list[AzureBlobMetadata]:
            try:
                container_client = self._service_client.get_container_client(container)
                blobs = container_client.list_blobs(name_starts_with=prefix or None)
                results = []
                for blob in blobs:
                    results.append(
                        AzureBlobMetadata(
                            key=blob.name,
                            etag=str(blob.etag or "").strip('"'),
                            last_modified=blob.last_modified or datetime.now(timezone.utc),
                            size=blob.size or 0,
                            content_type=blob.content_settings.content_type
                            if blob.content_settings
                            else None,
                        )
                    )
                return results
            except ClientAuthenticationError as exc:
                raise AzureBlobAuthError("Azure Blob credentials were rejected") from exc
            except AzureError as exc:
                raise AzureBlobConfigError(f"Azure Blob list_blobs failed: {exc}") from exc

        def download_blob(self, *, container: str, key: str) -> bytes:
            try:
                container_client = self._service_client.get_container_client(container)
                blob_client = container_client.get_blob_client(key)
                stream = blob_client.download_blob()
                return stream.readall()
            except ClientAuthenticationError as exc:
                raise AzureBlobAuthError("Azure Blob credentials were rejected") from exc
            except ResourceNotFoundError as exc:
                raise AzureBlobConfigError(f"Azure Blob not found: {key}") from exc
            except AzureError as exc:
                raise AzureBlobConfigError(f"Azure Blob download failed for {key}: {exc}") from exc

    return _AzureBlobClientImpl()


def _resolve_account_key(value: str, env: Mapping[str, str]) -> str:
    if isinstance(value, str) and value.startswith("env:"):
        env_name = value.removeprefix("env:")
        resolved = env.get(env_name)
        if resolved is None:
            raise AzureBlobAuthError(f"missing required environment variable: {env_name}")
        return resolved
    raise AzureBlobConfigError("source.azure_blob account_key must use env: references")


def ingest_azure_blob_source(
    session: Session,
    *,
    knowledge_base_name: str,
    config: dict[str, object],
    workspace_id: UUID | None = None,
    env: Mapping[str, str] | None = None,
    client: AzureBlobClientProtocol | None = None,
) -> IngestionReport:
    registry = get_plugin_registry()
    validated = registry.validate_config("source.azure_blob", config)
    _env = env or os.environ

    account_name = str(validated["account_name"])
    account_key = _resolve_account_key(str(validated["account_key"]), _env)

    active_client = client or _build_azure_client(account_name, account_key)

    return _run_azure_blob_ingest(
        session,
        knowledge_base_name=knowledge_base_name,
        workspace_id=workspace_id,
        container=str(validated["container"]),
        prefix=str(validated.get("prefix") or ""),
        config=validated,
        client=active_client,
        secret_values=[account_key],
    )


def _run_azure_blob_ingest(
    session: Session,
    *,
    knowledge_base_name: str,
    workspace_id: UUID | None = None,
    container: str,
    prefix: str,
    config: dict[str, object],
    client: AzureBlobClientProtocol,
    secret_values: list[str],
) -> IngestionReport:
    source_uri = _source_uri(container, prefix)

    if workspace_id is None:
        knowledge_base = get_or_create_knowledge_base(session, knowledge_base_name)
    else:
        knowledge_base = get_or_create_knowledge_base(
            session,
            knowledge_base_name,
            workspace_id=workspace_id,
        )

    source = get_or_create_source(
        session,
        knowledge_base_id=knowledge_base.id,
        kind="azure_blob",
        uri=source_uri,
        config_json=config,
    )
    run = create_pipeline_run(
        session,
        knowledge_base_id=knowledge_base.id,
        source_id=source.id,
        run_type="azure_blob_ingest",
        config_snapshot_json=config,
    )

    includes = list(config.get("include_patterns") or []) or list(DEFAULT_INCLUDE_PATTERNS)
    excludes = list(config.get("exclude_patterns") or [])
    max_bytes = int(float(config["max_object_size_mb"]) * 1024 * 1024)
    page_size = int(config["page_size"])

    try:
        all_blobs = client.list_blobs(
            container=container,
            prefix=prefix,
            max_results=page_size,
        )
    except AzureBlobAuthError as exc:
        _fail_run(run, exc, secret_values=secret_values)
        session.commit()
        raise

    discovered: list[AzureBlobMetadata] = []
    skipped_items: list[tuple[AzureBlobMetadata, str]] = []

    for blob in all_blobs:
        key = blob.key
        if any(fnmatch(key, pattern) for pattern in excludes):
            skipped_items.append((blob, "excluded"))
            continue
        if not any(
            fnmatch(key, pattern) or fnmatch(key.rsplit("/", 1)[-1], pattern)
            for pattern in includes
        ):
            skipped_items.append((blob, "unsupported_extension"))
            continue
        if blob.size > max_bytes:
            skipped_items.append((blob, "object_too_large"))
            continue
        discovered.append(blob)

    created_documents = 0
    created_versions = 0
    skipped_count = 0
    failed_count = 0

    for blob, reason in skipped_items:
        document, was_created = _get_or_create_azure_document(
            session,
            knowledge_base_id=knowledge_base.id,
            source_id=source.id,
            container=container,
            blob=blob,
            content_hash=f"skipped:{reason}",
            mime_type=blob.content_type or "application/octet-stream",
            metadata_json={**_blob_metadata_payload(blob), "skip_reason": reason},
        )
        if was_created:
            created_documents += 1
        create_pipeline_run_item(
            session,
            pipeline_run_id=run.id,
            document_id=document.id,
            status="skipped",
            metadata_json={**_blob_metadata_payload(blob), "skip_reason": reason},
        )
        skipped_count += 1

    for blob in discovered:
        try:
            with session.begin_nested():
                document_uri = _document_uri(container, blob.key)
                document = get_document_by_uri(
                    session,
                    knowledge_base_id=knowledge_base.id,
                    uri=document_uri,
                )
                snapshot = _blob_snapshot(blob)
                if (
                    document is not None
                    and document.metadata_json.get("object_snapshot") == snapshot
                ):
                    create_pipeline_run_item(
                        session,
                        pipeline_run_id=run.id,
                        document_id=document.id,
                        status="skipped",
                        metadata_json={
                            **_blob_metadata_payload(blob),
                            "skip_reason": "unchanged",
                        },
                    )
                    skipped_count += 1
                    continue

                body = client.download_blob(container=container, key=blob.key)

                if b"\x00" in body[:8192]:
                    document, was_created = _get_or_create_azure_document(
                        session,
                        knowledge_base_id=knowledge_base.id,
                        source_id=source.id,
                        container=container,
                        blob=blob,
                        content_hash="skipped:binary_file",
                        mime_type=blob.content_type or "application/octet-stream",
                        metadata_json={
                            **_blob_metadata_payload(blob),
                            "skip_reason": "binary_file",
                        },
                    )
                    if was_created:
                        created_documents += 1
                    create_pipeline_run_item(
                        session,
                        pipeline_run_id=run.id,
                        document_id=document.id,
                        status="skipped",
                        metadata_json={
                            **_blob_metadata_payload(blob),
                            "skip_reason": "binary_file",
                        },
                    )
                    skipped_count += 1
                    continue

                parse_result = _parse_blob_bytes(blob.key, body)
                metadata_json = {
                    **_blob_metadata_payload(blob),
                    "object_snapshot": snapshot,
                    "parser_metadata": parse_result.metadata,
                }
                document, was_created = _get_or_create_azure_document(
                    session,
                    knowledge_base_id=knowledge_base.id,
                    source_id=source.id,
                    container=container,
                    blob=blob,
                    content_hash=parse_result.content_hash,
                    mime_type=parse_result.mime_type,
                    metadata_json=metadata_json,
                )
                if was_created:
                    created_documents += 1

                version = DocumentVersion(
                    document_id=document.id,
                    version_number=get_next_version_number(session, document_id=document.id),
                    content_hash=parse_result.content_hash,
                    parser_name=parse_result.parser_name,
                    parser_config_json={"plugin_id": _parser_plugin_id(parse_result.parser_name)},
                    extracted_text=parse_result.extracted_text,
                    metadata_json=metadata_json,
                )
                session.add(version)
                session.flush()
                created_versions += 1

                create_pipeline_run_item(
                    session,
                    pipeline_run_id=run.id,
                    document_id=document.id,
                    status="success",
                    metadata_json={
                        **metadata_json,
                        "version_number": version.version_number,
                    },
                )
        except AzureBlobAuthError as exc:
            _fail_run(run, exc, secret_values=secret_values)
            session.commit()
            raise
        except (AzureBlobConfigError, UnicodeDecodeError) as exc:
            failed_count += 1
            reason = "parse_failed" if isinstance(exc, UnicodeDecodeError) else "object_read_failed"
            sanitized = _sanitize(str(exc), secrets=secret_values)
            document, was_created = _get_or_create_azure_document(
                session,
                knowledge_base_id=knowledge_base.id,
                source_id=source.id,
                container=container,
                blob=blob,
                content_hash="failed",
                mime_type=blob.content_type or "text/plain",
                metadata_json={**_blob_metadata_payload(blob), "failure_reason": reason},
            )
            if was_created:
                created_documents += 1
            create_pipeline_run_item(
                session,
                pipeline_run_id=run.id,
                document_id=document.id,
                status="failed",
                error_message=sanitized,
                metadata_json={**_blob_metadata_payload(blob), "failure_reason": reason},
            )

    run.total_items = len(discovered) + len(skipped_items)
    run.success_count = created_versions
    run.failure_count = failed_count
    run.status = "completed_with_failures" if failed_count else "completed"
    run.finished_at = datetime.now(timezone.utc)
    session.commit()
    return IngestionReport(
        pipeline_run_id=run.id,
        created_documents=created_documents,
        created_versions=created_versions,
        skipped_count=skipped_count,
        failed_count=failed_count,
    )


def _parse_blob_bytes(key: str, body: bytes):
    suffix = Path(key).suffix
    with NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
        tmp_file.write(body)
        tmp_path = Path(tmp_file.name)
    try:
        parser = _select_parser(Path(key))
        return parser.parse(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _blob_snapshot(blob: AzureBlobMetadata) -> str:
    return f"{blob.etag}:{blob.last_modified.isoformat()}:{blob.size}"


def _blob_metadata_payload(blob: AzureBlobMetadata) -> dict[str, object]:
    return {
        "object_key": blob.key,
        "etag": blob.etag,
        "last_modified": blob.last_modified.isoformat(),
        "size": blob.size,
        "content_type": blob.content_type,
    }


def _document_uri(container: str, key: str) -> str:
    return f"azure-blob://{container}/{key}"


def _source_uri(container: str, prefix: str) -> str:
    if not prefix:
        return f"azure-blob://{container}"
    return f"azure-blob://{container}/{prefix}"


def _get_or_create_azure_document(
    session: Session,
    *,
    knowledge_base_id,
    source_id,
    container: str,
    blob: AzureBlobMetadata,
    content_hash: str,
    mime_type: str,
    metadata_json: dict[str, object],
):
    return get_or_create_document(
        session,
        knowledge_base_id=knowledge_base_id,
        source_id=source_id,
        uri=_document_uri(container, blob.key),
        content_hash=content_hash,
        mime_type=mime_type,
        metadata_json=metadata_json,
    )


def _fail_run(run, exc: Exception, *, secret_values: list[str]) -> None:
    run.status = "failed"
    run.error_message = _sanitize(str(exc), secrets=secret_values)
    run.finished_at = datetime.now(timezone.utc)


def _sanitize(message: str, *, secrets: list[str]) -> str:
    sanitized = message
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "[REDACTED]")
    return sanitized
