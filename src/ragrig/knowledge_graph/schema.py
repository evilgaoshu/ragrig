from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class KnowledgeGraphBuildRequest(BaseModel):
    profile_id: str = "*.understand.default"
    extractor_version: str = "kg-lite-v1"
    reset: bool = True


class KnowledgeGraphStats(BaseModel):
    entity_count: int = 0
    mention_count: int = 0
    relation_count: int = 0
    relation_evidence_count: int = 0
    claim_count: int = 0
    source_chunk_count: int = 0
    document_count: int = 0
    graph_evidence_chunk_count: int = 0


class KnowledgeGraphMentionRecord(BaseModel):
    id: str
    chunk_id: str
    document_id: str
    document_version_id: str
    mention_text: str
    char_start: int | None = None
    char_end: int | None = None
    confidence: float
    text_preview: str
    document_uri: str


class KnowledgeGraphEntityRecord(BaseModel):
    id: str
    canonical_name: str
    display_name: str
    entity_type: str
    description: str | None = None
    confidence: float
    extractor_version: str
    mention_count: int = 0
    evidence_chunks: list[KnowledgeGraphMentionRecord] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeGraphRelationEvidenceRecord(BaseModel):
    id: str
    chunk_id: str
    document_id: str
    document_version_id: str
    evidence_text: str
    text_preview: str
    document_uri: str
    confidence: float


class KnowledgeGraphRelationRecord(BaseModel):
    id: str
    subject_entity_id: str
    subject: str
    predicate: str
    object_entity_id: str
    object: str
    confidence: float
    extractor_version: str
    evidence: list[KnowledgeGraphRelationEvidenceRecord] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeGraphClaimRecord(BaseModel):
    id: str
    claim_text: str
    confidence: float
    source_chunk_id: str
    document_id: str
    document_version_id: str
    document_uri: str
    text_preview: str
    extractor_version: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeGraphResult(BaseModel):
    schema_version: str = "1.0"
    status: str
    knowledge_base_id: str
    knowledge_base: str
    generated_from: str = "kg_lite_tables"
    stats: KnowledgeGraphStats
    entities: list[KnowledgeGraphEntityRecord] = Field(default_factory=list)
    relations: list[KnowledgeGraphRelationRecord] = Field(default_factory=list)
    claims: list[KnowledgeGraphClaimRecord] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    trace: dict[str, Any] = Field(default_factory=dict)


class GraphRetrievalContext(BaseModel):
    matched_entities: list[dict[str, Any]] = Field(default_factory=list)
    matched_relationships: list[dict[str, Any]] = Field(default_factory=list)
    expanded_entities: list[dict[str, Any]] = Field(default_factory=list)
    relation_paths: list[dict[str, Any]] = Field(default_factory=list)
    chunk_scores: dict[str, float] = Field(default_factory=dict)
    rank_movement: list[dict[str, Any]] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    degraded: bool = False
    degraded_reason: str = ""
