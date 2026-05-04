from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ragrig.chunkers import ChunkingConfig, chunk_text
from ragrig.db.models import Chunk, Document, DocumentVersion, Embedding
from ragrig.embeddings import EmbeddingResult
from ragrig.providers import BaseProvider, get_provider_registry
from ragrig.repositories import (
    create_pipeline_run,
    create_pipeline_run_item,
    get_knowledge_base_by_name,
    list_latest_document_versions,
)


@dataclass(frozen=True)
class IndexingReport:
    pipeline_run_id: object
    indexed_count: int
    skipped_count: int
    failed_count: int
    chunk_count: int
    embedding_count: int


def _embedding_provider_profile(embedding_provider: BaseProvider) -> tuple[str, str]:
    provider_name = getattr(getattr(embedding_provider, "metadata", None), "name", None)
    if provider_name is None:
        provider_name = embedding_provider.provider_name

    model_name = getattr(embedding_provider, "model_name", None)
    if model_name is None and hasattr(embedding_provider, "_provider"):
        model_name = getattr(embedding_provider._provider, "model_name", None)

    if model_name is None:
        raise ValueError("embedding provider must expose a model name")

    return provider_name, model_name


def _version_already_indexed(
    session: Session,
    *,
    document_version: DocumentVersion,
    config_hash: str,
    provider_name: str,
    model_name: str,
) -> bool:
    chunks = list(
        session.scalars(
            select(Chunk)
            .where(Chunk.document_version_id == document_version.id)
            .order_by(Chunk.chunk_index)
        )
    )
    if not chunks:
        return False

    if any(chunk.metadata_json.get("config_hash") != config_hash for chunk in chunks):
        return False

    chunk_ids = [chunk.id for chunk in chunks]
    embeddings = list(
        session.scalars(
            select(Embedding).where(
                Embedding.chunk_id.in_(chunk_ids),
                Embedding.provider == provider_name,
                Embedding.model == model_name,
            )
        )
    )
    return len(embeddings) == len(chunks)


def _replace_version_index(
    session: Session,
    *,
    document_version: DocumentVersion,
    document: Document,
    chunking_config: ChunkingConfig,
    embedding_provider: BaseProvider,
) -> tuple[int, int]:
    existing_chunk_ids = list(
        session.scalars(select(Chunk.id).where(Chunk.document_version_id == document_version.id))
    )
    if existing_chunk_ids:
        session.execute(delete(Embedding).where(Embedding.chunk_id.in_(existing_chunk_ids)))
    session.execute(delete(Chunk).where(Chunk.document_version_id == document_version.id))
    session.flush()

    chunk_drafts = chunk_text(document_version.extracted_text, chunking_config)
    created_chunks: list[Chunk] = []

    for draft in chunk_drafts:
        chunk = Chunk(
            document_version_id=document_version.id,
            chunk_index=draft.chunk_index,
            text=draft.text,
            char_start=draft.char_start,
            char_end=draft.char_end,
            metadata_json={
                **draft.metadata,
                "content_hash": document_version.content_hash,
                "document_uri": document.uri,
                "parser_name": document_version.parser_name,
                "version_number": document_version.version_number,
            },
        )
        session.add(chunk)
        session.flush()
        created_chunks.append(chunk)

        embedding: EmbeddingResult = embedding_provider.embed_text(draft.text)
        session.add(
            Embedding(
                chunk_id=chunk.id,
                provider=embedding.provider,
                model=embedding.model,
                dimensions=embedding.dimensions,
                embedding=embedding.vector,
                metadata_json={
                    **embedding.metadata,
                    "config_hash": chunking_config.config_hash,
                    "document_version_id": str(document_version.id),
                },
            )
        )

    session.flush()
    return len(created_chunks), len(created_chunks)


def index_knowledge_base(
    session: Session,
    *,
    knowledge_base_name: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    embedding_dimensions: int = 8,
) -> IndexingReport:
    knowledge_base = get_knowledge_base_by_name(session, knowledge_base_name)
    if knowledge_base is None:
        raise ValueError(f"Knowledge base '{knowledge_base_name}' was not found")

    effective_overlap = min(chunk_overlap, max(chunk_size - 1, 0))
    chunking_config = ChunkingConfig(chunk_size=chunk_size, chunk_overlap=effective_overlap)
    embedding_provider = get_provider_registry().get(
        "deterministic-local", dimensions=embedding_dimensions
    )
    provider_name, model_name = _embedding_provider_profile(embedding_provider)
    run = create_pipeline_run(
        session,
        knowledge_base_id=knowledge_base.id,
        source_id=None,
        run_type="chunk_embedding",
        config_snapshot_json={
            **chunking_config.as_metadata(),
            "embedding_dimensions": embedding_dimensions,
            "embedding_model": model_name,
            "embedding_provider": provider_name,
        },
    )

    indexed_count = 0
    skipped_count = 0
    failed_count = 0
    chunk_count = 0
    embedding_count = 0
    versions = list_latest_document_versions(session, knowledge_base_id=knowledge_base.id)

    for version in versions:
        document = version.document
        try:
            with session.begin_nested():
                if version.extracted_text == "":
                    create_pipeline_run_item(
                        session,
                        pipeline_run_id=run.id,
                        document_id=document.id,
                        status="skipped",
                        metadata_json={
                            "document_version_id": str(version.id),
                            "skip_reason": "empty_extracted_text",
                            "version_number": version.version_number,
                        },
                    )
                    skipped_count += 1
                    continue

                if _version_already_indexed(
                    session,
                    document_version=version,
                    config_hash=chunking_config.config_hash,
                    provider_name=provider_name,
                    model_name=model_name,
                ):
                    create_pipeline_run_item(
                        session,
                        pipeline_run_id=run.id,
                        document_id=document.id,
                        status="skipped",
                        metadata_json={
                            "document_version_id": str(version.id),
                            "skip_reason": "already_indexed",
                            "version_number": version.version_number,
                        },
                    )
                    skipped_count += 1
                    continue

                created_chunks, created_embeddings = _replace_version_index(
                    session,
                    document_version=version,
                    document=document,
                    chunking_config=chunking_config,
                    embedding_provider=embedding_provider,
                )
                chunk_count += created_chunks
                embedding_count += created_embeddings
                indexed_count += 1

                create_pipeline_run_item(
                    session,
                    pipeline_run_id=run.id,
                    document_id=document.id,
                    status="success",
                    metadata_json={
                        "chunk_count": created_chunks,
                        "document_version_id": str(version.id),
                        "embedding_dimensions": embedding_dimensions,
                        "version_number": version.version_number,
                    },
                )
        except Exception as exc:
            failed_count += 1
            create_pipeline_run_item(
                session,
                pipeline_run_id=run.id,
                document_id=document.id,
                status="failed",
                error_message=str(exc),
                metadata_json={
                    "document_version_id": str(version.id),
                    "version_number": version.version_number,
                },
            )

    run.total_items = len(versions)
    run.success_count = indexed_count
    run.failure_count = failed_count
    run.status = "completed_with_failures" if failed_count else "completed"
    run.finished_at = datetime.now(timezone.utc)
    session.commit()

    return IndexingReport(
        pipeline_run_id=run.id,
        indexed_count=indexed_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        chunk_count=chunk_count,
        embedding_count=embedding_count,
    )
