"""Answer generation schema — dataclasses for the answer generation pipeline.

Defines the canonical types for answer requests, responses, citations, and
grounding status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

GroundingStatus = Literal["grounded", "refused", "degraded", "error"]


@dataclass(frozen=True)
class Citation:
    """A citation linking a generated answer to an evidence chunk.

    Only safe metadata is exposed — never raw secrets or full ACL lists.
    """

    citation_id: str
    document_uri: str
    chunk_id: str
    chunk_index: int
    text_preview: str
    score: float
    metadata_summary: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EvidenceChunk:
    """A single piece of evidence used in answer generation."""

    citation_id: str
    document_uri: str
    chunk_id: str
    chunk_index: int
    text: str
    score: float
    distance: float


@dataclass(frozen=True)
class AnswerReport:
    """Structured payload returned by the answer generation API."""

    answer: str
    citations: list[Citation]
    evidence_chunks: list[EvidenceChunk]
    model: str
    provider: str
    retrieval_trace: dict[str, Any]
    grounding_status: GroundingStatus
    refusal_reason: str | None = None


class AnswerGenerationError(RuntimeError):
    """Base error for answer generation failures."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class NoEvidenceError(AnswerGenerationError):
    """No evidence found after retrieval — cannot ground an answer."""

    def __init__(self, knowledge_base: str, query: str) -> None:
        super().__init__(
            f"No evidence found in '{knowledge_base}' for query: {query}",
            code="no_evidence",
            details={"knowledge_base": knowledge_base, "query": query},
        )


class ProviderUnavailableError(AnswerGenerationError):
    """Answer provider is not available."""

    def __init__(self, provider: str, reason: str) -> None:
        super().__init__(
            f"Answer provider '{provider}' is unavailable: {reason}",
            code="provider_unavailable",
            details={"provider": provider, "reason": reason},
        )
