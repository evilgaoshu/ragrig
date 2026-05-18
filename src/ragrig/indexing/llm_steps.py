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


def build_embedding_text(text: str, description: str | None) -> str:
    """Return the text to embed.

    When a description is available, prepend it so the embedding captures
    both the semantic label and the raw content.
    """
    if description:
        return f"{description}\n\n{text}"
    return text
