from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from sqlalchemy.orm import Session

from ragrig.db.models import DocumentVersion
from ragrig.ingestion.pipeline import IngestionReport, _parser_plugin_id, _select_parser
from ragrig.plugins import get_plugin_registry
from ragrig.plugins.sources.s3.client import Boto3S3Client, S3ClientProtocol, S3ObjectMetadata
from ragrig.plugins.sources.s3.config import (
    S3SourceConfig,
    redact_s3_config,
    resolve_s3_credentials,
)
from ragrig.plugins.sources.s3.errors import (
    MissingDependencyError,
    PermanentObjectError,
    RetryableObjectError,
    S3ConfigError,
    S3CredentialError,
)
from ragrig.plugins.sources.s3.scanner import scan_objects
from ragrig.repositories import (
    create_pipeline_run,
    create_pipeline_run_item,
    get_document_by_uri,
    get_next_version_number,
    get_or_create_document,
    get_or_create_knowledge_base,
    get_or_create_source,
)


def ingest_s3_source(
    session: Session,
    *,
    knowledge_base_name: str,
    config: dict[str, object],
    client: S3ClientProtocol | None = None,
    env: Mapping[str, str] | None = None,
) -> IngestionReport:
    validated = get_plugin_registry().validate_config("source.s3", config)
    source_config = S3SourceConfig.model_validate(validated)
    redacted_config = redact_s3_config(validated)

    knowledge_base = get_or_create_knowledge_base(session, knowledge_base_name)
    source = get_or_create_source(
        session,
        knowledge_base_id=knowledge_base.id,
        kind="s3",
        uri=_source_uri(source_config.bucket, source_config.prefix),
        config_json=redacted_config,
    )
    run = create_pipeline_run(
        session,
        knowledge_base_id=knowledge_base.id,
        source_id=source.id,
        run_type="s3_ingest",
        config_snapshot_json=redacted_config,
    )
    env_mapping = env if env is not None else os.environ
    try:
        credentials = resolve_s3_credentials(source_config, env=env_mapping)
    except S3ConfigError as exc:
        _fail_run(run, message=str(exc))
        session.commit()
        raise

    active_client = client
    if active_client is None:
        active_client = Boto3S3Client(config=source_config, credentials=credentials)

    secret_values = [credentials.access_key, credentials.secret_key]
    if credentials.session_token is not None:
        secret_values.append(credentials.session_token)

    try:
        scan_result = scan_objects(
            client=active_client,
            bucket=source_config.bucket,
            prefix=source_config.prefix,
            include_patterns=source_config.include_patterns,
            exclude_patterns=source_config.exclude_patterns,
            max_object_size_bytes=source_config.max_object_size_mb * 1024 * 1024,
            page_size=source_config.page_size,
        )
    except (MissingDependencyError, S3ConfigError, S3CredentialError) as exc:
        _fail_run(run, message=_sanitize_error(str(exc), secrets=secret_values))
        session.commit()
        raise

    created_documents = 0
    created_versions = 0
    skipped_count = 0
    failed_count = 0

    for skipped in scan_result.skipped:
        document, was_created = _get_or_create_placeholder_document(
            session,
            knowledge_base_id=knowledge_base.id,
            source_id=source.id,
            bucket=source_config.bucket,
            object_metadata=skipped.object_metadata,
            reason=skipped.reason,
        )
        if was_created:
            created_documents += 1
        create_pipeline_run_item(
            session,
            pipeline_run_id=run.id,
            document_id=document.id,
            status="skipped",
            metadata_json=_item_metadata(skipped.object_metadata, skip_reason=skipped.reason),
        )
        skipped_count += 1

    for candidate in scan_result.discovered:
        object_metadata = candidate.object_metadata
        document_uri = _document_uri(source_config.bucket, object_metadata.key)
        existing_document = get_document_by_uri(
            session,
            knowledge_base_id=knowledge_base.id,
            uri=document_uri,
        )
        current_snapshot = _object_snapshot(object_metadata)
        previous_snapshot = None
        if existing_document is not None:
            previous_snapshot = existing_document.metadata_json.get("s3_snapshot")
        if previous_snapshot == current_snapshot:
            if existing_document is not None:
                create_pipeline_run_item(
                    session,
                    pipeline_run_id=run.id,
                    document_id=existing_document.id,
                    status="skipped",
                    metadata_json=_item_metadata(object_metadata, skip_reason="unchanged"),
                )
                skipped_count += 1
                continue

        try:
            with session.begin_nested():
                parse_result = _download_and_parse(
                    client=active_client,
                    source_config=source_config,
                    object_metadata=object_metadata,
                )
                document, was_created = get_or_create_document(
                    session,
                    knowledge_base_id=knowledge_base.id,
                    source_id=source.id,
                    uri=document_uri,
                    content_hash=parse_result.content_hash,
                    mime_type=parse_result.mime_type,
                    metadata_json=_document_metadata(
                        object_metadata,
                        parser_metadata=parse_result.metadata,
                    ),
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
                    metadata_json=_version_metadata(object_metadata, parse_result.metadata),
                )
                session.add(version)
                session.flush()
                created_versions += 1
                create_pipeline_run_item(
                    session,
                    pipeline_run_id=run.id,
                    document_id=document.id,
                    status="success",
                    metadata_json=_item_metadata(
                        object_metadata,
                        parser_metadata=parse_result.metadata,
                    ),
                )
        except _SkipObject as exc:
            document, was_created = _get_or_create_placeholder_document(
                session,
                knowledge_base_id=knowledge_base.id,
                source_id=source.id,
                bucket=source_config.bucket,
                object_metadata=object_metadata,
                reason=exc.reason,
            )
            if was_created:
                created_documents += 1
            create_pipeline_run_item(
                session,
                pipeline_run_id=run.id,
                document_id=document.id,
                status="skipped",
                metadata_json=_item_metadata(object_metadata, skip_reason=exc.reason),
            )
            skipped_count += 1
        except Exception as exc:  # pragma: no cover - exercised through tests with concrete types
            failed_count += 1
            document, was_created = _get_or_create_failure_document(
                session,
                knowledge_base_id=knowledge_base.id,
                source_id=source.id,
                bucket=source_config.bucket,
                object_metadata=object_metadata,
                failure_reason=_sanitize_error(str(exc), secrets=secret_values),
            )
            if was_created:
                created_documents += 1
            create_pipeline_run_item(
                session,
                pipeline_run_id=run.id,
                document_id=document.id,
                status="failed",
                error_message=_sanitize_error(str(exc), secrets=secret_values),
                metadata_json=_item_metadata(
                    object_metadata,
                    failure_reason=_sanitize_error(str(exc), secrets=secret_values),
                ),
            )

    run.total_items = len(scan_result.discovered) + len(scan_result.skipped)
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


