from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TocEntry(BaseModel):
    level: int
    title: str
    anchor: str | None = None


class Entity(BaseModel):
    name: str
    type: str
    mentions: int = 0
    description: str | None = None


class KeyClaim(BaseModel):
    claim: str
    confidence: str = "medium"
    evidence_snippet: str | None = None


class SourceSpan(BaseModel):
    start: int
    end: int
    text: str | None = None


class UnderstandingResult(BaseModel):
    summary: str | None = None
    table_of_contents: list[TocEntry] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    key_claims: list[KeyClaim] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    source_spans: list[SourceSpan] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> "UnderstandingResult":
        if not isinstance(raw, dict):
            raw = {}
        return cls.model_validate(raw)


class UnderstandingRequest(BaseModel):
    provider: str = "deterministic-local"
    model: str | None = None
    profile_id: str = "*.understand.default"


class UnderstandingRecord(BaseModel):
    id: str
    document_version_id: str
    profile_id: str
    provider: str
    model: str
    input_hash: str
    status: str
    result: dict[str, Any]
    error: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class UnderstandAllRequest(BaseModel):
    provider: str = "deterministic-local"
    model: str | None = None
    profile_id: str = "*.understand.default"


class BatchUnderstandingError(BaseModel):
    version_id: str
    error: str


class BatchUnderstandingResult(BaseModel):
    total: int
    created: int
    skipped: int
    failed: int
    errors: list[BatchUnderstandingError] = Field(default_factory=list)


class CoverageErrorEntry(BaseModel):
    document_version_id: str
    profile_id: str
    provider: str
    error: str


class UnderstandingCoverage(BaseModel):
    total_versions: int
    completed: int
    missing: int
    stale: int
    failed: int
    completeness_score: float | None = None
    recent_errors: list[CoverageErrorEntry] = Field(default_factory=list)


class UnderstandingRunRecord(BaseModel):
    id: str
    knowledge_base_id: str
    provider: str
    model: str
    profile_id: str
    trigger_source: str
    operator: str | None = None
    status: str
    total: int
    created: int
    skipped: int
    failed: int
    error_summary: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


class UnderstandingRunFilter(BaseModel):
    provider: str | None = None
    model: str | None = None
    profile_id: str | None = None
    status: str | None = None
    started_after: str | None = None
    started_before: str | None = None
    limit: int = Field(default=50, ge=1, le=200)


class KnowledgeMapNode(BaseModel):
    id: str
    kind: str
    label: str
    document_id: str | None = None
    document_version_id: str | None = None
    uri: str | None = None
    entity_type: str | None = None
    entity_count: int | None = None
    mentions: int | None = None
    document_count: int | None = None
    topics: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeMapEdge(BaseModel):
    id: str
    source: str
    target: str
    relationship: str
    strength: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence: str | None = None
    shared_entities: list[str] = Field(default_factory=list)
    document_count: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeMapTopicCoverage(BaseModel):
    topic: str
    document_count: int
    coverage_pct: float
    document_ids: list[str] = Field(default_factory=list)


class KnowledgeMapStats(BaseModel):
    total_versions: int
    completed: int
    missing: int
    stale: int
    failed: int
    included_documents: int
    document_nodes: int
    entity_nodes: int
    document_relationship_edges: int
    mention_edges: int
    co_mention_edges: int
    cross_document_entity_count: int
    isolated_document_count: int


class KnowledgeMapResult(BaseModel):
    schema_version: str = "1.0"
    generated_at: str
    knowledge_base_id: str
    knowledge_base: str | None = None
    profile_id: str
    status: str
    nodes: list[KnowledgeMapNode] = Field(default_factory=list)
    edges: list[KnowledgeMapEdge] = Field(default_factory=list)
    topic_coverage: list[KnowledgeMapTopicCoverage] = Field(default_factory=list)
    stats: KnowledgeMapStats
    limitations: list[str] = Field(default_factory=list)
