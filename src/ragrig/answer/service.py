"""Answer generation service — orchestrates retrieval + LLM generation.

The core pipeline:
1. Retrieve evidence chunks via existing retrieval path (ACL-aware)
2. If no evidence → refuse to answer
3. Build citations with safe metadata
4. Call answer provider (deterministic or LLM)
5. Validate returned citation IDs against evidence
6. Return structured AnswerReport
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ragrig.answer.provider import get_answer_provider
from ragrig.answer.schema import (
    AnswerGenerationError,
    AnswerReport,
    Citation,
    EvidenceChunk,
    GroundingStatus,
    NoEvidenceError,
    ProviderUnavailableError,
)
from ragrig.retrieval import (
    search_knowledge_base,
)
from ragrig.vectorstore.base import VectorBackend


def _build_citations(evidence: list[EvidenceChunk]) -> list[Citation]:
    """Build citation objects from evidence chunks with safe metadata only."""
    citations: list[Citation] = []
    for chunk in evidence:
        safe_metadata: dict[str, Any] = {}

        citations.append(
            Citation(
                citation_id=chunk.citation_id,
                document_uri=chunk.document_uri,
                chunk_id=chunk.chunk_id,
                chunk_index=chunk.chunk_index,
                text_preview=chunk.text[:160],
                score=chunk.score,
                metadata_summary=safe_metadata,
            )
        )
    return citations


def _build_retrieval_trace(report: Any) -> dict[str, Any]:
    """Build a safe retrieval trace without leaking secrets or full text."""
    return {
        "knowledge_base": report.knowledge_base,
        "query": report.query,
        "top_k": report.top_k,
        "provider": report.provider,
        "model": report.model,
        "dimensions": report.dimensions,
        "distance_metric": report.distance_metric,
        "backend": report.backend,
        "total_results": report.total_results,
        "acl_explain": report.acl_explain,
    }


def _sanitize_error_message(exc: Exception) -> str:
    """Return a safe error message — never leak raw provider keys or full prompts."""
    import re

    msg = str(exc)
    # Redact common secret patterns
    msg = re.sub(r"api_key[=:]\s*\S+", "api_key=[REDACTED]", msg, flags=re.IGNORECASE)
    msg = re.sub(r"secret[=:]\s*\S+", "secret=[REDACTED]", msg, flags=re.IGNORECASE)
    msg = re.sub(r"token[=:]\s*\S+", "token=[REDACTED]", msg, flags=re.IGNORECASE)
    msg = re.sub(r"password[=:]\s*\S+", "password=[REDACTED]", msg, flags=re.IGNORECASE)
    msg = re.sub(r"sk-[a-zA-Z0-9_-]+", "sk-[REDACTED]", msg)
    # Limit error message length to avoid leaking context
    if len(msg) > 500:
        msg = msg[:497] + "..."
    return msg


def generate_answer(
    session: Session,
    *,
    knowledge_base_name: str,
    query: str,
    top_k: int = 5,
    provider: str = "deterministic-local",
    model: str | None = None,
    provider_config: dict[str, Any] | None = None,
    answer_provider: str | None = None,
    answer_model: str | None = None,
    answer_provider_config: dict[str, Any] | None = None,
    dimensions: int | None = None,
    vector_backend: VectorBackend | None = None,
    principal_ids: list[str] | None = None,
    enforce_acl: bool = True,
) -> AnswerReport:
    """Generate a grounded answer from an evidence-grounded retrieval.

    The pipeline:
    1. Search the knowledge base (ACL-aware)
    2. If no results → refuse
    3. Build evidence chunks with citation IDs
    4. Call answer provider
    5. Validate and return structured report

    Raises:
        NoEvidenceError: No retrievable chunks for the query
        ProviderUnavailableError: Answer provider could not generate
    """
    # 1. Retrieval
    retrieval_report = search_knowledge_base(
        session=session,
        knowledge_base_name=knowledge_base_name,
        query=query,
        top_k=top_k,
        provider=provider,
        model=model,
        dimensions=dimensions,
        vector_backend=vector_backend,
        principal_ids=principal_ids,
        enforce_acl=enforce_acl,
    )

    # 2. No evidence → refuse
    if retrieval_report.total_results == 0:
        raise NoEvidenceError(knowledge_base=knowledge_base_name, query=query)

    # 3. Build evidence chunks with stable citation IDs
    evidence: list[EvidenceChunk] = []
    for i, result in enumerate(retrieval_report.results):
        evidence.append(
            EvidenceChunk(
                citation_id=f"cit-{i + 1}",
                document_uri=result.document_uri,
                chunk_id=str(result.chunk_id),
                chunk_index=result.chunk_index,
                text=result.text,
                score=result.score,
                distance=result.distance,
            )
        )

    # 4. Call answer provider
    resolved_answer_provider = answer_provider or provider
    resolved_answer_model = answer_model if answer_model is not None else model
    resolved_answer_config = (
        answer_provider_config if answer_provider_config is not None else provider_config
    )
    try:
        if resolved_answer_config is None:
            answer_provider_obj = get_answer_provider(
                resolved_answer_provider,
                model=resolved_answer_model,
            )
        else:
            answer_provider_obj = get_answer_provider(
                resolved_answer_provider,
                model=resolved_answer_model,
                provider_config=resolved_answer_config,
            )
        answer_text, citation_ids_used = answer_provider_obj.generate(
            query=query, evidence=evidence
        )
    except Exception as exc:
        reason = _sanitize_error_message(exc)
        raise ProviderUnavailableError(
            provider=resolved_answer_provider,
            reason=reason,
        ) from exc

    # 5. Validate citation IDs — provider must only reference existing evidence
    valid_citation_ids = {chunk.citation_id for chunk in evidence}
    invalid_citations = [cid for cid in citation_ids_used if cid not in valid_citation_ids]
    if invalid_citations:
        grounding_status: GroundingStatus = "degraded"
        refusal_reason: str | None = (
            f"Answer references non-existent citations: {', '.join(invalid_citations)}"
        )
    elif not citation_ids_used:
        grounding_status = "degraded"
        refusal_reason = "Answer contains no citations — grounding cannot be verified."
    else:
        grounding_status = "grounded"
        refusal_reason = None

    # Build citations (only for evidence actually cited)
    cited_evidence = [chunk for chunk in evidence if chunk.citation_id in citation_ids_used]
    citations = _build_citations(cited_evidence)

    retrieval_trace = _build_retrieval_trace(retrieval_report)

    return AnswerReport(
        answer=answer_text,
        citations=citations,
        evidence_chunks=evidence,
        model=resolved_answer_model or retrieval_report.model,
        provider=resolved_answer_provider,
        retrieval_trace=retrieval_trace,
        grounding_status=grounding_status,
        refusal_reason=refusal_reason,
    )


__all__ = [
    "AnswerGenerationError",
    "NoEvidenceError",
    "ProviderUnavailableError",
    "generate_answer",
]
