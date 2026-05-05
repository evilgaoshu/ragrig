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
from ragrig.plugins.sources.fileshare.client import (
    FakeFileshareClient,
    FileshareClientProtocol,
    FileshareFileMetadata,
    MountedPathClient,
)
from ragrig.plugins.sources.fileshare.errors import (
    FileshareConfigError,
    FileshareCredentialError,
    FilesharePermanentError,
    FileshareRetryableError,
    sanitize_error_message,
)
from ragrig.plugins.sources.fileshare.scanner import scan_files
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
class ResolvedFileshareSecrets:
    username: str | None = None
    password: str | None = None
    private_key: str | None = None


def ingest_fileshare_source(
    session: Session,
    *,
    knowledge_base_name: str,
    config: dict[str, object],
    env: Mapping[str, str] | None = None,
    client: FileshareClientProtocol | None = None,
    dry_run: bool = False,
) -> IngestionReport:
    registry = get_plugin_registry()
    validated = registry.validate_config("source.fileshare", config)
    if validated["protocol"] == "nfs_mounted" and dry_run:
        mounted_client = MountedPathClient(root_path=Path(str(validated["root_path"])))
        scan_result = scan_files(mounted_client, config=validated)
        return IngestionReport(
            pipeline_run_id="dry-run",
            created_documents=0,
            created_versions=0,
            skipped_count=len(scan_result.discovered)
            + len(scan_result.skipped)
            + len(scan_result.deleted),
            failed_count=0,
        )

    secrets = _resolve_secrets(validated, env=env or os.environ)
    active_client = client or _build_client(validated)
    source_uri = _source_uri(validated)
    knowledge_base = get_or_create_knowledge_base(session, knowledge_base_name)
    source = get_or_create_source(
        session,
        knowledge_base_id=knowledge_base.id,
        kind="fileshare",
        uri=source_uri,
        config_json=validated,
    )
    run = create_pipeline_run(
        session,
        knowledge_base_id=knowledge_base.id,
        source_id=source.id,
        run_type="fileshare_ingest",
        config_snapshot_json=_config_snapshot(validated),
    )

    try:
        scan_result = scan_files(active_client, config=validated)
    except (FileshareConfigError, FileshareCredentialError) as exc:
        _fail_run(run, exc, secrets=secrets)
        session.commit()
        raise exc.__class__(run.error_message or str(exc)) from exc

    created_documents = 0
    created_versions = 0
    skipped_count = 0
    failed_count = 0

    for skipped in scan_result.skipped:
        document, was_created = _get_or_create_fileshare_document(
            session,
            knowledge_base_id=knowledge_base.id,
            source_id=source.id,
            config=validated,
            file_metadata=skipped.file_metadata,
            content_hash=f"skipped:{skipped.reason}",
            mime_type=skipped.file_metadata.content_type or "application/octet-stream",
            metadata_json={
                **_file_metadata_payload(validated, skipped.file_metadata),
                "skip_reason": skipped.reason,
                "permission_mapping": _permission_mapping(skipped.file_metadata),
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
                **_file_metadata_payload(validated, skipped.file_metadata),
                "skip_reason": skipped.reason,
            },
        )
        skipped_count += 1

    for candidate in scan_result.discovered:
        file_metadata = candidate.file_metadata
        try:
            with session.begin_nested():
                document_uri = _document_uri(validated, file_metadata.path)
                document = get_document_by_uri(
                    session,
                    knowledge_base_id=knowledge_base.id,
                    uri=document_uri,
                )
                snapshot = _file_snapshot(file_metadata)
                if (
                    document is not None
                    and document.metadata_json.get("source_snapshot") == snapshot
                ):
                    create_pipeline_run_item(
                        session,
                        pipeline_run_id=run.id,
                        document_id=document.id,
                        status="skipped",
                        metadata_json={
                            **_file_metadata_payload(validated, file_metadata),
                            "skip_reason": "unchanged",
                        },
                    )
                    skipped_count += 1
                    continue

                body = _read_with_retries(
                    active_client,
                    path=file_metadata.path,
                    max_retries=int(validated["max_retries"]),
                )
                parse_result = _parse_file_bytes(file_metadata.path, body)
                metadata_json = {
                    **_file_metadata_payload(validated, file_metadata),
                    "source_snapshot": snapshot,
                    "parser_metadata": parse_result.metadata,
                    "permission_mapping": _permission_mapping(file_metadata),
                }
                document, was_created = _get_or_create_fileshare_document(
                    session,
                    knowledge_base_id=knowledge_base.id,
                    source_id=source.id,
                    config=validated,
                    file_metadata=file_metadata,
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
                        **_file_metadata_payload(validated, file_metadata),
                        "version_number": version.version_number,
                    },
                )
        except (FileshareConfigError, FileshareCredentialError) as exc:
            _fail_run(run, exc, secrets=secrets)
            session.commit()
            raise exc.__class__(run.error_message or str(exc)) from exc
        except (FilesharePermanentError, FileshareRetryableError, UnicodeDecodeError) as exc:
            failed_count += 1
            reason = "parse_failed" if isinstance(exc, UnicodeDecodeError) else "read_failed"
            sanitized = sanitize_error_message(
                str(exc),
                secrets=[secrets.username or "", secrets.password or "", secrets.private_key or ""],
            )
            document, was_created = _get_or_create_fileshare_document(
                session,
                knowledge_base_id=knowledge_base.id,
                source_id=source.id,
                config=validated,
                file_metadata=file_metadata,
                content_hash="failed",
                mime_type=file_metadata.content_type or "text/plain",
                metadata_json={
                    **_file_metadata_payload(validated, file_metadata),
                    "failure_reason": reason,
                    "permission_mapping": _permission_mapping(file_metadata),
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
                    **_file_metadata_payload(validated, file_metadata),
                    "failure_reason": reason,
                },
            )

    for deleted in scan_result.deleted:
        document = get_document_by_uri(
            session,
            knowledge_base_id=knowledge_base.id,
            uri=deleted.uri,
        )
        if document is None:
            deleted_path = deleted.uri.removeprefix(f"{_source_uri(validated)}/")
            synthetic_metadata = FileshareFileMetadata(
                path=deleted_path,
                modified_at=datetime.now(timezone.utc),
                size=0,
                content_type=None,
            )
            document, was_created = _get_or_create_fileshare_document(
                session,
                knowledge_base_id=knowledge_base.id,
                source_id=source.id,
                config=validated,
                file_metadata=synthetic_metadata,
                content_hash="skipped:deleted_upstream",
                mime_type="application/octet-stream",
                metadata_json={
                    **_file_metadata_payload(validated, synthetic_metadata),
                    "skip_reason": "deleted_upstream",
                    "delete_detection": "placeholder",
                    "permission_mapping": _permission_mapping(synthetic_metadata),
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
                "skip_reason": "deleted_upstream",
                "delete_detection": "placeholder",
                "uri": deleted.uri,
            },
        )
        skipped_count += 1

    run.total_items = (
        len(scan_result.discovered) + len(scan_result.skipped) + len(scan_result.deleted)
    )
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


