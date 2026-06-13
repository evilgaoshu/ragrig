"""Faithfulness / hallucination detection for generated answers.

After an LLM produces an answer from retrieved evidence, this module checks
whether every claim in the answer is actually supported by the source passages.

The check is performed by a second LLM call (may be a cheaper model).  It is
entirely optional — when ``faithfulness_config`` is None or the LLM call fails,
the pipeline continues unchanged and ``faithfulness_score`` is left as None.

Score interpretation
--------------------
The LLM rates support on a 1-5 scale:
  5 → all claims directly supported  (score ≥ 0.8 → faithful)
  4 → mostly supported, minor gaps   (score ≥ 0.8 → faithful)
  3 → partially supported            (score < 0.8 → unfaithful)
  2 → mostly unsupported
  1 → not supported / hallucinated

``is_faithful = score >= threshold`` (default threshold = 0.6, i.e. ≥ 3/5).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ragrig.providers import BaseProvider

logger = logging.getLogger(__name__)

_FAITHFULNESS_PROMPT = """\
You are an impartial judge evaluating whether an AI-generated answer is \
supported by the provided source passages.

Question: {query}

Source passages:
{context}

Generated answer:
{answer}

Task: Rate how faithfully the answer is supported by the source passages on a \
scale of 1 to 5, where:
  5 = all claims are directly supported by the passages
  4 = mostly supported; minor details may be inferred but not invented
  3 = partially supported; some claims are present, others are not
  2 = mostly unsupported; the answer adds significant information not in passages
  1 = not supported at all / hallucinated content

Reply in this exact format:
SCORE: <1-5>
REASON: <one concise sentence explaining the rating>"""


@dataclass(frozen=True)
class FaithfulnessConfig:
    """Configuration for the faithfulness check step.

    Attributes:
        provider_name: Name of the LLM provider used for the faithfulness judge
            (can be a cheaper/faster model than the answer provider).
        threshold: Minimum normalised score (0-1) to be considered faithful.
            Default 0.6 corresponds to a raw score of ≥ 3/5.
        max_context_chars: Maximum total characters of evidence passed to the
            judge to avoid exceeding context limits.
    """

    provider_name: str
    model_name: str | None = None
    provider_config: dict[str, Any] | None = None
    threshold: float = 0.6
    max_context_chars: int = 6000

    def __post_init__(self) -> None:
        if not (0.0 < self.threshold <= 1.0):
            raise ValueError(f"threshold must be in (0, 1], got {self.threshold}")


@dataclass(frozen=True)
class FaithfulnessResult:
    """Result of a faithfulness check."""

    score: float  # normalised to [0, 1]
    is_faithful: bool
    reason: str | None
    raw_score: int  # 1-5 as returned by the LLM


def _parse_response(response: str) -> tuple[int, str | None]:
    """Extract (raw_score, reason) from the LLM reply.

    Returns (0, None) if parsing fails.
    """
    score_match = re.search(r"SCORE\s*:\s*([1-5])", response, re.IGNORECASE)
    reason_match = re.search(r"REASON\s*:\s*(.+)", response, re.IGNORECASE)
    if not score_match:
        return 0, None
    raw_score = int(score_match.group(1))
    reason = reason_match.group(1).strip() if reason_match else None
    return raw_score, reason


def check_faithfulness(
    *,
    query: str,
    answer: str,
    context_passages: list[str],
    config: FaithfulnessConfig,
    provider: "BaseProvider | None",
) -> FaithfulnessResult | None:
    """Run faithfulness check using an LLM judge.

    Returns None on any failure so callers can safely ignore errors.
    """
    if provider is None:
        return None
    if not answer.strip() or not context_passages:
        return None

    # Truncate and join context passages
    context = ""
    for i, passage in enumerate(context_passages, 1):
        entry = f"[{i}] {passage}\n"
        if len(context) + len(entry) > config.max_context_chars:
            break
        context += entry

    prompt = _FAITHFULNESS_PROMPT.format(
        query=query,
        context=context.strip(),
        answer=answer,
    )
    try:
        response = provider.generate(prompt)
        raw_score, reason = _parse_response(response)
        if raw_score == 0:
            logger.debug("Faithfulness response could not be parsed: %r", response[:200])
            return None
        normalised = round((raw_score - 1) / 4, 4)  # map 1-5 → 0.0-1.0
        return FaithfulnessResult(
            score=normalised,
            is_faithful=normalised >= config.threshold,
            reason=reason,
            raw_score=raw_score,
        )
    except Exception:
        logger.debug("Faithfulness check failed (non-fatal)", exc_info=True)
        return None
