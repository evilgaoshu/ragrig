from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Mapping

from sqlalchemy.orm import Session

from ragrig.db.models import DocumentVersion
from ragrig.ingestion.pipeline import IngestionReport, _parser_plugin_id, _select_parser
from ragrig.plugins import get_plugin_registry
from ragrig.plugins.sources.s3.client import S3ClientProtocol, S3ObjectMetadata, build_boto3_client
from ragrig.plugins.sources.s3.errors import (
    S3ConfigError,
    S3CredentialError,
    S3PermanentError,
    S3RetryableError,
    sanitize_error_message,
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


@dataclass(frozen=True)
class ResolvedS3Secrets:
    access_key: str
    secret_key: str
    session_token: str | None = None


def ingest_s3_source(
    session: Session,
    *,
    knowledge_base_name: str,
    config: dict[str, object],
    env: Mapping[str, str] | None = None,
    client: S3ClientProtocol | None = None,
) -> IngestionReport:
    registry = get_plugin_registry()
    validated = registry.validate_config("source.s3", config)
    secrets = _resolve_secrets(validated, env=env or os.environ)
    source_uri = _source_uri(str(validated["bucket"]), str(validated.get("prefix") or ""))
    knowledge_base = get_or_create_knowledge_base(session, knowledge_base_name)
    source = get_or_create_source(
        session,
        knowledge_base_id=knowledge_base.id,
        kind="s3",
        uri=source_uri,
        config_json=validated,
    )
    run = create_pipeline_run(
        session,
        knowledge_base_id=knowledge_base.id,
        source_id=source.id,
        run_type="s3_ingest",
        config_snapshot_json=validated,
    )

    active_client = client or build_boto3_client({**validated, **secrets.__dict__})
    try:
        scan_result = scan_objects(active_client, config=validated)
    except (S3ConfigError, S3CredentialError) as exc:
        _fail_run(run, exc, secrets=secrets)
        session.commit()
        raise exc.__class__(run.error_message or str(exc)) from exc

    created_documents = 0
    created_versions = 0
    skipped_count = 0
    failed_count = 0

    for skipped in scan_result.skipped:
        document, was_created = _get_or_create_s3_document(
            session,
            knowledge_base_id=knowledge_base.id,
            source_id=source.id,
            bucket=str(validated["bucket"]),
            object_metadata=skipped.object_metadata,
            content_hash=f"skipped:{skipped.reason}",
            mime_type=skipped.object_metadata.content_type or "application/octet-stream",
            metadata_json={
                **_object_metadata_payload(skipped.object_metadata),
                "skip_reason": skipped.reason,
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
                **_object_metadata_payload(skipped.object_metadata),
                "skip_reason": skipped.reason,
            },
        )
        skipped_count += 1

    for candidate in scan_result.discovered:
        object_metadata = candidate.object_metadata
        try:
            with session.begin_nested():
                document_uri = _document_uri(str(validated["bucket"]), object_metadata.key)
                document = get_document_by_uri(
                    session,
                    knowledge_base_id=knowledge_base.id,
                    uri=document_uri,
                )
                snapshot = _object_snapshot(object_metadata)
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
                            **_object_metadata_payload(object_metadata),
                            "skip_reason": "unchanged",
                        },
                    )
                    skipped_count += 1
                    continue

                body = _download_with_retries(
                    active_client,
                    bucket=str(validated["bucket"]),
                    key=object_metadata.key,
                    max_retries=int(validated["max_retries"]),
                )
                if b"\x00" in body[:8192]:
                    document, was_created = _get_or_create_s3_document(
                        session,
                        knowledge_base_id=knowledge_base.id,
                        source_id=source.id,
                        bucket=str(validated["bucket"]),
                        object_metadata=object_metadata,
                        content_hash="skipped:binary_file",
                        mime_type=object_metadata.content_type or "application/octet-stream",
                        metadata_json={
                            **_object_metadata_payload(object_metadata),
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
                            **_object_metadata_payload(object_metadata),
                            "skip_reason": "binary_file",
                        },
                    )
                    skipped_count += 1
                    continue

                parse_result = _parse_object_bytes(object_metadata.key, body)
                metadata_json = {
                    **_object_metadata_payload(object_metadata),
                    "object_snapshot": snapshot,
                    "parser_metadata": parse_result.metadata,
                }
                document, was_created = _get_or_create_s3_document(
                    session,
                    knowledge_base_id=knowledge_base.id,
                    source_id=source.id,
                    bucket=str(validated["bucket"]),
                    object_metadata=object_metadata,
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
        except (S3ConfigError, S3CredentialError) as exc:
            _fail_run(run, exc, secrets=secrets)
            session.commit()
            raise exc.__class__(run.error_message or str(exc)) from exc
        except (S3PermanentError, S3RetryableError, UnicodeDecodeError) as exc:
            failed_count += 1
            reason = "object_read_failed"
            if isinstance(exc, UnicodeDecodeError):
                reason = "parse_failed"
            sanitized = sanitize_error_message(
                str(exc),
                secrets=[secrets.access_key, secrets.secret_key, secrets.session_token or ""],
            )
            document, was_created = _get_or_create_s3_document(
                session,
                knowledge_base_id=knowledge_base.id,
                source_id=source.id,
                bucket=str(validated["bucket"]),
                object_metadata=object_metadata,
                content_hash="failed",
                mime_type=object_metadata.content_type or "text/plain",
                metadata_json={
                    **_object_metadata_payload(object_metadata),
                    "failure_reason": reason,
                },
            )
            if was_created:
                created_documents += 1
            create_pipeline_run_item(
                session,
                pipeline_run_id=run.id,
                document_id=document.id,
                status="failed",
                error_message=sanitized,
                metadata_json={
                    **_object_metadata_payload(object_metadata),
                    "failure_reason": reason,
                },
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


def _resolve_secrets(config: dict[str, object], *, env: Mapping[str, str]) -> ResolvedS3Secrets:
    def _resolve(value: object, *, required: bool) -> str | None:
        if value is None:
            if required:
                raise S3ConfigError("missing required secret reference")
            return None
        if not isinstance(value, str) or not value.startswith("env:"):
            raise S3ConfigError("source.s3 secrets must use env: references")
        env_name = value.removeprefix("env:")
        resolved = env.get(env_name)
        if resolved is None:
            raise S3ConfigError(f"missing required secret env: {env_name}")
        return resolved

    return ResolvedS3Secrets(
        access_key=_resolve(config["access_key"], required=True) or "",
        secret_key=_resolve(config["secret_key"], required=True) or "",
        session_token=_resolve(config.get("session_token"), required=False),
    )


def _download_with_retries(
    client: S3ClientProtocol,
    *,
    bucket: str,
    key: str,
    max_retries: int,
) -> bytes:
    attempts = max_retries + 1
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            return client.download_object(bucket=bucket, key=key)
        except S3RetryableError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise S3PermanentError(f"object read failed for {key}")


def _parse_object_bytes(key: str, body: bytes):
    suffix = Path(key).suffix
    with NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
        tmp_file.write(body)
        tmp_path = Path(tmp_file.name)
    try:
        parser = _select_parser(Path(key))
        return parser.parse(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _object_snapshot(object_metadata: S3ObjectMetadata) -> str:
    return (
        f"{object_metadata.etag}:{object_metadata.last_modified.isoformat()}:{object_metadata.size}"
    )


def _object_metadata_payload(object_metadata: S3ObjectMetadata) -> dict[str, object]:
    return {
        "object_key": object_metadata.key,
        "etag": object_metadata.etag,
        "last_modified": object_metadata.last_modified.isoformat(),
        "size": object_metadata.size,
        "content_type": object_metadata.content_type,
    }


def _document_uri(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def _source_uri(bucket: str, prefix: str) -> str:
    if not prefix:
        return f"s3://{bucket}"
    return f"s3://{bucket}/{prefix}"


def _get_or_create_s3_document(
    session: Session,
    *,
    knowledge_base_id,
    source_id,
    bucket: str,
    object_metadata: S3ObjectMetadata,
    content_hash: str,
    mime_type: str,
    metadata_json: dict[str, object],
):
    return get_or_create_document(
        session,
        knowledge_base_id=knowledge_base_id,
        source_id=source_id,
        uri=_document_uri(bucket, object_metadata.key),
        content_hash=content_hash,
        mime_type=mime_type,
        metadata_json=metadata_json,
    )


def _fail_run(run, exc: Exception, *, secrets: ResolvedS3Secrets) -> None:
    run.status = "failed"
    run.error_message = sanitize_error_message(
        str(exc),
        secrets=[secrets.access_key, secrets.secret_key, secrets.session_token or ""],
    )
    run.finished_at = datetime.now(timezone.utc)
