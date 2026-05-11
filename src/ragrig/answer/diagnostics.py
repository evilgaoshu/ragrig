"""Answer live smoke diagnostics — JSON report for local LLM provider health.

This module provides a safe, dependency-guarded diagnostics path for
`make answer-live-smoke`.  It never crashes on missing optional dependencies
and never exposes raw API keys.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Literal
from urllib.parse import urlparse, urlunparse

Status = Literal["healthy", "degraded", "skip", "error"]


def _try_import(import_name: str) -> bool:
    try:
        __import__(import_name)
        return True
    except ImportError:
        return False


def _redact_base_url(url: str) -> str:
    """Redact API keys / credentials from a base URL.

    Removes userinfo (e.g. ``http://key@host/``) and common secret query params.
    If the URL is malformed (e.g. port out of range), returns it unchanged
    so that diagnostics never crash on bad input.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return url

    netloc = parsed.hostname or ""
    try:
        if parsed.port:
            netloc += f":{parsed.port}"
    except ValueError:
        # Malformed port — keep the raw netloc so the operator can see the typo
        netloc = parsed.netloc

    # Strip query parameters that look like secrets
    safe_params: list[str] = []
    if parsed.query:
        for param in parsed.query.split("&"):
            if not param:
                continue
            key = param.split("=")[0].lower()
            if any(secret in key for secret in ("api_key", "secret", "token", "password")):
                safe_params.append(f"{param.split('=')[0]}=[REDACTED]")
            else:
                safe_params.append(param)

    query = "&".join(safe_params) if safe_params else ""
    return urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, query, parsed.fragment)
    )


def _check_openai_dependency() -> tuple[bool, str]:
    """Check whether the ``openai`` package is importable.

    Returns ``(ok, reason)``.
    """
    if not _try_import("openai"):
        return (
            False,
            "Missing optional dependency: openai. "
            "Install with: uv sync --extra local-ml  or  pip install .[local-ml]",
        )
    return True, "openai package is available."


def _ping_provider(base_url: str, timeout: float = 10.0) -> tuple[bool, str]:
    """Attempt a lightweight health ping against an OpenAI-compatible endpoint.

    Returns ``(ok, reason)``.
    """
    try:
        from openai import OpenAI

        client = OpenAI(base_url=base_url, api_key="not-needed", timeout=timeout)
        client.models.list()
        return True, "Provider endpoint responded to models.list()."
    except Exception as exc:  # noqa: BLE001
        return False, f"Provider unreachable: {type(exc).__name__}: {exc}"


def _smoke_chat(
    base_url: str,
    model: str,
    timeout: float = 30.0,
) -> tuple[int, str]:
    """Send a minimal chat request and count citation IDs in the response.

    Returns ``(citation_count, reason)``.
    """
    try:
        from openai import OpenAI

        client = OpenAI(base_url=base_url, api_key="not-needed", timeout=timeout)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Say 'pong' and include a citation like [cit-1]."
                    ),
                }
            ],
            temperature=0.0,
            max_tokens=50,
        )
        content = response.choices[0].message.content or ""
        citations = re.findall(r"\[(cit-\d+)\]", content)
        return len(citations), f"Chat smoke completed; response length={len(content)} chars."
    except Exception as exc:  # noqa: BLE001
        return 0, f"Chat smoke failed: {type(exc).__name__}: {exc}"


@dataclass
class AnswerDiagnosticsReport:
    """Structured JSON-serialisable report for answer live smoke diagnostics."""

    provider: str
    model: str
    base_url_redacted: str
    status: Status
    reason: str
    citation_count: int
    timing_ms: float
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url_redacted": self.base_url_redacted,
            "status": self.status,
            "reason": self.reason,
            "citation_count": self.citation_count,
            "timing_ms": self.timing_ms,
            "details": self.details,
        }

    def to_json(self, *, indent: int | None = None) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, sort_keys=True)


def run_answer_diagnostics(
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    _ping_fn=_ping_provider,
    _chat_fn=_smoke_chat,
    _deps_fn=_check_openai_dependency,
) -> AnswerDiagnosticsReport:
    """Run answer live smoke diagnostics and return a structured report.

    All optional ``_`` prefixed arguments are exposed for testing only.
    """
    provider = provider or os.environ.get("RAGRIG_ANSWER_PROVIDER", "ollama")
    model = model or os.environ.get("RAGRIG_ANSWER_MODEL", "llama3.2:1b")
    base_url = base_url or os.environ.get(
        "RAGRIG_ANSWER_BASE_URL", "http://localhost:11434/v1"
    )

    t0 = time.perf_counter()
    base_url_redacted = _redact_base_url(base_url)

    # 1. Dependency check
    deps_ok, deps_reason = _deps_fn()
    if not deps_ok:
        timing_ms = round((time.perf_counter() - t0) * 1000, 2)
        return AnswerDiagnosticsReport(
            provider=provider,
            model=model,
            base_url_redacted=base_url_redacted,
            status="skip",
            reason=deps_reason,
            citation_count=0,
            timing_ms=timing_ms,
            details={"missing_dependencies": True},
        )

    # 2. Reachability check
    reachable, reach_reason = _ping_fn(base_url)
    if not reachable:
        timing_ms = round((time.perf_counter() - t0) * 1000, 2)
        return AnswerDiagnosticsReport(
            provider=provider,
            model=model,
            base_url_redacted=base_url_redacted,
            status="error",
            reason=reach_reason,
            citation_count=0,
            timing_ms=timing_ms,
            details={"reachable": False},
        )

    # 3. Smoke chat
    citation_count, chat_reason = _chat_fn(base_url, model)
    timing_ms = round((time.perf_counter() - t0) * 1000, 2)

    if citation_count > 0:
        status: Status = "healthy"
        reason = f"Provider healthy. {chat_reason}"
    else:
        status = "degraded"
        reason = f"Provider reachable but no citations in response. {chat_reason}"

    return AnswerDiagnosticsReport(
        provider=provider,
        model=model,
        base_url_redacted=base_url_redacted,
        status=status,
        reason=reason,
        citation_count=citation_count,
        timing_ms=timing_ms,
        details={"reachable": True, "chat_smoke": chat_reason},
    )


__all__ = [
    "AnswerDiagnosticsReport",
    "Status",
    "_check_openai_dependency",
    "_ping_provider",
    "_redact_base_url",
    "_smoke_chat",
    "run_answer_diagnostics",
]