def _resolve_secrets(
    config: dict[str, object], *, env: Mapping[str, str]
) -> ResolvedFileshareSecrets:
    def _resolve(value: object, *, required: bool) -> str | None:
        if value is None:
            if required:
                raise FileshareConfigError("missing required secret reference")
            return None
        if not isinstance(value, str) or not value.startswith("env:"):
            raise FileshareConfigError("source.fileshare secrets must use env: references")
        env_name = value.removeprefix("env:")
        resolved = env.get(env_name)
        if resolved is None:
            raise FileshareConfigError(f"missing required secret env: {env_name}")
        return resolved

    return ResolvedFileshareSecrets(
        username=_resolve(config.get("username"), required=config["protocol"] != "nfs_mounted"),
        password=_resolve(config.get("password"), required=False),
        private_key=_resolve(config.get("private_key"), required=False),
    )


def _build_client(config: dict[str, object]) -> FileshareClientProtocol:
    if config["protocol"] == "nfs_mounted":
        return MountedPathClient(root_path=Path(str(config["root_path"])))
    return FakeFileshareClient(
        protocol=str(config["protocol"]),
        host=str(config.get("host") or "") or None,
        share=str(config.get("share") or "") or None,
        base_url=str(config.get("base_url") or "") or None,
    )


def _read_with_retries(client: FileshareClientProtocol, *, path: str, max_retries: int) -> bytes:
    attempts = max_retries + 1
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            return client.read_file(path=path)
        except FileshareRetryableError as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    raise FilesharePermanentError(f"file read failed for {path}")


