from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ragrig.db.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from ragrig.db.models.identity import KnowledgeBasePermission, Workspace
    from ragrig.db.models.pipeline import (
        DocumentUnderstanding,
        PipelineRun,
        PipelineRunItem,
        UnderstandingRun,
    )


class KnowledgeBase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_knowledge_bases_workspace_name"),
        Index("ix_knowledge_bases_workspace_id", "workspace_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    doc_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    workspace: Mapped["Workspace"] = relationship(back_populates="knowledge_bases")
    sources: Mapped[list["Source"]] = relationship(back_populates="knowledge_base")
    documents: Mapped[list["Document"]] = relationship(back_populates="knowledge_base")
    pipeline_runs: Mapped[list["PipelineRun"]] = relationship(back_populates="knowledge_base")
    understanding_runs: Mapped[list["UnderstandingRun"]] = relationship(
        back_populates="knowledge_base"
    )
    permissions: Mapped[list["KnowledgeBasePermission"]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan"
    )


class Source(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "uri", name="uq_sources_kb_uri"),
        UniqueConstraint("knowledge_base_id", "id", name="uq_sources_kb_id_id"),
    )

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="sources")
    documents: Mapped[list["Document"]] = relationship(
        back_populates="source", overlaps="documents,knowledge_base"
    )
    pipeline_runs: Mapped[list["PipelineRun"]] = relationship(
        back_populates="source", overlaps="knowledge_base,pipeline_runs"
    )


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["knowledge_base_id", "source_id"],
            ["sources.knowledge_base_id", "sources.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("knowledge_base_id", "uri", name="uq_documents_kb_uri"),
    )

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    knowledge_base: Mapped[KnowledgeBase] = relationship(
        back_populates="documents", overlaps="documents"
    )
    source: Mapped[Source] = relationship(
        back_populates="documents", overlaps="documents,knowledge_base"
    )
    versions: Mapped[list["DocumentVersion"]] = relationship(back_populates="document")
    pipeline_run_items: Mapped[list["PipelineRunItem"]] = relationship(back_populates="document")


class DocumentVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version_number", name="uq_document_versions_doc_version"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    parser_name: Mapped[str] = mapped_column(String(128), nullable=False)
    parser_config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    document: Mapped[Document] = relationship(back_populates="versions")
    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document_version")
    understandings: Mapped[list["DocumentUnderstanding"]] = relationship(
        back_populates="document_version"
    )


class Chunk(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_version_id", "chunk_index", name="uq_chunks_doc_version_index"),
        Index("ix_chunks_workspace_id", "workspace_id"),
    )

    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    llm_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_prefix: Mapped[str | None] = mapped_column(Text, nullable=True)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    page_number: Mapped[int | None] = mapped_column(Integer)
    heading: Mapped[str | None] = mapped_column(String(255))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    parent_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chunks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    document_version: Mapped[DocumentVersion] = relationship(back_populates="chunks")
    embeddings: Mapped[list["Embedding"]] = relationship(back_populates="chunk")
    children: Mapped[list["Chunk"]] = relationship(
        "Chunk", foreign_keys="Chunk.parent_chunk_id", back_populates="parent"
    )
    parent: Mapped["Chunk | None"] = relationship(
        "Chunk",
        foreign_keys="Chunk.parent_chunk_id",
        back_populates="children",
        remote_side="Chunk.id",
    )


class Embedding(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "embeddings"
    __table_args__ = (Index("ix_embeddings_workspace_id", "workspace_id"),)

    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chunks.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    chunk: Mapped[Chunk] = relationship(back_populates="embeddings")


class DocumentSummary(UUIDPrimaryKeyMixin, Base):
    """LLM-generated document-level summary with its embedding.

    One row per document version.  Used for document-level retrieval: broad or
    high-level queries that match a document as a whole but not any single chunk.
    """

    __tablename__ = "document_summaries"
    __table_args__ = (
        UniqueConstraint("document_version_id", name="uq_document_summaries_doc_version"),
        Index("ix_document_summaries_workspace_id", "workspace_id"),
    )

    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    document_version: Mapped["DocumentVersion"] = relationship()