class _SkipObject(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _download_and_parse(
    *,
    client: S3ClientProtocol,
    source_config: S3SourceConfig,
    object_metadata: S3ObjectMetadata,
):
    suffix = Path(object_metadata.key).suffix
    with NamedTemporaryFile(delete=False, suffix=suffix) as handle:
        temp_path = Path(handle.name)
    try:
        _download_with_retries(
            client=client,
            source_config=source_config,
            object_metadata=object_metadata,
            destination=temp_path,
        )
        if _is_binary_file(temp_path):
            raise _SkipObject("binary_file")
        parser = _select_parser(temp_path)
        return parser.parse(temp_path)
    finally:
        with suppress(FileNotFoundError):
            temp_path.unlink()


def _download_with_retries(
    *,
    client: S3ClientProtocol,
    source_config: S3SourceConfig,
    object_metadata: S3ObjectMetadata,
    destination: Path,
) -> None:
    attempts = 0
    while True:
        try:
            client.download_object(
                bucket=source_config.bucket,
                key=object_metadata.key,
                destination=destination,
            )
            return
        except RetryableObjectError:
            attempts += 1
            if attempts > source_config.max_retries:
                raise
        except (PermanentObjectError, S3ConfigError, S3CredentialError):
            raise


def _is_binary_file(path: Path) -> bool:
    return b"\x00" in path.read_bytes()[:8192]


def _document_uri(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def _source_uri(bucket: str, prefix: str) -> str:
    if prefix:
        return f"s3://{bucket}/{prefix}"
    return f"s3://{bucket}"


def _object_snapshot(object_metadata: S3ObjectMetadata) -> dict[str, object]:
    return {
        "etag": object_metadata.etag,
        "last_modified": object_metadata.last_modified.isoformat(),
        "size": object_metadata.size,
    }


def _base_metadata(object_metadata: S3ObjectMetadata) -> dict[str, object]:
    return {
        "object_key": object_metadata.key,
        "etag": object_metadata.etag,
        "last_modified": object_metadata.last_modified.isoformat(),
        "size": object_metadata.size,
        "content_type": object_metadata.content_type,
        "s3_snapshot": _object_snapshot(object_metadata),
    }


def _document_metadata(
    object_metadata: S3ObjectMetadata,
    *,
    parser_metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    metadata = _base_metadata(object_metadata)
    if parser_metadata is not None:
        metadata["parser_metadata"] = parser_metadata
    return metadata


def _version_metadata(
    object_metadata: S3ObjectMetadata,
    parser_metadata: dict[str, object],
) -> dict[str, object]:
    metadata = _base_metadata(object_metadata)
    metadata["parser_metadata"] = parser_metadata
    return metadata


def _item_metadata(
    object_metadata: S3ObjectMetadata,
    *,
    parser_metadata: dict[str, object] | None = None,
    skip_reason: str | None = None,
    failure_reason: str | None = None,
) -> dict[str, object]:
    metadata = _base_metadata(object_metadata)
    if parser_metadata is not None:
        metadata["parser_metadata"] = parser_metadata
    if skip_reason is not None:
        metadata["skip_reason"] = skip_reason
    if failure_reason is not None:
        metadata["failure_reason"] = failure_reason
    return metadata


def _get_or_create_placeholder_document(
    session: Session,
    *,
    knowledge_base_id,
    source_id,
    bucket: str,
    object_metadata: S3ObjectMetadata,
    reason: str,
):
    return _get_or_create_stub_document(
        session,
        knowledge_base_id=knowledge_base_id,
        source_id=source_id,
        bucket=bucket,
        object_metadata=object_metadata,
        content_hash=f"skipped:{reason}",
        mime_type=object_metadata.content_type or "application/octet-stream",
        extra_metadata={"skip_reason": reason},
    )


def _get_or_create_failure_document(
    session: Session,
    *,
    knowledge_base_id,
    source_id,
    bucket: str,
    object_metadata: S3ObjectMetadata,
    failure_reason: str,
):
    return _get_or_create_stub_document(
        session,
        knowledge_base_id=knowledge_base_id,
        source_id=source_id,
        bucket=bucket,
        object_metadata=object_metadata,
        content_hash="failed",
        mime_type=object_metadata.content_type or "text/plain",
        extra_metadata={"failure_reason": failure_reason},
    )


def _get_or_create_stub_document(
    session: Session,
    *,
    knowledge_base_id,
    source_id,
    bucket: str,
    object_metadata: S3ObjectMetadata,
    content_hash: str,
    mime_type: str,
    extra_metadata: dict[str, object],
):
    uri = _document_uri(bucket, object_metadata.key)
    document = get_document_by_uri(session, knowledge_base_id=knowledge_base_id, uri=uri)
    if document is not None:
        return document, False
    return get_or_create_document(
        session,
        knowledge_base_id=knowledge_base_id,
        source_id=source_id,
        uri=uri,
        content_hash=content_hash,
        mime_type=mime_type,
        metadata_json=_base_metadata(object_metadata) | extra_metadata,
    )


def _fail_run(run, *, message: str) -> None:
    run.status = "failed"
    run.error_message = message
    run.finished_at = datetime.now(timezone.utc)


def _sanitize_error(message: str, *, secrets: Sequence[str]) -> str:
    sanitized = message
    for secret in secrets:
        if secret:
            sanitized = sanitized.replace(secret, "[redacted]")
    return sanitized
