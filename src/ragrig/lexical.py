"""Deterministic local lexical scorer for hybrid retrieval.

Implements a BM25-lite token-overlap scorer that ranks text chunks against
a query by term frequency and inverse document frequency computed locally.
No external services or indices are required.
"""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"\w+")


def _tokenize(text: str) -> list[str]:
    """Lower-case tokenization matching word character runs."""
    return _TOKEN_RE.findall(text.lower())


def _compute_tf(chunk_tokens: list[str]) -> dict[str, float]:
    """Relative term frequency: count / total tokens."""
    total = len(chunk_tokens)
    if total == 0:
        return {}
    counts = Counter(chunk_tokens)
    return {term: count / total for term, count in counts.items()}


def _compute_idf(
    corpus_tokens: list[list[str]], query_terms: set[str]
) -> dict[str, float]:
    """Inverse document frequency for a set of query terms across a corpus."""
    num_docs = len(corpus_tokens)
    if num_docs == 0:
        return {term: 0.0 for term in query_terms}
    idf: dict[str, float] = {}
    for term in query_terms:
        df = sum(1 for tokens in corpus_tokens if term in tokens)
        idf[term] = math.log((num_docs - df + 0.5) / (df + 0.5) + 1.0)
    return idf


def bm25_score_tokens(
    chunk_tokens: list[str],
    query_tokens: list[str],
    corpus_tokens: list[list[str]],
    *,
    k1: float = 1.2,
    b: float = 0.75,
) -> float:
    """BM25-lite scoring for a single chunk against a query.

    Uses the standard BM25 formula:

        score = Σ IDF(qi) * (tf(qi, D) * (k1 + 1)) / (tf(qi, D) + k1 * (1 - b + b * |D| / avg_dl))

    The avg_dl is computed from the corpus provided.

    Returns a non-negative float where higher values indicate better lexical
    match.
    """
    if not query_tokens or not chunk_tokens:
        return 0.0

    tf = _compute_tf(chunk_tokens)
    query_terms = set(query_tokens)
    idf = _compute_idf(corpus_tokens, query_terms)

    avg_dl = sum(len(tokens) for tokens in corpus_tokens) / max(len(corpus_tokens), 1)
    dl = len(chunk_tokens)
    norm_factor = k1 * (1.0 - b + b * dl / max(avg_dl, 1.0))

    score = 0.0
    for term in query_terms:
        tf_val = tf.get(term, 0.0)
        if tf_val > 0 and idf.get(term, 0.0) > 0:
            score += idf[term] * (tf_val * (k1 + 1)) / (tf_val + norm_factor)

    return score


def token_overlap_score(
    chunk_text: str, query: str, corpus_texts: list[str]
) -> float:
    """Deterministic token overlap scorer backed by BM25-lite.

    Tokenizes both chunk_text and query, then builds a corpus view from all
    provided corpus_texts.  The score is a non-negative float; higher values
    mean stronger lexical match.

    When corpus_texts is empty, falls back to a pure token overlap ratio.
    """
    query_tokens = _tokenize(query)
    chunk_tokens = _tokenize(chunk_text)
    if not query_tokens or not chunk_tokens:
        return 0.0

    if not corpus_texts:
        overlap = set(chunk_tokens) & set(query_tokens)
        return len(overlap) / max(len(query_tokens), 1)

    corpus = [_tokenize(t) for t in corpus_texts]
    return bm25_score_tokens(chunk_tokens, query_tokens, corpus)


__all__ = [
    "bm25_score_tokens",
    "token_overlap_score",
]
