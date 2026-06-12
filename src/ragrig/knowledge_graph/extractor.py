from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class KnowledgeGraphExtractionSource:
    chunk_id: str
    document_id: str
    document_version_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedEntity:
    name: str
    source_chunk_id: str
    entity_type: str = "TERM"
    description: str | None = None
    confidence: float = 0.6
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedRelationship:
    subject: str
    predicate: str
    object: str
    source_chunk_id: str
    claim: str | None = None
    confidence: float = 0.6
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedClaim:
    text: str
    source_chunk_id: str
    confidence: float = 0.6
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class KnowledgeGraphExtraction:
    entities: list[ExtractedEntity] = field(default_factory=list)
    relationships: list[ExtractedRelationship] = field(default_factory=list)
    claims: list[ExtractedClaim] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class KnowledgeGraphExtractor(Protocol):
    """Provider seam for source-backed entity, relationship, and claim extraction."""

    name: str
    version: str

    def extract(
        self,
        sources: list[KnowledgeGraphExtractionSource],
    ) -> KnowledgeGraphExtraction: ...


__all__ = [
    "ExtractedClaim",
    "ExtractedEntity",
    "ExtractedRelationship",
    "KnowledgeGraphExtraction",
    "KnowledgeGraphExtractionSource",
    "KnowledgeGraphExtractor",
]
