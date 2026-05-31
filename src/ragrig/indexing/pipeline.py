from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ragrig.chunkers import ChunkingConfig, chunk_text, chunk_text_hierarchical
from ragrig.db.models import Chunk, Document, DocumentSummary, DocumentVersion, Embedding
from ragrig.embeddings import EmbeddingResult
from ragrig.indexing.conflict_detection import find_conflicting_chunk, record_conflict
from ragrig.indexing.llm_steps import (
    build_embedding_text,
    generate_chunk_context,
    generate_chunk_description,
    generate_document_summary,
)
from ragrig.observability import (
    aggregate_cost_latency,
    hash_attribute,
    log_event,
    observe_model_call,
    set_span_attributes,
    start_span,
    trace_function,
)
from ragrig.pii import redact as pii_redact
from ragrig.plugins import get_plugin_registry
from ragrig.processing_profile import ProcessingProfile, TaskType, resolve_profile
from ragrig.providers import BaseProvider, get_provider_registry
from ragrig.repositories import (
    create_pipeline_run,
    create_pipeline_run_item,
    get_knowledge_base_by_name,
    list_latest_document_versions,
)
from ragrig.vectorstore import build_vector_collection
from ragrig.vectorstore.base import VectorBackend, VectorEmbeddingRecord

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _indexing_span_attributes(*_args, **kwargs) -> dict[str, object]:
    return {
        "ragrig.operation": "indexing.knowledge_base",
        "ragrig.knowledge_base_hash": hash_attribute(
            kwargs.get("knowledge_base_name"), prefix="kb"
        ),
        "ragrig.workspace_hash": hash_attribute(kwargs.get("workspace_id"), prefix="ws"),
        "index.chunk_size": int(kwargs.get("chunk_size", 500) or 500),
        "index.chunk_overlap": int(kwargs.get("chunk_overlap", 50) or 50),
        "embedding.dimensions": int(kwargs.get("embedding_dimensions", 8) or 8),
        "index.force_reindex": bool(kwargs.get("force_reindex", False)),
    }


def _indexing_result_span_attributes(report: "IndexingReport") -> dict[str, object]:
    return {
        "index.indexed_count": report.indexed_count,
        "index.skipped_count": report.skipped_count,
        "index.failed_count": report.failed_count,
        "index.chunk_count": report.chunk_count,
        "index.embedding_count": report.embedding_count,
    }


@dataclass(frozen=True)
class IndexingReport:
    pipeline_run_id: object
    indexed_count: int
    skipped_count: int
    failed_count: int
    chunk_count: int
    embedding_count: int


@dataclass(frozen=True)
class _PreparedChunkEmbedding:
    chunk: Chunk
    chunk_index: int
    embedding_input: str


EMBEDDING_BATCH_SIZE = 32


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

    # In parent-child mode, parent chunks (negative chunk_index) have no embeddings.
    leaf_chunks = [c for c in chunks if c.chunk_index >= 0]
    if not leaf_chunks:
        return False
    chunk_ids = [c.id for c in leaf_chunks]
    embeddings = list(
        session.scalars(
            select(Embedding).where(
                Embedding.chunk_id.in_(chunk_ids),
                Embedding.provider == provider_name,
                Embedding.model == model_name,
            )
        )
    )
    return len(embeddings) == len(leaf_chunks)


def _embed_texts_with_provider(
    embedding_provider: BaseProvider, texts: list[str]
) -> list[EmbeddingResult]:
    if not texts:
        return []

    if getattr(type(embedding_provider), "embed_texts", None) is not None:
        embeddings = list(embedding_provider.embed_texts(texts))
    else:
        embeddings = [embedding_provider.embed_text(text) for text in texts]

    if len(embeddings) != len(texts):
        raise ValueError(
            f"embedding provider returned {len(embeddings)} embeddings for {len(texts)} inputs"
        )
    return embeddings


