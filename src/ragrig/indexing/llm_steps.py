"""Optional LLM-powered pipeline steps for the indexing phase.

All functions in this module degrade gracefully when the provider is None
or when the LLM call fails — the pipeline always continues without raising.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ragrig.providers import BaseProvider

logger = logging.getLogger(__name__)

_SUMMARY_PROMPT = (
    "Write a concise summary (3-5 sentences) of the following document. "
    "Cover the main topic, key points, and any important conclusions. "
    "Reply with only the summary, no preamble or headings.\n\n"
    "Document:\n{text}"
)

_CONTEXT_PROMPT = (
    "<document>\n{doc_text}\n</document>\n\n"
    "Here is a chunk from the document above:\n"
    "<chunk>\n{chunk_text}\n</chunk>\n\n"
    "Give a short context (1-2 sentences) that situates this chunk within the "
    "document — describe what section it belongs to, what topic it covers, and "
    "how it relates to the document's overall content. "
    "Reply with only the context, no preamble or labels."
)

_DESCRIPTION_PROMPT = (
    "Summarize in one concise sentence what the following passage is about. "
    "Focus on the topic and key information, not the writing style. "
    "Reply with only the summary sentence, no preamble.\n\n"
    "Passage:\n{text}"
)


def generate_chunk_description(text: str, provider: "BaseProvider | None") -> str | None:
    """Call the LLM to produce a one-sentence semantic description for a chunk.

    Returns None on any failure so callers can safely ignore errors.
    """
    if provider is None:
        return None
    if not text.strip():
        return None
    try:
        prompt = _DESCRIPTION_PROMPT.format(text=text[:4000])
        description = provider.generate(prompt)
        return description.strip() or None
    except Exception:
        logger.debug("LLM description generation failed (non-fatal)", exc_info=True)
        return None


def generate_document_summary(text: str, provider: "BaseProvider | None") -> str | None:
    """Call the LLM to produce a 3-5 sentence summary for an entire document.

    Truncates input to 12 000 chars so very large documents don't exceed context.
    Returns None on any failure so callers can safely ignore errors.
    """
    if provider is None:
        return None
    if not text.strip():
        return None
    try:
        prompt = _SUMMARY_PROMPT.format(text=text[:12000])
        summary = provider.generate(prompt)
        return summary.strip() or None
    except Exception:
        logger.debug("LLM document summary generation failed (non-fatal)", exc_info=True)
        return None


def generate_chunk_context(
    doc_text: str,
    chunk_text: str,
    provider: "BaseProvider | None",
    *,
    max_doc_chars: int = 10_000,
) -> str | None:
    """Generate a short context sentence situating *chunk_text* within *doc_text*.

    The returned string is meant to be prepended to the chunk text before
    embedding so the embedding captures document-level context.  Returns None
    on any failure so the caller can fall back to embedding the plain chunk.
    """
    if provider is None:
        return None
    if not chunk_text.strip():
        return None
    try:
        prompt = _CONTEXT_PROMPT.format(
            doc_text=doc_text[:max_doc_chars],
            chunk_text=chunk_text[:2000],
        )
        context = provider.generate(prompt)
        return context.strip() or None
    except Exception:
        logger.debug("LLM chunk context generation failed (non-fatal)", exc_info=True)
        return None


def build_embedding_text(text: str, description: str | None) -> str:
    """Return the text to embed.

    When a description is available, prepend it so the embedding captures
    both the semantic label and the raw content.
    """
    if description:
        return f"{description}\n\n{text}"
    return text
