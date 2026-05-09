"""Answer generation providers — deterministic and LLM-backed.

Provides fake/deterministic providers for CI/testing and wrappers around
the provider registry for live LLM use.
"""

from __future__ import annotations

from typing import Any

from ragrig.answer.schema import EvidenceChunk
from ragrig.providers import BaseProvider, ProviderCapability


class AnswerProvider:
    """Interface for answer generation providers."""

    def generate(self, query: str, evidence: list[EvidenceChunk]) -> tuple[str, list[str]]:
        """Generate an answer from query and evidence chunks.

        Returns (answer_text, citation_ids_used).
        """
        raise NotImplementedError


class DeterministicAnswerProvider(AnswerProvider):
    """Deterministic provider for CI/testing.

    Generates structured answers that reference evidence by citation ID.
    When no evidence is provided, returns a refusal.
    """

    def generate(self, query: str, evidence: list[EvidenceChunk]) -> tuple[str, list[str]]:
        if not evidence:
            return (
                "I cannot answer this question because no relevant evidence was found "
                "in the knowledge base.",
                [],
            )

        used_ids: list[str] = []
        summary_parts: list[str] = []

        for _i, chunk in enumerate(evidence):
            cid = chunk.citation_id
            used_ids.append(cid)
            snippet = chunk.text[:120].strip()
            if len(chunk.text) > 120:
                snippet += "..."
            summary_parts.append(f"Source [{cid}]: {snippet}")

        summary_text = "\n".join(summary_parts)

        answer = (
            f"Based on the provided evidence, here is the answer to '{query}':\n\n"
            f"{summary_text}\n\n"
            f"This answer is grounded in {len(evidence)} evidence chunk(s)."
        )
        return answer, used_ids


class LLMAnswerProvider(AnswerProvider):
    """Wrapper around a BaseProvider with chat/generate capability for answer generation."""

    def __init__(self, provider: BaseProvider, model: str | None = None) -> None:
        self._provider = provider
        self._model = model

    def generate(self, query: str, evidence: list[EvidenceChunk]) -> tuple[str, list[str]]:
        """Use LLM to generate a grounded answer with citation references."""
        if not evidence:
            return (
                "I cannot answer this question because no relevant evidence was found "
                "in the knowledge base.",
                [],
            )

        evidence_blocks: list[str] = []
        for chunk in evidence:
            evidence_blocks.append(
                f"[{chunk.citation_id}] (source: {chunk.document_uri}, "
                f"relevance: {chunk.score:.2f}):\n{chunk.text}"
            )

        evidence_text = "\n\n".join(evidence_blocks)

        system_prompt = (
            "You are a precise, evidence-grounded answer engine. "
            "Answer ONLY using the provided evidence. "
            "Reference sources using their citation IDs in square brackets, e.g. [cit-1]. "
            "If the evidence is insufficient, state clearly that you cannot answer. "
            "Never fabricate information or use knowledge outside the provided evidence."
        )

        user_prompt = (
            f"Question: {query}\n\n"
            f"Evidence:\n{evidence_text}\n\n"
            f"Provide a grounded answer using the evidence above. "
            f"Always cite sources with their citation IDs."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            raw = self._provider.chat(messages)
        except Exception:
            try:
                raw_text = self._provider.generate(f"{system_prompt}\n\n{user_prompt}")
                raw = {"choices": [{"message": {"content": raw_text}}]}
            except Exception as exc:
                from ragrig.providers import ProviderError

                raise ProviderError(
                    f"Answer generation failed: {exc}",
                    code="answer_generation_failed",
                    retryable=False,
                    details={"error": str(exc)},
                ) from exc

        content = self._extract_content(raw)
        used_ids = self._extract_citation_ids(content)
        return content, used_ids

    @staticmethod
    def _extract_content(raw: dict[str, Any]) -> str:
        if "choices" in raw and raw["choices"]:
            return str(raw["choices"][0].get("message", {}).get("content", ""))
        if "response" in raw:
            return str(raw["response"])
        if "content" in raw:
            return str(raw["content"])
        return ""

    @staticmethod
    def _extract_citation_ids(text: str) -> list[str]:
        """Extract citation IDs from answer text (e.g., [cit-1], [cit-2])."""
        import re

        pattern = r"\[(cit-\d+)\]"
        matches = re.findall(pattern, text)
        seen: set[str] = set()
        result: list[str] = []
        for m in matches:
            if m not in seen:
                seen.add(m)
                result.append(m)
        return result


def get_answer_provider(provider_name: str, model: str | None = None) -> AnswerProvider:
    """Factory to resolve an answer provider by name.

    'deterministic-local' returns a DeterministicAnswerProvider.
    Any other name is resolved through the provider registry and wrapped
    in an LLMAnswerProvider.
    """
    if provider_name == "deterministic-local":
        return DeterministicAnswerProvider()

    from ragrig.providers import get_provider_registry

    registry = get_provider_registry()
    base = registry.get(provider_name)

    capabilities = base.metadata.capabilities
    if (
        ProviderCapability.CHAT not in capabilities
        and ProviderCapability.GENERATE not in capabilities
    ):
        from ragrig.providers import ProviderError

        raise ProviderError(
            f"Provider '{provider_name}' does not support chat/generate",
            code="unsupported_capability",
            retryable=False,
            details={"provider": provider_name},
        )

    return LLMAnswerProvider(base, model=model)


# Re-export
__all__ = [
    "AnswerProvider",
    "DeterministicAnswerProvider",
    "LLMAnswerProvider",
    "get_answer_provider",
]