def _replace_version_index(
    session: Session,
    *,
    document_version: DocumentVersion,
    document: Document,
    chunking_config: ChunkingConfig,
    embedding_provider: BaseProvider,
    chunk_profile_id: str,
    embed_profile_id: str,
    cost_latency_operations: list[dict[str, object]] | None = None,
    workspace_id: object = None,
    pii_redaction: bool = False,
    llm_description_provider: "BaseProvider | None" = None,
    conflict_detection: bool = False,
    conflict_threshold: float = 0.92,
    summary_provider: "BaseProvider | None" = None,
    contextual_provider: "BaseProvider | None" = None,
    embedding_batch_size: int = EMBEDDING_BATCH_SIZE,
) -> tuple[int, int]:
    if embedding_batch_size <= 0:
        raise ValueError("embedding_batch_size must be greater than zero")

    existing_chunk_ids = list(
        session.scalars(select(Chunk.id).where(Chunk.document_version_id == document_version.id))
    )
    if existing_chunk_ids:
        session.execute(delete(Embedding).where(Embedding.chunk_id.in_(existing_chunk_ids)))
    session.execute(delete(Chunk).where(Chunk.document_version_id == document_version.id))
    session.flush()

    source_text = document_version.extracted_text
    if pii_redaction:
        source_text = pii_redact(source_text).redacted_text

    acl_payload: dict[str, object] = {}
    document_acl = (document.metadata_json or {}).get("acl") or (
        document_version.metadata_json or {}
    ).get("acl")
    if isinstance(document_acl, dict):
        acl_payload = {
            "acl": {
                **document_acl,
                "inheritance": "propagated",
            }
        }

    base_meta: dict[str, object] = {
        "content_hash": document_version.content_hash,
        "document_uri": document.uri,
        "document_id": str(document.id),
        "parser_name": document_version.parser_name,
        "version_number": document_version.version_number,
        **acl_payload,
        "profile_id": chunk_profile_id,
    }

    # ── Determine parent-child vs flat chunking ───────────────────────────────
    with start_span(
        "ragrig.indexing.chunk",
        **{
            "ragrig.document_version_hash": hash_attribute(document_version.id, prefix="dv"),
            "ragrig.workspace_hash": hash_attribute(workspace_id, prefix="ws"),
            "index.chunk_size": chunking_config.chunk_size,
            "index.chunk_overlap": chunking_config.chunk_overlap,
            "index.parent_child": chunking_config.parent_chunk_size is not None,
        },
    ) as chunk_span:
        if chunking_config.parent_chunk_size is not None:
            parent_drafts, child_drafts = chunk_text_hierarchical(source_text, chunking_config)
        else:
            parent_drafts, child_drafts = [], chunk_text(source_text, chunking_config)
        set_span_attributes(
            chunk_span,
            **{
                "index.parent_chunk_count": len(parent_drafts),
                "index.child_chunk_count": len(child_drafts),
            },
        )

    # ── Persist parent chunks (no embedding) ─────────────────────────────────
    # Parent chunks use negative chunk_index (-(i+1)) to avoid collisions with
    # the (document_version_id, chunk_index) unique constraint on child chunks.
    parent_id_by_index: dict[int, object] = {}
    for pdraft in parent_drafts:
        parent_chunk = Chunk(
            document_version_id=document_version.id,
            workspace_id=workspace_id,
            chunk_index=-(pdraft.chunk_index + 1),
            text=pdraft.text,
            char_start=pdraft.char_start,
            char_end=pdraft.char_end,
            metadata_json={**pdraft.metadata, **base_meta, "is_parent": True},
        )
        session.add(parent_chunk)
        session.flush()
        parent_id_by_index[pdraft.chunk_index] = parent_chunk.id

    # ── Persist child / leaf chunks (embedded) ────────────────────────────────
    created_chunks: list[Chunk] = []
    prepared_embeddings: list[_PreparedChunkEmbedding] = []
    for draft in child_drafts:
        parent_db_id = (
            parent_id_by_index.get(draft.parent_chunk_index)
            if draft.parent_chunk_index is not None
            else None
        )

        description = generate_chunk_description(draft.text, llm_description_provider)
        context_prefix = generate_chunk_context(source_text, draft.text, contextual_provider)

        # Build the text to embed: context prefix > llm description > plain text
        if context_prefix:
            embedding_input = f"{context_prefix}\n\n{draft.text}"
        else:
            embedding_input = build_embedding_text(draft.text, description)

        chunk = Chunk(
            document_version_id=document_version.id,
            workspace_id=workspace_id,
            chunk_index=draft.chunk_index,
            text=draft.text,
            llm_description=description,
            context_prefix=context_prefix,
            char_start=draft.char_start,
            char_end=draft.char_end,
            parent_chunk_id=parent_db_id,
            metadata_json={
                **draft.metadata,
                **base_meta,
                **({"llm_description": True} if description else {}),
                **({"contextual_retrieval": True} if context_prefix else {}),
                **({"has_parent": True} if parent_db_id is not None else {}),
            },
        )
        session.add(chunk)
        created_chunks.append(chunk)
        prepared_embeddings.append(
            _PreparedChunkEmbedding(
                chunk=chunk,
                chunk_index=draft.chunk_index,
                embedding_input=embedding_input,
            )
        )

    session.flush()
    for batch_start in range(0, len(prepared_embeddings), embedding_batch_size):
        batch = prepared_embeddings[batch_start : batch_start + embedding_batch_size]
        started = perf_counter()
        with start_span(
            "ragrig.indexing.embed",
            **{
                "ragrig.document_version_hash": hash_attribute(document_version.id, prefix="dv"),
                "ragrig.workspace_hash": hash_attribute(workspace_id, prefix="ws"),
                "embedding.provider": getattr(embedding_provider, "provider_name", "unknown"),
                "embedding.batch_size": len(batch),
                "embedding.batch_start": batch_start,
            },
        ) as embed_span:
            embeddings = _embed_texts_with_provider(
                embedding_provider,
                [prepared.embedding_input for prepared in batch],
            )
            if embeddings:
                set_span_attributes(
                    embed_span,
                    **{
                        "embedding.provider": embeddings[0].provider,
                        "embedding.model": embeddings[0].model,
                        "embedding.dimensions": embeddings[0].dimensions,
                        "embedding.count": len(embeddings),
                    },
                )
        batch_latency_ms = (perf_counter() - started) * 1000
        per_embedding_latency_ms = batch_latency_ms / len(embeddings)

        for batch_index, (prepared, embedding) in enumerate(zip(batch, embeddings, strict=True)):
            cost_latency = observe_model_call(
                operation="embedding",
                provider=embedding.provider,
                model=embedding.model,
                input_text=prepared.embedding_input,
                latency_ms=per_embedding_latency_ms,
                metadata={
                    "batch_index": batch_index,
                    "batch_latency_ms": round(batch_latency_ms, 3),
                    "batch_size": len(batch),
                    "chunk_index": prepared.chunk_index,
                    "document_version_id": str(document_version.id),
                },
            )
            if cost_latency_operations is not None:
                cost_latency_operations.append(cost_latency)
            session.add(
                Embedding(
                    chunk_id=prepared.chunk.id,
                    workspace_id=workspace_id,
                    provider=embedding.provider,
                    model=embedding.model,
                    dimensions=embedding.dimensions,
                    embedding=embedding.vector,
                    metadata_json={
                        **embedding.metadata,
                        "config_hash": chunking_config.config_hash,
                        "document_version_id": str(document_version.id),
                        "profile_id": embed_profile_id,
                        "cost_latency": cost_latency,
                    },
                )
            )
            session.flush()

            # Optional: near-duplicate conflict detection
            if conflict_detection and document.knowledge_base_id is not None:
                conflict = find_conflicting_chunk(
                    session,
                    new_vector=embedding.vector,
                    knowledge_base_id=document.knowledge_base_id,
                    new_chunk_id=prepared.chunk.id,
                    threshold=conflict_threshold,
                )
                if conflict is not None:
                    existing_chunk_id, similarity = conflict
                    record_conflict(
                        session,
                        knowledge_base_id=document.knowledge_base_id,
                        new_chunk_id=prepared.chunk.id,
                        existing_chunk_id=existing_chunk_id,
                        similarity=similarity,
                        extra_metadata={
                            "document_uri": document.uri,
                            "chunk_index": prepared.chunk_index,
                        },
                    )
        log_event(
            logger,
            logging.INFO,
            "index.embedding_batch.completed",
            document_id=str(document.id),
            document_version_id=str(document_version.id),
            knowledge_base_id=(
                str(document.knowledge_base_id) if document.knowledge_base_id is not None else None
            ),
            provider=embeddings[0].provider,
            model=embeddings[0].model,
            batch_size=len(batch),
            batch_start=batch_start,
            duration_ms=round(batch_latency_ms, 3),
        )

    # ── Optional: document-level summary + embedding ──────────────────────────
    if summary_provider is not None and source_text.strip():
        summary_text = generate_document_summary(source_text, summary_provider)
        if summary_text:
            # Delete stale summary for this version before inserting a new one
            from sqlalchemy import delete as _delete

            session.execute(
                _delete(DocumentSummary).where(
                    DocumentSummary.document_version_id == document_version.id
                )
            )
            summary_embedding: EmbeddingResult = embedding_provider.embed_text(summary_text)
            session.add(
                DocumentSummary(
                    document_version_id=document_version.id,
                    workspace_id=workspace_id,
                    summary_text=summary_text,
                    provider=summary_embedding.provider,
                    model=summary_embedding.model,
                    dimensions=summary_embedding.dimensions,
                    embedding=summary_embedding.vector,
                    metadata_json={
                        "document_uri": document.uri,
                        "document_id": str(document.id),
                        "profile_id": embed_profile_id,
                    },
                )
            )
            session.flush()

    session.flush()
    return len(created_chunks), len(created_chunks)


