from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ragrig.providers import BaseProvider, ProviderCapability, ProviderError

DEFAULT_PROVIDER_PROMPT_VERSION = "graph-rag-provider-v1"


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
    canonical_name: str | None = None
    aliases: list[str] = field(default_factory=list)
    entity_type: str = "TERM"
    description: str | None = None
    confidence: float = 0.6
    evidence_text: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedRelationship:
    subject: str
    predicate: str
    object: str
    source_chunk_id: str
    claim: str | None = None
    confidence: float = 0.6
    evidence_text: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExtractedClaim:
    text: str
    source_chunk_id: str
    confidence: float = 0.6
    evidence_text: str | None = None
    char_start: int | None = None
    char_end: int | None = None
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


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _ProviderSpanModel(_StrictModel):
    source_chunk_id: str = Field(min_length=1)
    evidence_text: str | None = Field(default=None, max_length=2000)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_span(self) -> "_ProviderSpanModel":
        if (self.char_start is None) != (self.char_end is None):
            raise ValueError("char_start and char_end must be provided together")
        if self.char_start is not None and self.char_end is not None:
            if self.char_end <= self.char_start:
                raise ValueError("char_end must be greater than char_start")
        return self


class ProviderEntityModel(_ProviderSpanModel):
    name: str = Field(min_length=1, max_length=512)
    canonical_name: str | None = Field(default=None, max_length=512)
    aliases: list[str] = Field(default_factory=list, max_length=32)
    type: str = Field(default="TERM", min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=2000)
    confidence: float = Field(ge=0.0, le=1.0)


class ProviderRelationshipModel(_ProviderSpanModel):
    subject: str = Field(min_length=1, max_length=512)
    predicate: str = Field(min_length=1, max_length=128)
    object: str = Field(min_length=1, max_length=512)
    confidence: float = Field(ge=0.0, le=1.0)
    claim: str | None = Field(default=None, max_length=2000)
    extraction_reason: str | None = Field(default=None, max_length=500)


class ProviderClaimModel(_ProviderSpanModel):
    text: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0.0, le=1.0)


class ProviderKnowledgeGraphResponse(_StrictModel):
    entities: list[ProviderEntityModel] = Field(max_length=1000)
    relationships: list[ProviderRelationshipModel] = Field(max_length=1000)
    claims: list[ProviderClaimModel] = Field(max_length=1000)


class ProviderBackedKnowledgeGraphExtractor:
    """Strict source-backed extractor using an existing chat/generate provider."""

    name = "provider-backed"

    def __init__(
        self,
        provider: BaseProvider,
        *,
        provider_name: str,
        model: str | None = None,
        prompt_version: str = DEFAULT_PROVIDER_PROMPT_VERSION,
        max_source_chars: int = 12_000,
    ) -> None:
        if (
            ProviderCapability.CHAT not in provider.metadata.capabilities
            and ProviderCapability.GENERATE not in provider.metadata.capabilities
        ):
            raise ProviderError(
                f"Provider '{provider_name}' does not support chat/generate",
                code="unsupported_capability",
                retryable=False,
                details={"provider": provider_name},
            )
        self._provider = provider
        self.provider_name = provider_name
        self.model = model
        self.prompt_version = prompt_version
        self.max_source_chars = max_source_chars
        self.version = f"{prompt_version}:{provider_name}:{model or 'default'}"

    def extract(
        self,
        sources: list[KnowledgeGraphExtractionSource],
    ) -> KnowledgeGraphExtraction:
        source_by_id = {source.chunk_id: source for source in sources}
        prompt = _provider_prompt(sources, max_source_chars=self.max_source_chars)
        raw_text = self._generate(prompt)
        parsed = _parse_provider_response(raw_text)
        rejected: list[dict[str, str]] = []

        entities = [_entity_from_provider(item, source_by_id, rejected) for item in parsed.entities]
        relationships = [
            _relationship_from_provider(item, source_by_id, rejected)
            for item in parsed.relationships
        ]
        claims = [_claim_from_provider(item, source_by_id, rejected) for item in parsed.claims]
        return KnowledgeGraphExtraction(
            entities=[item for item in entities if item is not None],
            relationships=[item for item in relationships if item is not None],
            claims=[item for item in claims if item is not None],
            metadata={
                "source": "provider",
                "provider": self.provider_name,
                "model": self.model,
                "prompt_version": self.prompt_version,
                "response_fingerprint": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
                "rejected_item_count": len(rejected),
                "rejected_items": rejected[:20],
            },
        )

    def _generate(self, prompt: str) -> str:
        if ProviderCapability.CHAT in self._provider.metadata.capabilities:
            raw = self._provider.chat(
                [
                    {
                        "role": "system",
                        "content": "Return only valid JSON matching the supplied schema.",
                    },
                    {"role": "user", "content": prompt},
                ]
            )
            return _chat_content(raw)
        return self._provider.generate(prompt)


