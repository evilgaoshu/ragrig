"""Reranking utilities for retrieval results.

Includes a fake reranker for testing and a provider-based reranker that
delegates to the provider registry.  When the real reranker is unavailable,
callers should degrade gracefully.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from ragrig.config import Settings, get_settings

PRODUCTION_APP_ENVS = {"prod", "production"}
DEFAULT_RERANKER_PROVIDER = "reranker.bge"


@dataclass(frozen=True)
class RerankCandidate:
    """A single candidate for reranking, carrying its original index."""

    document_id: uuid.UUID
    document_version_id: uuid.UUID
    chunk_id: uuid.UUID
    chunk_index: int
    document_uri: str
    source_uri: str | None
    text: str
    text_preview: str
    original_score: float
    original_index: int
    chunk_metadata: dict[str, Any]


@dataclass(frozen=True)
class RerankResult:
    """Result after reranking with new order and scores."""

    candidate: RerankCandidate
    rerank_score: float
    new_rank: int


def fake_rerank(query: str, candidates: list[RerankCandidate]) -> list[RerankResult]:
    """Deterministic fake reranker for CI and testing.

    Ranks candidates by a simple heuristic: documents whose text contains
    more query tokens rank higher.  The score is the ratio of matching
    query tokens to total query tokens.  This guarantees the order
    *often* differs from the original vector-only ranking, providing
    visible evidence that the rerank stage runs.

    The rerank is deterministic — no randomness involved.
    """
    import re

    query_tokens = set(re.findall(r"\w+", query.lower()))
    if not query_tokens:
        return [
            RerankResult(candidate=c, rerank_score=c.original_score, new_rank=i)
            for i, c in enumerate(candidates)
        ]

    scored = []
    for cand in candidates:
        text_tokens = set(re.findall(r"\w+", cand.text.lower()))
        match_ratio = len(query_tokens & text_tokens) / len(query_tokens)
        scored.append((match_ratio, cand))

    scored.sort(key=lambda x: (-x[0], x[1].original_index))

    results = []
    for new_rank, (rerank_score, cand) in enumerate(scored):
        results.append(
            RerankResult(
                candidate=cand,
                rerank_score=round(rerank_score, 6),
                new_rank=new_rank,
            )
        )
    return results


def fake_reranker_allowed(settings: Settings | None = None) -> bool:
    active_settings = settings or get_settings()
    if active_settings.ragrig_allow_fake_reranker:
        return True
    return active_settings.app_env.lower() not in PRODUCTION_APP_ENVS


def fake_reranker_policy(settings: Settings | None = None) -> dict[str, Any]:
    active_settings = settings or get_settings()
    allowed = fake_reranker_allowed(active_settings)
    explicit_override = active_settings.ragrig_allow_fake_reranker
    production_env = active_settings.app_env.lower() in PRODUCTION_APP_ENVS
    if explicit_override:
        status = "override_allowed"
        policy = "explicit_override"
        detail = "Fake reranker fallback is explicitly allowed by RAGRIG_ALLOW_FAKE_RERANKER."
    elif production_env:
        status = "blocked"
        policy = "production_requires_real_reranker"
        detail = (
            "Fake reranker fallback is disabled in production; configure a real reranker "
            "or set RAGRIG_ALLOW_FAKE_RERANKER=true."
        )
    else:
        status = "development_fallback_allowed"
        policy = "non_production_fallback"
        detail = "Fake reranker fallback is allowed outside production."
    return {
        "status": status,
        "provider": DEFAULT_RERANKER_PROVIDER,
        "fake_reranker_allowed": allowed,
        "policy": policy,
        "detail": detail,
        "app_env": active_settings.app_env,
    }


def provider_rerank(
    query: str,
    candidates: list[RerankCandidate],
    *,
    provider_name: str | None = None,
    model_name: str | None = None,
) -> list[RerankResult] | None:
    """Rerank using the provider registry.

    Returns None when the reranker provider is unavailable, signalling the
    caller to degrade.  Returns results list on success.
    """
    from ragrig.providers import ProviderError, get_provider_registry

    target_provider = provider_name or "reranker.bge"
    try:
        registry = get_provider_registry()
        config: dict[str, Any] = {}
        if provider_name is not None:
            config["provider"] = provider_name
        if model_name is not None:
            config["model_name"] = model_name
        provider = registry.get(target_provider, **config)
    except ProviderError:
        return None

    texts = [c.text for c in candidates]
    try:
        scored = provider.rerank(query, texts)
    except ProviderError:
        return None

    results = []
    for item in scored:
        idx = item.get("index", 0)
        score = float(item.get("score", 0.0))
        if 0 <= idx < len(candidates):
            results.append(
                RerankResult(
                    candidate=candidates[idx],
                    rerank_score=round(score, 6),
                    new_rank=len(results),
                )
            )

    if not results:
        return None

    results.sort(key=lambda r: -r.rerank_score)
    for i, r in enumerate(results):
        results[i] = RerankResult(
            candidate=r.candidate,
            rerank_score=r.rerank_score,
            new_rank=i,
        )

    return results


__all__ = [
    "DEFAULT_RERANKER_PROVIDER",
    "RerankCandidate",
    "RerankResult",
    "fake_rerank",
    "fake_reranker_allowed",
    "fake_reranker_policy",
    "provider_rerank",
]
