from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from ragrig.db.models import DocumentVersion
from ragrig.ingestion.scanner import scan_paths
from ragrig.parsers import MarkdownParser, PlainTextParser
from ragrig.plugins import get_plugin_registry
from ragrig.processing_profile import TaskType, resolve_profile
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
class IngestionReport:
    pipeline_run_id: object
    created_documents: int
    created_versions: int
    skipped_count: int
    failed_count: int


def _select_parser(path: Path):
    get_plugin_registry()
    if path.suffix.lower() in {".md", ".markdown"}:
        return MarkdownParser()
    return PlainTextParser()


def _parser_plugin_id(parser_name: str) -> str:
    if parser_name == "plaintext":
        return "parser.text"
    return f"parser.{parser_name}"


def ingest_local_directory(
    session: Session,
    *,
    knowledge_base_name: str,
    root_path: Path,
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    max_file_size_bytes: int = 10 * 1024 * 1024,
    dry_run: bool = False,
) -> IngestionReport:
    root_path = root_path.resolve()
    scan_result = scan_paths(
        root_path=root_path,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
        max_file_size_bytes=max_file_size_bytes,
    )

    if dry_run:
        return IngestionReport(
            pipeline_run_id="dry-run",
            created_documents=0,
            created_versions=0,
            skipped_count=len(scan_result.discovered) + len(scan_result.skipped),
            failed_count=0,
        )

    knowledge_base = get_or_create_knowledge_base(session, knowledge_base_name)
    source = get_or_create_source(
        session,
        knowledge_base_id=knowledge_base.id,
        uri=str(root_path),
        config_json={
            "root_path": str(root_path),
            "include_patterns": include_patterns or [],
            "exclude_patterns": exclude_patterns or [],
            "max_file_size_bytes": max_file_size_bytes,
        },
    )
    correct_profile = resolve_profile("*", TaskType.CORRECT)
    clean_profile = resolve_profile("*", TaskType.CLEAN)

    run = create_pipeline_run(
        session,
        knowledge_base_id=knowledge_base.id,
        source_id=source.id,
        config_snapshot_json={
            "root_path": str(root_path),
            "include_patterns": include_patterns or [],
            "exclude_patterns": exclude_patterns or [],
            "max_file_size_bytes": max_file_size_bytes,
            "dry_run": dry_run,
            "correct_profile_id": correct_profile.profile_id,
            "clean_profile_id": clean_profile.profile_id,
        },
    )

    created_documents = 0
    created_versions = 0
    skipped_count = 0
    failed_count = 0

    for skipped in scan_result.skipped:
        document = get_document_by_uri(
            session, knowledge_base_id=knowledge_base.id, uri=str(skipped.path)
        )
        if document is None:
            document, was_created = get_or_create_document(
                session,
                knowledge_base_id=knowledge_base.id,
                source_id=source.id,
                uri=str(skipped.path),
                content_hash=f"skipped:{skipped.reason}",
                mime_type="application/octet-stream",
                metadata_json={"skip_reason": skipped.reason, "path": str(skipped.path)},
            )
            if was_created:
                created_documents += 1
        create_pipeline_run_item(
            session,
            pipeline_run_id=run.id,
            document_id=document.id,
            status="skipped",
            metadata_json={"file_name": skipped.path.name, "skip_reason": skipped.reason},
        )
        skipped_count += 1

    for candidate in scan_result.discovered:
        try:
            with session.begin_nested():
                parser = _select_parser(candidate.path)
                parse_result = parser.parse(candidate.path)
                document, was_created = get_or_create_document(
                    session,
                    knowledge_base_id=knowledge_base.id,
                    source_id=source.id,
                    uri=str(candidate.path),
                    content_hash=parse_result.content_hash,
                    mime_type=parse_result.mime_type,
                    metadata_json=parse_result.metadata,
                )
                if was_created:
                    created_documents += 1

                latest_hash = None
                if document.versions:
                    latest_hash = max(
                        document.versions, key=lambda item: item.version_number
                    ).content_hash
                if latest_hash == parse_result.content_hash:
                    create_pipeline_run_item(
                        session,
                        pipeline_run_id=run.id,
                        document_id=document.id,
                        status="skipped",
                        metadata_json={
                            "file_name": candidate.path.name,
                            "skip_reason": "unchanged",
                        },
                    )
                    skipped_count += 1
                    continue

                version = DocumentVersion(
                    document_id=document.id,
                    version_number=get_next_version_number(session, document_id=document.id),
                    content_hash=parse_result.content_hash,
                    parser_name=parse_result.parser_name,
                    parser_config_json={"plugin_id": _parser_plugin_id(parse_result.parser_name)},
                    extracted_text=parse_result.extracted_text,
                    metadata_json=parse_result.metadata,
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
                        "file_name": candidate.path.name,
                        "version_number": version.version_number,
                    },
                )
        except Exception as exc:
            failed_count += 1
            document = get_document_by_uri(
                session, knowledge_base_id=knowledge_base.id, uri=str(candidate.path)
            )
            if document is None:
                document, was_created = get_or_create_document(
                    session,
                    knowledge_base_id=knowledge_base.id,
                    source_id=source.id,
                    uri=str(candidate.path),
                    content_hash="failed",
                    mime_type="text/plain",
                    metadata_json={"failure_reason": str(exc), "path": str(candidate.path)},
                )
                if was_created:
                    created_documents += 1
            create_pipeline_run_item(
                session,
                pipeline_run_id=run.id,
                document_id=document.id,
                status="failed",
                error_message=str(exc),
                metadata_json={"file_name": candidate.path.name},
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