def _parse_file_bytes(path: str, body: bytes):
    suffix = Path(path).suffix
    with NamedTemporaryFile(suffix=suffix, delete=False) as tmp_file:
        tmp_file.write(body)
        tmp_path = Path(tmp_file.name)
    try:
        parser = _select_parser(Path(path))
        return parser.parse(tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _source_uri(config: dict[str, object]) -> str:
    protocol = str(config["protocol"])
    root_path = str(config["root_path"]).strip("/")
    if protocol == "nfs_mounted":
        return f"nfs://mounted/{root_path}".rstrip("/")
    if protocol == "webdav":
        base_url = str(config["base_url"] or "").rstrip("/")
        suffix = f"/{root_path}" if root_path else ""
        return f"webdav://{base_url.removeprefix('https://').removeprefix('http://')}{suffix}"
    host = str(config.get("host") or "")
    share = str(config.get("share") or "").strip("/")
    suffix = f"/{root_path}" if root_path else ""
    return f"{protocol}://{host}/{share}{suffix}".rstrip("/")


def _document_uri(config: dict[str, object], path: str) -> str:
    normalized_path = _normalize_remote_path(str(config["root_path"]), path)
    return f"{_source_uri(config)}/{normalized_path}".rstrip("/")


def _file_snapshot(file_metadata: FileshareFileMetadata) -> str:
    content_type = file_metadata.content_type or ""
    return f"{file_metadata.modified_at.isoformat()}:{file_metadata.size}:{content_type}"


def _file_metadata_payload(
    config: dict[str, object], file_metadata: FileshareFileMetadata
) -> dict[str, object]:
    return {
        "protocol": config["protocol"],
        "remote_path": file_metadata.path,
        "modified_at": file_metadata.modified_at.isoformat(),
        "size": file_metadata.size,
        "content_type": file_metadata.content_type,
        "source_uri": _source_uri(config),
    }


def _permission_mapping(file_metadata: FileshareFileMetadata) -> dict[str, object]:
    return {
        "owner": file_metadata.owner,
        "group": file_metadata.group,
        "permissions": file_metadata.permissions,
        "enforcement": "not_implemented",
    }


def _config_snapshot(config: dict[str, object]) -> dict[str, object]:
    snapshot = dict(config)
    for key in ("username", "password", "private_key"):
        if snapshot.get(key) is not None:
            snapshot[key] = "[secret]"
    return snapshot


def _get_or_create_fileshare_document(
    session: Session,
    *,
    knowledge_base_id,
    source_id,
    config: dict[str, object],
    file_metadata: FileshareFileMetadata,
    content_hash: str,
    mime_type: str,
    metadata_json: dict[str, object],
):
    return get_or_create_document(
        session,
        knowledge_base_id=knowledge_base_id,
        source_id=source_id,
        uri=_document_uri(config, file_metadata.path),
        content_hash=content_hash,
        mime_type=mime_type,
        metadata_json=metadata_json,
    )


def _normalize_remote_path(root_path: str, path: str) -> str:
    normalized_root = root_path.strip("/")
    normalized_path = path.strip("/")
    if normalized_root and normalized_path.startswith(f"{normalized_root}/"):
        return normalized_path.removeprefix(f"{normalized_root}/")
    return normalized_path


def _fail_run(run, exc: Exception, *, secrets: ResolvedFileshareSecrets) -> None:
    run.status = "failed"
    run.error_message = sanitize_error_message(
        str(exc),
        secrets=[secrets.username or "", secrets.password or "", secrets.private_key or ""],
    )
    run.finished_at = datetime.now(timezone.utc)