def _provider_prompt(
    sources: list[KnowledgeGraphExtractionSource], *, max_source_chars: int
) -> str:
    schema = ProviderKnowledgeGraphResponse.model_json_schema()
    source_payload = [
        {
            "source_chunk_id": source.chunk_id,
            "document_id": source.document_id,
            "document_version_id": source.document_version_id,
            "text": source.text[:max_source_chars],
        }
        for source in sources
    ]
    return (
        "Extract source-backed entities, aliases, typed relationships, and claims. "
        "Use explicit predicates such as depends_on, owns, routes_to, references, "
        "assigned_to, implements, or conflicts_with when supported by evidence. "
        "Every item must use one supplied source_chunk_id. Character spans are offsets "
        "inside that chunk text. Do not invent facts. Return only JSON.\n\n"
        f"JSON schema:\n{json.dumps(schema, ensure_ascii=True)}\n\n"
        f"Sources:\n{json.dumps(source_payload, ensure_ascii=True)}"
    )


def _parse_provider_response(raw_text: str) -> ProviderKnowledgeGraphResponse:
    content = raw_text.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    try:
        return ProviderKnowledgeGraphResponse.model_validate_json(content.strip())
    except (ValidationError, ValueError) as exc:
        raise ProviderError(
            f"Graph extractor returned invalid JSON/schema: {exc}",
            code="graph_extractor_schema_invalid",
            retryable=False,
            details={"response_fingerprint": hashlib.sha256(raw_text.encode("utf-8")).hexdigest()},
        ) from exc


def _chat_content(raw: dict[str, Any]) -> str:
    if not isinstance(raw, dict):
        raise ProviderError(
            "Graph extractor provider returned an invalid chat response",
            code="graph_extractor_response_invalid",
            retryable=False,
        )
    if "choices" in raw and raw["choices"]:
        return str(raw["choices"][0].get("message", {}).get("content", ""))
    if "response" in raw:
        return str(raw["response"])
    if "content" in raw:
        return str(raw["content"])
    return ""


def _validated_source(
    item: _ProviderSpanModel,
    source_by_id: dict[str, KnowledgeGraphExtractionSource],
    rejected: list[dict[str, str]],
    *,
    kind: str,
) -> KnowledgeGraphExtractionSource | None:
    source = source_by_id.get(item.source_chunk_id)
    if source is None:
        rejected.append({"kind": kind, "reason": "source_chunk_id_not_found"})
        return None
    if item.char_start is not None and item.char_end is not None:
        if item.char_end > len(source.text):
            rejected.append({"kind": kind, "reason": "evidence_span_out_of_bounds"})
            return None
    return source


def _evidence_metadata(item: _ProviderSpanModel) -> dict[str, Any]:
    return {
        "evidence_text": item.evidence_text,
        "evidence_char_start": item.char_start,
        "evidence_char_end": item.char_end,
    }


def _entity_from_provider(
    item: ProviderEntityModel,
    source_by_id: dict[str, KnowledgeGraphExtractionSource],
    rejected: list[dict[str, str]],
) -> ExtractedEntity | None:
    if _validated_source(item, source_by_id, rejected, kind="entity") is None:
        return None
    return ExtractedEntity(
        name=item.name,
        canonical_name=item.canonical_name,
        aliases=item.aliases,
        source_chunk_id=item.source_chunk_id,
        entity_type=item.type,
        description=item.description,
        confidence=item.confidence,
        evidence_text=item.evidence_text,
        char_start=item.char_start,
        char_end=item.char_end,
        metadata=_evidence_metadata(item),
    )


def _relationship_from_provider(
    item: ProviderRelationshipModel,
    source_by_id: dict[str, KnowledgeGraphExtractionSource],
    rejected: list[dict[str, str]],
) -> ExtractedRelationship | None:
    if _validated_source(item, source_by_id, rejected, kind="relationship") is None:
        return None
    return ExtractedRelationship(
        subject=item.subject,
        predicate=item.predicate,
        object=item.object,
        source_chunk_id=item.source_chunk_id,
        claim=item.claim,
        confidence=item.confidence,
        evidence_text=item.evidence_text,
        char_start=item.char_start,
        char_end=item.char_end,
        metadata={
            **_evidence_metadata(item),
            "extraction_reason": item.extraction_reason,
        },
    )


def _claim_from_provider(
    item: ProviderClaimModel,
    source_by_id: dict[str, KnowledgeGraphExtractionSource],
    rejected: list[dict[str, str]],
) -> ExtractedClaim | None:
    if _validated_source(item, source_by_id, rejected, kind="claim") is None:
        return None
    return ExtractedClaim(
        text=item.text,
        source_chunk_id=item.source_chunk_id,
        confidence=item.confidence,
        evidence_text=item.evidence_text,
        char_start=item.char_start,
        char_end=item.char_end,
        metadata=_evidence_metadata(item),
    )


__all__ = [
    "DEFAULT_PROVIDER_PROMPT_VERSION",
    "ExtractedClaim",
    "ExtractedEntity",
    "ExtractedRelationship",
    "KnowledgeGraphExtraction",
    "KnowledgeGraphExtractionSource",
    "KnowledgeGraphExtractor",
    "ProviderBackedKnowledgeGraphExtractor",
    "ProviderKnowledgeGraphResponse",
]
