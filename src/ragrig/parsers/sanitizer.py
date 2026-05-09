"""Summary sanitizer for preview parser metadata.

Redacts sensitive fragments from text_summary to prevent token,
password, API key, and other secrets from leaking into pipeline
metadata or the Web Console.

All CSV/HTML/plaintext/markdown preview parsers share this single
sanitizer.
"""

from __future__ import annotations

import re

_MAX_CHARS: int = 80

# Key names that indicate a sensitive value follows.
_SENSITIVE_KEY: str = (
    r"api[_-]?key"
    r"|(?:access[_-]?|auth[_-]?)?token"
    r"|password"
    r"|secret"
)

# Non-whitespace delimiters where a value should stop.
_VALID_VALUE_CHAR = r"[^\s,;}\]\"\'\)\]]"

# Patterns ordered from most specific to least specific to avoid
# partial-match collisions (e.g. Bearer before generic token,
# key=value before standalone sk- pattern).
_SENSITIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # 1. Bearer tokens: "Bearer eyJ..." -> "Bearer [REDACTED]"
    (re.compile(r"Bearer\s+\S+", re.IGNORECASE), "Bearer [REDACTED]"),
    # 2. Private key PEM blocks (RSA, EC, DSA, OpenSSH, generic)
    (
        re.compile(
            r"-----BEGIN\s+(?:RSA\s+|EC\s+|DSA\s+|OPENSSH\s+)?PRIVATE\s+KEY-----"
            r"[\s\S]*?"
            r"-----END\s+(?:RSA\s+|EC\s+|DSA\s+|OPENSSH\s+)?PRIVATE\s+KEY-----",
            re.IGNORECASE,
        ),
        "[PRIVATE KEY REDACTED]",
    ),
    # 3. JSON-style: "key": "value" or "key":"value"
    (
        re.compile(
            rf'("(?:{_SENSITIVE_KEY})"\s*:\s*"?)(?:{_VALID_VALUE_CHAR})+',
            re.IGNORECASE,
        ),
        r"\1[REDACTED]",
    ),
    # 4. key=value, key: value, _key=value (plain text, env vars, YAML, etc.)
    (
        re.compile(
            rf"((?:^|\b|[_-])(?:{_SENSITIVE_KEY})\s*[=:]\s*[\"']?)"
            rf"(?:{_VALID_VALUE_CHAR})+",
            re.IGNORECASE,
        ),
        r"\1[REDACTED]",
    ),
    # 5. Standalone common API key prefixes (OpenAI sk-, Anthropic sk-ant-)
    #    Placed AFTER key=value patterns so key=value redaction happens first.
    (
        re.compile(r"\bsk-(?:ant-)?[a-zA-Z0-9_-]{5,}\b"),
        "[API KEY REDACTED]",
    ),
]


def sanitize_text_summary(text: str, max_chars: int = _MAX_CHARS) -> tuple[str, int]:
    """Return (sanitized_summary, redaction_count).

    Applies all sensitive-pattern redactions to *text*, then truncates
    to *max_chars* characters (adding "…" when truncated).

    The redaction count reflects the total number of pattern matches
    found across the full text, not just the truncated prefix.
    """
    if not text:
        return "", 0

    redaction_count = 0
    sanitized = text
    for pattern, replacement in _SENSITIVE_PATTERNS:
        sanitized, n = pattern.subn(replacement, sanitized)
        redaction_count += n

    summary = sanitized
    if len(summary) > max_chars:
        summary = sanitized[:max_chars] + "…"

    return summary, redaction_count