def _mirror_version_index(
    session: Session,
    *,
    knowledge_base_name: str,
    knowledge_base_id,
    document_version: DocumentVersion,
    embedding_provider: BaseProvider,
    vector_backend: VectorBackend,
) -> int:
    chunk_records = session.execute(
        select(Embedding, Chunk, DocumentVersion, Document)
        .join(Chunk, Chunk.id == Embedding.chunk_id)
        .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(DocumentVersion.id == document_version.id)
        .order_by(Chunk.chunk_index.asc())
    ).all()
    if not chunk_records:
        return 0
    provider_name, model_name = _embedding_provider_profile(embedding_provider)
    collection = build_vector_collection(
        knowledge_base_name=knowledge_base_name,
        provider=provider_name,
        model=model_name,
        dimensions=embedding_provider.dimensions,
        knowledge_base_id=knowledge_base_id,
    )
    collection = type(collection)(
        name=collection.name,
        knowledge_base=collection.knowledge_base,
        provider=collection.provider,
        model=collection.model,
        dimensions=collection.dimensions,
        knowledge_base_id=knowledge_base_id,
    )
    vector_backend.ensure_collection(session, collection)
    records = [
        VectorEmbeddingRecord(
            embedding_id=embedding.id,
            chunk_id=chunk.id,
            document_id=document.id,
            document_version_id=version.id,
            chunk_index=chunk.chunk_index,
            vector=list(embedding.embedding),
            text=chunk.text,
            metadata={
                "document_uri": document.uri,
                "source_uri": document.source.uri if document.source is not None else None,
                "chunk_metadata": chunk.metadata_json,
                "provider": embedding.provider,
                "model": embedding.model,
                "dimensions": embedding.dimensions,
            },
        )
        for embedding, chunk, version, document in chunk_records
    ]
    with start_span(
        "ragrig.indexing.upsert",
        backend=getattr(vector_backend, "backend_name", "unknown"),
        record_count=len(records),
        **{
            "ragrig.knowledge_base_hash": hash_attribute(knowledge_base_id, prefix="kb"),
        },
    ):
        vector_backend.upsert_embeddings(session, collection, records)
    return len(records)


