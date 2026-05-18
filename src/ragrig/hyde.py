"""HyDE — Hypothetical Document Embeddings for improved retrieval recall.

Instead of embedding the raw query, an LLM generates a short hypothetical
passage that *would* answer the question. That passage is embedded and used
for retrieval (optionally blended with the original query embedding).

Hypothetical documents sit closer to real documents in embedding space, so
retrieval recall improves — especially for vague or short queries.

All functions degrade gracefully: when the provider is None or the LLM call
fails, ``generate_hypothetical_document`` returns None and the caller falls
back to the original query vector.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ragrig.providers import BaseProvider

logger = logging.getLogger(__name__)

_HYDE_PROMPT = (
    "Write a short, factual passage (2-4 sentences) that directly and "
    "completely answers the following question. Do not say you are answering "
    "a question — just write the passage as if it appeared in a document.\n\n"
    "Question: {query}\n\nPassage:"
)


@dataclass(frozen=True)
class HydeConfig:
    """Configuration for HyDE query transformation.

    Pass to ``search_knowledge_base()`` as ``hyde_config``.
    When None (default), HyDE is disabled and retrieval is unchanged.

    Attributes:
        provider_name: Name of the LLM provider used to generate the
            hypothetical document (e.g. ``"model.openai"``).
        blend: Controls how the final query vector is constructed.
            ``1.0`` → use only the hypothetical document embedding (pure HyDE).
            ``0.0`` → use only the original query embedding (no-op).
            ``0.5`` → weighted average, then L2-normalised.
            Defaults to ``1.0``.
    """

    provider_name: str
    blend: float = 1.0

    def __post_init__(self) -> None:
        if not (0.0 <= self.blend <= 1.0):
            raise ValueError(f"blend must be in [0, 1], got {self.blend}")


def generate_hypothetical_document(
    query: str,
    provider: "BaseProvider | None",
) -> str | None:
    """Ask the LLM to write a passage that would answer *query*.

    Returns the generated passage, or None on failure/no provider.
    """
    if provider is None:
        return None
    prompt = _HYDE_PROMPT.format(query=query)
    try:
        return provider.generate(prompt)
    except Exception:
        logger.debug("HyDE generation failed (non-fatal)", exc_info=True)
        return None


def blend_vectors(
    query_vec: list[float],
    hyde_vec: list[float],
    blend: float,
) -> list[float]:
    """Return ``(1 - blend) * query_vec + blend * hyde_vec``, L2-normalised.

    When ``blend`` is 0 or 1, returns the respective vector unchanged
    (no copy, no normalisation cost — the original is already unit-length
    from the embedding provider).
    """
    if blend == 0.0:
        return query_vec
    if blend == 1.0:
        return hyde_vec

    n = len(query_vec)
    blended = [(1.0 - blend) * query_vec[i] + blend * hyde_vec[i] for i in range(n)]
    norm = math.sqrt(sum(x * x for x in blended)) or 1.0
    return [x / norm for x in blended]
