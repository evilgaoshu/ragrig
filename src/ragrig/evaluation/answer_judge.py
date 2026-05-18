"""LLM-as-judge scoring for RAG answer quality.

Two metrics are computed by an LLM judge:

* **Answer correctness** — when a ground-truth reference answer is available,
  the judge rates how well the generated answer captures the key information.
* **Answer relevance** — the judge rates whether the generated answer actually
  addresses the question, regardless of a reference answer.

Both use a 1-5 scale normalised to [0, 1] as ``(raw - 1) / 4``.  All
functions degrade gracefully: None is returned on any LLM failure so that
evaluation runs complete even when the judge provider is unavailable.

Context-based metrics (no LLM required):

* **Context precision** — proportion of retrieved chunks that contain at
  least one expected citation or relevant text fragment.
* **Context recall** — proportion of expected relevant fragments found in
  the retrieved chunks.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ragrig.providers import BaseProvider

logger = logging.getLogger(__name__)

_CORRECTNESS_PROMPT = """\
You are an impartial judge evaluating the quality of an AI-generated answer \
compared to a reference answer.

Question: {query}

Reference answer:
{expected}

Generated answer:
{generated}

Task: Rate how well the generated answer captures the key information in the \
reference answer on a scale of 1 to 5, where:
  5 = all key information present, no important omissions or errors
  4 = most key information present, minor gaps only
  3 = partially correct; some key information present, some missing
  2 = mostly incorrect or missing; little overlap with reference
  1 = completely wrong or unrelated to the reference

Reply in this exact format (no other text):
SCORE: <1-5>
REASON: <one sentence>"""

_RELEVANCE_PROMPT = """\
You are an impartial judge evaluating whether an AI-generated answer \
addresses the question asked.

Question: {query}

Generated answer:
{generated}

Task: Rate how well the answer addresses the question on a scale of 1 to 5, \
where:
  5 = directly and completely addresses the question
  4 = mostly addresses the question with minor gaps
  3 = partially addresses the question
  2 = tangentially related but does not answer the question
  1 = does not address the question at all

Reply in this exact format (no other text):
SCORE: <1-5>
REASON: <one sentence>"""

_SCORE_RE = re.compile(r"SCORE:\s*([1-5])", re.IGNORECASE)
_REASON_RE = re.compile(r"REASON:\s*(.+)", re.IGNORECASE)


def _parse_judge_response(response: str) -> tuple[int, str | None]:
    """Extract (raw_score, reason) from judge LLM output. Returns (0, None) on failure."""
    score_match = _SCORE_RE.search(response)
    if not score_match:
        return 0, None
    raw = int(score_match.group(1))
    reason_match = _REASON_RE.search(response)
    reason = reason_match.group(1).strip() if reason_match else None
    return raw, reason


def score_answer_correctness(
    *,
    query: str,
    generated_answer: str,
    expected_answer: str,
    provider: "BaseProvider",
) -> tuple[float, str | None] | None:
    """Rate how well *generated_answer* captures the key info in *expected_answer*.

    Returns ``(score_0_1, reason)`` or None on failure.
    """
    prompt = _CORRECTNESS_PROMPT.format(
        query=query,
        expected=expected_answer[:3000],
        generated=generated_answer[:3000],
    )
    try:
        response = provider.complete(prompt)
        raw, reason = _parse_judge_response(response)
        if raw == 0:
            return None
        return (raw - 1) / 4.0, reason
    except Exception:
        logger.debug("Answer correctness judge failed (non-fatal)", exc_info=True)
        return None


def score_answer_relevance(
    *,
    query: str,
    generated_answer: str,
    provider: "BaseProvider",
) -> tuple[float, str | None] | None:
    """Rate whether *generated_answer* addresses *query*.

    Returns ``(score_0_1, reason)`` or None on failure.
    """
    prompt = _RELEVANCE_PROMPT.format(
        query=query,
        generated=generated_answer[:3000],
    )
    try:
        response = provider.complete(prompt)
        raw, reason = _parse_judge_response(response)
        if raw == 0:
            return None
        return (raw - 1) / 4.0, reason
    except Exception:
        logger.debug("Answer relevance judge failed (non-fatal)", exc_info=True)
        return None


def score_context_precision(
    *,
    retrieved_texts: list[str],
    expected_citations: list[str],
) -> float:
    """Proportion of retrieved chunks containing at least one expected citation.

    String-match heuristic — no LLM call required.  Returns 0.0 when
    *retrieved_texts* is empty or no expected citations are given.
    """
    if not retrieved_texts or not expected_citations:
        return 0.0
    citations_lower = [c.lower() for c in expected_citations]
    hits = sum(1 for text in retrieved_texts if any(cit in text.lower() for cit in citations_lower))
    return hits / len(retrieved_texts)


def score_context_recall(
    *,
    retrieved_texts: list[str],
    expected_citations: list[str],
) -> float:
    """Proportion of expected citations found in the retrieved chunks.

    String-match heuristic — no LLM call required.  Returns 0.0 when
    *expected_citations* is empty.
    """
    if not expected_citations:
        return 0.0
    if not retrieved_texts:
        return 0.0
    all_retrieved = " ".join(t.lower() for t in retrieved_texts)
    found = sum(1 for cit in expected_citations if cit.lower() in all_retrieved)
    return found / len(expected_citations)
