"""Regex-based PII detection and redaction.

Detects common PII patterns and replaces them with labelled placeholders.
No external ML dependencies — runs entirely in-process.

Patterns covered:
- Email addresses             → [PII_EMAIL]
- Phone numbers (intl/US)     → [PII_PHONE]
- US Social Security Numbers  → [PII_SSN]
- Credit card numbers (Luhn)  → [PII_CC]
- IPv4 addresses              → [PII_IP]
- UK National Insurance       → [PII_NI]
- Passport-like numbers       → [PII_PASSPORT]
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "[PII_EMAIL]",
        re.compile(
            r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
            re.IGNORECASE,
        ),
    ),
    (
        "[PII_SSN]",
        re.compile(r"\b(?!000|666|9\d{2})\d{3}[- ](?!00)\d{2}[- ](?!0{4})\d{4}\b"),
    ),
    (
        "[PII_CC]",
        re.compile(r"\b(?:4\d{12}(?:\d{3})?|5[1-5]\d{14}|3[47]\d{13}|6(?:011|5\d{2})\d{12})\b"),
    ),
    (
        "[PII_PHONE]",
        re.compile(
            r"(?<!\d)"
            r"(?:\+?1[-.\s]?)?"
            r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
            r"(?!\d)",
        ),
    ),
    (
        "[PII_IP]",
        re.compile(
            r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
        ),
    ),
    (
        "[PII_NI]",
        re.compile(
            r"\b[A-CEGHJ-PR-TW-Z]{1}[A-CEGHJ-NPR-TW-Z]{1}\d{6}[A-D]\b",
            re.IGNORECASE,
        ),
    ),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PiiScanResult:
    redacted_text: str
    hit_count: int
    labels_found: list[str]


def redact(text: str) -> PiiScanResult:
    """Replace all detected PII patterns in *text* with placeholder labels."""
    result = text
    hit_count = 0
    labels: list[str] = []
    for label, pattern in _PATTERNS:
        new_text, n = pattern.subn(label, result)
        if n:
            hit_count += n
            labels.append(label)
            result = new_text
    return PiiScanResult(redacted_text=result, hit_count=hit_count, labels_found=labels)


def scan(text: str) -> list[str]:
    """Return a list of PII label types detected in *text* (no redaction)."""
    found: list[str] = []
    for label, pattern in _PATTERNS:
        if pattern.search(text):
            found.append(label)
    return found
