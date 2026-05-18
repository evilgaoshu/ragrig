"""Optional LLM-powered query rewriting for the retrieval phase.

Supports two modes:
- compress: shorten a long query to ≤ max_chars while preserving intent
- decompose: split a complex query into 2-5 focused sub-questions

All functions degrade gracefully — when the provider is None or the LLM
call fails, the original query is returned unchanged.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ragrig.providers import BaseProvider

logger = logging.getLogger(__name__)

_COMPRESS_PROMPT = (
    "Compress the following query to under {max_chars} characters while "
    "preserving its core intent. Reply with only the compressed query, "
    "no preamble or explanation.\n\nQuery:\n{query}"
)

_DECOMPOSE_PROMPT = (
    "Decompose the following complex query into 2 to 5 focused sub-questions "
    "that together cover the original intent. Reply with one sub-question per "
    "line, no numbering, no preamble.\n\nQuery:\n{query}"
)


@dataclass(frozen=True)
class RewriteConfig:
    """Configuration for query rewriting.

    Pass to search_knowledge_base() as ``rewrite_config``.
    When None (default), rewriting is disabled entirely.
    """

    provider_name: str
    model_name: str | None = None
    max_chars: int = 300
    decompose_threshold_chars: int = 300
    decompose_on_multi_question: bool = True


def rewrite_query(
    query: str,
    *,
    config: RewriteConfig | None,
    provider: "BaseProvider | None",
) -> list[str]:
    """Return a list of sub-queries derived from the original query.

    Returns ``[query]`` (unchanged) when:
    - config is None
    - provider is None
    - the query is short and single-question
    - the LLM call fails
    """
    if config is None or provider is None:
        return [query]

    needs_compress = len(query) > config.decompose_threshold_chars
    needs_decompose = config.decompose_on_multi_question and query.count("?") > 1

    if not needs_compress and not needs_decompose:
        return [query]

    if needs_decompose:
        return _decompose(query, provider=provider)

    # Compress only
    compressed = _compress(query, provider=provider, max_chars=config.max_chars)
    return [compressed]


def _compress(query: str, *, provider: "BaseProvider", max_chars: int) -> str:
    try:
        prompt = _COMPRESS_PROMPT.format(max_chars=max_chars, query=query)
        result = provider.generate(prompt).strip()
        return result if result else query
    except Exception:
        logger.debug("Query compression failed (non-fatal)", exc_info=True)
        return query


def _decompose(query: str, *, provider: "BaseProvider") -> list[str]:
    try:
        prompt = _DECOMPOSE_PROMPT.format(query=query)
        raw = provider.generate(prompt).strip()
        sub_queries = [line.strip() for line in raw.splitlines() if line.strip()]
        if not sub_queries:
            return [query]
        # Cap at 5 sub-questions to avoid fan-out explosion
        return sub_queries[:5]
    except Exception:
        logger.debug("Query decomposition failed (non-fatal)", exc_info=True)
        return [query]


def merge_retrieval_results(
    result_lists: list[list],
    top_k: int,
) -> list:
    """Deduplicate results from multiple sub-queries, keeping the highest score per chunk."""
    seen: dict = {}
    for results in result_lists:
        for r in results:
            chunk_id = r.chunk_id
            if chunk_id not in seen or r.score > seen[chunk_id].score:
                seen[chunk_id] = r

    merged = sorted(seen.values(), key=lambda x: -x.score)
    return merged[:top_k]


__all__ = ["RewriteConfig", "merge_retrieval_results", "rewrite_query"]