@trace_function(
    "ragrig.indexing.knowledge_base",
    attributes=_indexing_span_attributes,
    result_attributes=_indexing_result_span_attributes,
)
def index_knowledge_base(
    session: Session,
    *,
    knowledge_base_name: str,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    embedding_dimensions: int = 8,
    embedding_batch_size: int = EMBEDDING_BATCH_SIZE,
    vector_backend: VectorBackend | None = None,
    force_reindex: bool = False,
    pii_redaction: bool = False,
    workspace_id: object = None,
) -> IndexingReport:
    if embedding_batch_size <= 0:
        raise ValueError("embedding_batch_size must be greater than zero")

    run_started = perf_counter()
    get_plugin_registry()
    knowledge_base = get_knowledge_base_by_name(
        session,
        knowledge_base_name,
        workspace_id=workspace_id,
    )
    if knowledge_base is None:
        raise ValueError(f"Knowledge base '{knowledge_base_name}' was not found")

    effective_overlap = min(chunk_overlap, max(chunk_size - 1, 0))
    chunking_config = ChunkingConfig(chunk_size=chunk_size, chunk_overlap=effective_overlap)
    embedding_provider = get_provider_registry().get(
        "deterministic-local", dimensions=embedding_dimensions
    )
    provider_name, model_name = _embedding_provider_profile(embedding_provider)

    chunk_profile: ProcessingProfile = resolve_profile("*", TaskType.CHUNK)
    embed_profile: ProcessingProfile = resolve_profile("*", TaskType.EMBED)

    run = create_pipeline_run(
        session,
        knowledge_base_id=knowledge_base.id,
        source_id=None,
        run_type="chunk_embedding",
        config_snapshot_json={
            **chunking_config.as_metadata(),
            "embedding_dimensions": embedding_dimensions,
            "embedding_batch_size": embedding_batch_size,
            "embedding_model": model_name,
            "embedding_provider": provider_name,
            "chunk_profile_id": chunk_profile.profile_id,
            "embed_profile_id": embed_profile.profile_id,
            "force_reindex": force_reindex,
        },
    )
    log_event(
        logger,
        logging.INFO,
        "index.knowledge_base.start",
        pipeline_run_id=str(run.id),
        knowledge_base=knowledge_base_name,
        knowledge_base_id=str(knowledge_base.id),
        workspace_id=str(knowledge_base.workspace_id),
        chunk_size=chunk_size,
        chunk_overlap=effective_overlap,
        embedding_provider=provider_name,
        embedding_model=model_name,
        embedding_dimensions=embedding_dimensions,
        embedding_batch_size=embedding_batch_size,
        force_reindex=force_reindex,
    )

    indexed_count = 0
    skipped_count = 0
    failed_count = 0
    chunk_count = 0
    embedding_count = 0
    run_cost_latency_operations: list[dict[str, object]] = []
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
                    log_event(
                        logger,
                        logging.INFO,
                        "index.document",
                        pipeline_run_id=str(run.id),
                        knowledge_base=knowledge_base_name,
                        document_id=str(document.id),
                        document_version_id=str(version.id),
                        status="skipped",
                        skip_reason="empty_extracted_text",
                        version_number=version.version_number,
                    )
                    skipped_count += 1
                    continue

                if not force_reindex and _version_already_indexed(
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
                    log_event(
                        logger,
                        logging.INFO,
                        "index.document",
                        pipeline_run_id=str(run.id),
                        knowledge_base=knowledge_base_name,
                        document_id=str(document.id),
                        document_version_id=str(version.id),
                        status="skipped",
                        skip_reason="already_indexed",
                        version_number=version.version_number,
                    )
                    skipped_count += 1
                    continue

                document_cost_latency_operations: list[dict[str, object]] = []
                created_chunks, created_embeddings = _replace_version_index(
                    session,
                    document_version=version,
                    document=document,
                    chunking_config=chunking_config,
                    embedding_provider=embedding_provider,
                    chunk_profile_id=chunk_profile.profile_id,
                    embed_profile_id=embed_profile.profile_id,
                    cost_latency_operations=document_cost_latency_operations,
                    workspace_id=knowledge_base.workspace_id,
                    pii_redaction=pii_redaction,
                    embedding_batch_size=embedding_batch_size,
                )
                run_cost_latency_operations.extend(document_cost_latency_operations)
                chunk_count += created_chunks
                embedding_count += created_embeddings
                if vector_backend is not None:
                    _mirror_version_index(
                        session,
                        knowledge_base_name=knowledge_base_name,
                        knowledge_base_id=knowledge_base.id,
                        document_version=version,
                        embedding_provider=embedding_provider,
                        vector_backend=vector_backend,
                    )
                indexed_count += 1

                create_pipeline_run_item(
                    session,
                    pipeline_run_id=run.id,
                    document_id=document.id,
                    status="success",
                    metadata_json={
                        "chunk_count": created_chunks,
                        "cost_latency_summary": aggregate_cost_latency(
                            document_cost_latency_operations
                        ),
                        "document_version_id": str(version.id),
                        "embedding_dimensions": embedding_dimensions,
                        "version_number": version.version_number,
                    },
                )
                log_event(
                    logger,
                    logging.INFO,
                    "index.document",
                    pipeline_run_id=str(run.id),
                    knowledge_base=knowledge_base_name,
                    document_id=str(document.id),
                    document_version_id=str(version.id),
                    document_uri=document.uri,
                    status="success",
                    chunk_count=created_chunks,
                    embedding_count=created_embeddings,
                    version_number=version.version_number,
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
            log_event(
                logger,
                logging.ERROR,
                "index.document",
                pipeline_run_id=str(run.id),
                knowledge_base=knowledge_base_name,
                document_id=str(document.id),
                document_version_id=str(version.id),
                document_uri=document.uri,
                status="failed",
                error=str(exc),
                version_number=version.version_number,
            )

    run.total_items = len(versions)
    run.success_count = indexed_count
    run.failure_count = failed_count
    run.status = "completed_with_failures" if failed_count else "completed"
    run.finished_at = datetime.now(timezone.utc)
    run.config_snapshot_json = {
        **(run.config_snapshot_json or {}),
        "cost_latency_summary": {
            **aggregate_cost_latency(
                run_cost_latency_operations,
                total_latency_ms=(perf_counter() - run_started) * 1000,
            ),
            "operations": run_cost_latency_operations,
        },
    }
    session.commit()
    log_event(
        logger,
        logging.INFO,
        "index.knowledge_base.completed",
        pipeline_run_id=str(run.id),
        knowledge_base=knowledge_base_name,
        status=run.status,
        indexed_count=indexed_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        chunk_count=chunk_count,
        embedding_count=embedding_count,
        duration_ms=round((perf_counter() - run_started) * 1000, 3),
    )

    return IndexingReport(
        pipeline_run_id=run.id,
        indexed_count=indexed_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        chunk_count=chunk_count,
        embedding_count=embedding_count,
    )
