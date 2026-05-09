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
