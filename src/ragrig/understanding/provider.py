from __future__ import annotations

import hashlib
import json
from typing import Any

from ragrig.providers import BaseProvider, ProviderCapability, ProviderError
from ragrig.understanding.schema import (
    Entity,
    KeyClaim,
    TocEntry,
    UnderstandingResult,
)

DEFAULT_SYSTEM_PROMPT = (
    "You are a document analysis engine. Extract structured understanding from the text. "
    "Return ONLY valid JSON matching this schema:\n"
    "{\n"
    '  "summary": "string",\n'
    '  "table_of_contents": [{"level": int, "title": "string", "anchor": "string|null"}],\n'
    '  "entities": [{"name": "string", "type": "string", "mentions": int, '
    '"description": "string|null"}],\n'
    '  "key_claims": [{"claim": "string", "confidence": "string", '
    '"evidence_snippet": "string|null"}],\n'
    '  "limitations": ["string"],\n'
    '  "source_spans": [{"start": int, "end": int, "text": "string|null"}]\n'
    "}"
)


def compute_input_hash(text: str, profile_id: str, provider: str, model: str) -> str:
    payload = f"{profile_id}:{provider}:{model}:{text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class UnderstandingProvider:
    def generate(self, text: str, *, system_prompt: str | None = None) -> UnderstandingResult:
        raise NotImplementedError


class DeterministicUnderstandingProvider(UnderstandingProvider):
    """Deterministic provider for CI/testing that produces structured output from text hashes."""

    def generate(self, text: str, *, system_prompt: str | None = None) -> UnderstandingResult:
        del system_prompt
        if not text.strip():
            return UnderstandingResult(
                summary="",
                table_of_contents=[],
                entities=[],
                key_claims=[],
                limitations=["Empty input text: no content to analyze."],
                source_spans=[],
            )

        lines = text.splitlines()
        headings = []
        for _i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("# "):
                headings.append(TocEntry(level=1, title=stripped[2:].strip(), anchor=None))
            elif stripped.startswith("## "):
                headings.append(TocEntry(level=2, title=stripped[3:].strip(), anchor=None))
            elif stripped.startswith("### "):
                headings.append(TocEntry(level=3, title=stripped[4:].strip(), anchor=None))

        if not headings:
            headings = [TocEntry(level=1, title="Content", anchor=None)]

        word_count = len(text.split())
        summary = f"Deterministic summary: {word_count} words, {len(lines)} lines."

        # Extract capitalized words as fake entities
        entities: list[Entity] = []
        seen: set[str] = set()
        for word in text.split():
            raw = word.strip(".,;:!?()[]{}\"'")
            clean = raw.lower()
            if len(clean) >= 4 and raw[0].isupper() and clean not in seen:
                seen.add(clean)
                entities.append(Entity(name=raw, type="TERM", mentions=1))
            if len(entities) >= 5:
                break

        key_claims = [
            KeyClaim(
                claim="Document contains structured or semi-structured text.",
                confidence="medium",
            )
        ]
        limitations: list[str] = []
        if word_count < 20:
            limitations.append("Very short document; summary quality may be limited.")

        return UnderstandingResult(
            summary=summary,
            table_of_contents=headings,
            entities=entities,
            key_claims=key_claims,
            limitations=limitations,
            source_spans=[],
        )


class LLMUnderstandingProvider(UnderstandingProvider):
    """Wrapper around a BaseProvider with chat/generate capability."""

    def __init__(self, provider: BaseProvider, model: str | None = None) -> None:
        self._provider = provider
        self._model = model

    def generate(self, text: str, *, system_prompt: str | None = None) -> UnderstandingResult:
        prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ]
        try:
            raw = self._provider.chat(messages)
        except ProviderError:
            raw_text = self._provider.generate(
                f"{prompt}\n\nDocument text:\n{text}"
            )
            raw = {"choices": [{"message": {"content": raw_text}}]}

        content = ""
        if isinstance(raw, dict):
            if "choices" in raw and raw["choices"]:
                content = str(raw["choices"][0].get("message", {}).get("content", ""))
            elif "response" in raw:
                content = str(raw["response"])
            elif "content" in raw:
                content = str(raw["content"])
        content = content.strip()

        # Try to extract JSON from markdown code blocks
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        try:
            parsed: dict[str, Any] = json.loads(content) if content else {}
        except json.JSONDecodeError as exc:
            raise ProviderError(
                f"LLM returned invalid JSON: {exc}",
                code="understanding_schema_invalid",
                retryable=False,
                details={"content_preview": content[:200]},
            ) from exc

        return UnderstandingResult.from_raw(parsed)


def get_understanding_provider(
    provider_name: str, model: str | None = None
) -> UnderstandingProvider:
    if provider_name == "deterministic-local":
        return DeterministicUnderstandingProvider()

    from ragrig.providers import get_provider_registry

    registry = get_provider_registry()
    base = registry.get(provider_name)
    if ProviderCapability.CHAT not in base.metadata.capabilities and (
        ProviderCapability.GENERATE not in base.metadata.capabilities
    ):
        raise ProviderError(
            f"Provider '{provider_name}' does not support chat/generate",
            code="unsupported_capability",
            retryable=False,
            details={"provider": provider_name},
        )
    return LLMUnderstandingProvider(base, model=model)
