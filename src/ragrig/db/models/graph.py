from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
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
    from ragrig.db.models.corpus import Chunk, Document, DocumentVersion, KnowledgeBase


class KnowledgeGraphEntity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Persistent KG-lite entity anchored to a knowledge base."""

    __tablename__ = "kg_entities"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_base_id",
            "canonical_name",
            name="uq_kg_entities_kb_canonical_name",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_kg_entities_confidence_range",
        ),
        Index("ix_kg_entities_kb_name", "knowledge_base_id", "canonical_name"),
        Index("ix_kg_entities_workspace_id", "workspace_id"),
    )

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )
    canonical_name: Mapped[str] = mapped_column(String(512), nullable=False)
    display_name: Mapped[str] = mapped_column(String(512), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False, default="TERM")
    description: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.6)
    extractor_version: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    knowledge_base: Mapped["KnowledgeBase"] = relationship()
    mentions: Mapped[list["KnowledgeGraphEntityMention"]] = relationship(
        back_populates="entity",
        cascade="all, delete-orphan",
    )


class KnowledgeGraphEntityMention(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A concrete source-chunk mention for a KG-lite entity."""

    __tablename__ = "kg_entity_mentions"
    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_kg_entity_mentions_confidence_range",
        ),
        Index("ix_kg_entity_mentions_entity_id", "entity_id"),
        Index("ix_kg_entity_mentions_chunk_id", "chunk_id"),
        Index("ix_kg_entity_mentions_document_id", "document_id"),
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kg_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chunks.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    mention_text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.6)
    extractor_version: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    entity: Mapped["KnowledgeGraphEntity"] = relationship(back_populates="mentions")
    chunk: Mapped["Chunk"] = relationship()
    document: Mapped["Document"] = relationship()
    document_version: Mapped["DocumentVersion"] = relationship()


class KnowledgeGraphRelation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A KG-lite relation between two entities with chunk-level evidence."""

    __tablename__ = "kg_relations"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_base_id",
            "subject_entity_id",
            "predicate",
            "object_entity_id",
            name="uq_kg_relations_kb_triplet",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_kg_relations_confidence_range",
        ),
        Index("ix_kg_relations_kb_predicate", "knowledge_base_id", "predicate"),
        Index("ix_kg_relations_subject_entity_id", "subject_entity_id"),
        Index("ix_kg_relations_object_entity_id", "object_entity_id"),
        Index("ix_kg_relations_workspace_id", "workspace_id"),
    )

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )
    subject_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kg_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    predicate: Mapped[str] = mapped_column(String(128), nullable=False)
    object_entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kg_entities.id", ondelete="CASCADE"),
        nullable=False,
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.6)
    extractor_version: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    knowledge_base: Mapped["KnowledgeBase"] = relationship()
    subject_entity: Mapped["KnowledgeGraphEntity"] = relationship(
        foreign_keys=[subject_entity_id],
    )
    object_entity: Mapped["KnowledgeGraphEntity"] = relationship(
        foreign_keys=[object_entity_id],
    )
    evidence: Mapped[list["KnowledgeGraphRelationEvidence"]] = relationship(
        back_populates="relation",
        cascade="all, delete-orphan",
    )


class KnowledgeGraphRelationEvidence(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A chunk that supports a KG-lite relation."""

    __tablename__ = "kg_relation_evidence"
    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_kg_relation_evidence_confidence_range",
        ),
        Index("ix_kg_relation_evidence_relation_id", "relation_id"),
        Index("ix_kg_relation_evidence_chunk_id", "chunk_id"),
    )

    relation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kg_relations.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chunks.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.6)
    extractor_version: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    relation: Mapped["KnowledgeGraphRelation"] = relationship(back_populates="evidence")
    chunk: Mapped["Chunk"] = relationship()
    document: Mapped["Document"] = relationship()
    document_version: Mapped["DocumentVersion"] = relationship()


class KnowledgeGraphClaim(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A source-backed claim extracted from a document or chunk."""

    __tablename__ = "kg_claims"
    __table_args__ = (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_kg_claims_confidence_range",
        ),
        Index("ix_kg_claims_knowledge_base_id", "knowledge_base_id"),
        Index("ix_kg_claims_source_chunk_id", "source_chunk_id"),
        Index("ix_kg_claims_workspace_id", "workspace_id"),
    )

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chunks.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.6)
    extractor_version: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    knowledge_base: Mapped["KnowledgeBase"] = relationship()
    source_chunk: Mapped["Chunk"] = relationship()
    document: Mapped["Document"] = relationship()
    document_version: Mapped["DocumentVersion"] = relationship()


class SemanticCacheEntry(UUIDPrimaryKeyMixin, Base):
    """Cached (query, answer) pair keyed by query embedding similarity.

    Entries are scoped to a knowledge base and optionally to a workspace.
    Expired entries (expires_at < now()) are ignored at lookup time.
    """

    __tablename__ = "semantic_cache"
    __table_args__ = (
        Index("ix_semantic_cache_kb_name", "knowledge_base_name"),
        Index("ix_semantic_cache_workspace_id", "workspace_id"),
        Index("ix_semantic_cache_expires_at", "expires_at"),
    )

    knowledge_base_name: Mapped[str] = mapped_column(Text, nullable=False)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(), nullable=True)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    citations_json: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConflictReview(Base):
    """Near-duplicate chunk conflict requiring human (or automated) resolution."""

    __tablename__ = "conflict_reviews"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'resolved_keep_new', 'resolved_keep_old', "
            "'resolved_keep_both', 'resolved_auto_recency')",
            name="ck_conflict_reviews_status",
        ),
        Index("ix_conflict_reviews_kb_status", "knowledge_base_id", "status"),
        Index("ix_conflict_reviews_new_chunk", "new_chunk_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False
    )
    new_chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False
    )
    existing_chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chunks.id", ondelete="CASCADE"), nullable=False
    )
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    resolution: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    knowledge_base: Mapped["KnowledgeBase"] = relationship()
    new_chunk: Mapped["Chunk"] = relationship(foreign_keys=[new_chunk_id])
    existing_chunk: Mapped["Chunk"] = relationship(foreign_keys=[existing_chunk_id])
