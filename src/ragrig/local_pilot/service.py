from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from sqlalchemy.orm import Session

from ragrig.answer.provider import get_answer_provider
from ragrig.answer.schema import EvidenceChunk
from ragrig.db.models import DocumentVersion, KnowledgeBase
from ragrig.ingestion.pipeline import _select_parser
from ragrig.ingestion.web_import import MAX_WEBSITE_IMPORT_URLS, collect_website_imports
from ragrig.local_pilot.schema import (
    LocalPilotModelStatus,
    LocalPilotStatus,
    LocalPilotUploadStatus,
    LocalPilotWebsiteStatus,
)
from ragrig.parsers.base import parse_with_timeout
from ragrig.repositories import (
    create_pipeline_run,
    create_pipeline_run_item,
    get_next_version_number,
    get_or_create_document,
    get_or_create_source,
)


def build_local_pilot_status() -> LocalPilotStatus:
    return LocalPilotStatus(
        upload=LocalPilotUploadStatus(
            extensions=[".md", ".markdown", ".txt", ".text", ".pdf", ".docx"],
            max_file_size_mb=50,
        ),
        website_import=LocalPilotWebsiteStatus(
            max_pages=MAX_WEBSITE_IMPORT_URLS,
            modes=["single_url", "sitemap", "docs_url_list"],
        ),
        models=LocalPilotModelStatus(
            required=["model.google_gemini"],
            local_first=["model.ollama", "model.lm_studio", "model.openai_compatible"],
            cloud_supported=["model.openai", "model.openrouter", "model.google_gemini"],
        ),
    )


def import_website_pages(
    session: Session,
    *,
    knowledge_base: KnowledgeBase,
    urls: list[str],
    sitemap_url: str | None = None,
) -> dict[str, Any]:
    result = collect_website_imports(urls=urls, sitemap_url=sitemap_url)
    source_uri = sitemap_url or (urls[0] if urls else "website-import")
    source = get_or_create_source(
        session,
        knowledge_base_id=knowledge_base.id,
        kind="website_import",
        uri=source_uri,
        config_json={
            "kind": "website_import",
            "urls": urls,
            "sitemap_url": sitemap_url,
            "max_pages": MAX_WEBSITE_IMPORT_URLS,
        },
    )
    run = create_pipeline_run(
        session,
        knowledge_base_id=knowledge_base.id,
        source_id=source.id,
        run_type="website_import",
        config_snapshot_json={
            "source": "website_import",
            "urls": urls,
            "sitemap_url": sitemap_url,
            "max_pages": MAX_WEBSITE_IMPORT_URLS,
        },
    )

    success_count = 0
    failure_count = len(result.failures)

    with TemporaryDirectory(prefix="ragrig-web-import-") as staging_dir:
        staging_path = Path(staging_dir)
        for index, page in enumerate(result.accepted_pages, start=1):
            document = None
            try:
                path = staging_path / f"page-{index}.html"
                path.write_text(page.html, encoding="utf-8")
                parser = _select_parser(path)
                parse_result = parse_with_timeout(parser, path, timeout_seconds=30.0)
                metadata = {
                    **parse_result.metadata,
                    "source_url": page.source_url,
                    "title": page.title,
                }
                document, _ = get_or_create_document(
                    session,
                    knowledge_base_id=knowledge_base.id,
                    source_id=source.id,
                    uri=page.source_url,
                    content_hash=parse_result.content_hash,
                    mime_type=parse_result.mime_type,
                    metadata_json=metadata,
                )
                version = DocumentVersion(
                    document_id=document.id,
                    version_number=get_next_version_number(session, document_id=document.id),
                    content_hash=parse_result.content_hash,
                    parser_name=parse_result.parser_name,
                    parser_config_json={"plugin_id": "parser.html"},
                    extracted_text=parse_result.extracted_text,
                    metadata_json=metadata,
                )
                session.add(version)
                session.flush()
                create_pipeline_run_item(
                    session,
                    pipeline_run_id=run.id,
                    document_id=document.id,
                    status="success",
                    metadata_json={
                        "source_url": page.source_url,
                        "title": page.title,
                        "version_number": version.version_number,
                        "parser_name": parse_result.parser_name,
                        "parser_id": "parser.html",
                    },
                )
                success_count += 1
            except Exception as exc:
                failure_count += 1
                if document is None:
                    document, _ = get_or_create_document(
                        session,
                        knowledge_base_id=knowledge_base.id,
                        source_id=source.id,
                        uri=page.source_url,
                        content_hash="failed",
                        mime_type="text/html",
                        metadata_json={
                            "failure_reason": str(exc),
                            "source_url": page.source_url,
                            "title": page.title,
                        },
                    )
                create_pipeline_run_item(
                    session,
                    pipeline_run_id=run.id,
                    document_id=document.id,
                    status="failed",
                    error_message=str(exc),
                    metadata_json={"source_url": page.source_url, "failure_reason": str(exc)},
                )

    for failure in result.failures:
        failed_document, _ = get_or_create_document(
            session,
            knowledge_base_id=knowledge_base.id,
            source_id=source.id,
            uri=failure.source_url,
            content_hash=f"failed:{failure.reason}",
            mime_type="text/html",
            metadata_json={
                "failure_reason": failure.reason,
                "source_url": failure.source_url,
            },
        )
        create_pipeline_run_item(
            session,
            pipeline_run_id=run.id,
            document_id=failed_document.id,
            status="failed",
            error_message=failure.message,
            metadata_json={
                "source_url": failure.source_url,
                "failure_reason": failure.reason,
            },
        )

    run.total_items = len(result.accepted_pages) + len(result.failures)
    run.success_count = success_count
    run.failure_count = failure_count
    run.status = "completed_with_failures" if failure_count else "completed"
    run.finished_at = datetime.now(timezone.utc)
    session.commit()

    return {
        "pipeline_run_id": str(run.id),
        "accepted_pages": success_count,
        "failed_pages": failure_count,
        "failures": [
            {
                "source_url": failure.source_url,
                "reason": failure.reason,
                "message": failure.message,
            }
            for failure in result.failures
        ],
    }


def run_answer_smoke(*, provider: str, model: str | None = None) -> dict[str, Any]:
    evidence = [
        EvidenceChunk(
            citation_id="cit-1",
            document_uri="local-pilot://smoke",
            chunk_id="smoke",
            chunk_index=0,
            text="RAGRig Local Pilot verifies grounded answers with citations.",
            score=1.0,
            distance=0.0,
        )
    ]
    try:
        answer_provider = get_answer_provider(provider, model=model)
        answer, citation_ids = answer_provider.generate(
            "What does Local Pilot verify?",
            evidence,
        )
    except Exception as exc:
        return {
            "provider": provider,
            "model": model,
            "status": "unavailable",
            "detail": str(exc),
        }

    status = "healthy" if "cit-1" in citation_ids or "[cit-1]" in answer else "degraded"
    return {
        "provider": provider,
        "model": model,
        "status": status,
        "detail": answer[:240],
    }
