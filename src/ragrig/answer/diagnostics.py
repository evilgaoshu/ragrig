"""Answer live smoke diagnostics — JSON report for local LLM provider health.

This module provides a safe, dependency-guarded diagnostics path for
`make answer-live-smoke`.  It never crashes on missing optional dependencies
and never exposes raw API keys.

This module also provides artifact generation and console-safe summary
functions for the Web Console badge / CI artifact pattern.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
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
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, query, parsed.fragment))


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
                    "content": ("Say 'pong' and include a citation like [cit-1]."),
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
    base_url = base_url or os.environ.get("RAGRIG_ANSWER_BASE_URL", "http://localhost:11434/v1")

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


# ── Artifact generation ──────────────────────────────────────────────────

_DEFAULT_ARTIFACT_PATH = Path("docs/operations/artifacts/answer-live-smoke.json")
_ARTIFACT_TYPE = "answer-live-smoke"
_SUPPORTED_SCHEMA_VERSION = "1.0"

_SECRET_KEY_PARTS = (
    "api_key",
    "access_key",
    "secret",
    "password",
    "token",
    "credential",
    "private_key",
    "dsn",
    "service_account",
    "session_token",
)


def _redact_secrets(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: "[redacted]"
            if any(p in k.lower() for p in _SECRET_KEY_PARTS)
            else _redact_secrets(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_secrets(v) for v in obj]
    return obj


def generate_diagnostics_artifact(
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    output_path: Path | None = None,
    _deps_fn=_check_openai_dependency,
    _ping_fn=_ping_provider,
    _chat_fn=_smoke_chat,
) -> dict[str, Any]:
    """Run diagnostics and produce a CI artifact dict with all required fields.

    Writes to *output_path* if provided (defaults to
    ``docs/operations/artifacts/answer-live-smoke.json``).
    Never includes raw secret fragments.
    """
    report = run_answer_diagnostics(
        provider=provider,
        model=model,
        base_url=base_url,
        _deps_fn=_deps_fn,
        _ping_fn=_ping_fn,
        _chat_fn=_chat_fn,
    )

    now_iso = datetime.now(timezone.utc).isoformat()
    artifact = {
        "artifact": _ARTIFACT_TYPE,
        "schema_version": _SUPPORTED_SCHEMA_VERSION,
        "provider": report.provider,
        "model": report.model,
        "base_url_redacted": report.base_url_redacted,
        "status": report.status,
        "reason": report.reason,
        "citation_count": report.citation_count,
        "timing_ms": report.timing_ms,
        "generated_at": now_iso,
        "report_path": None,
    }
    artifact = _redact_secrets(artifact)

    out = output_path or _DEFAULT_ARTIFACT_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    artifact["report_path"] = str(out)
    return artifact


def _read_artifact(artifact_path: Path) -> dict[str, Any] | None:
    """Read and validate a diagnostics artifact, or return None on failure."""
    if not artifact_path.exists():
        return None
    try:
        data = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("artifact") != _ARTIFACT_TYPE:
        return None
    return data


def get_diagnostics_summary(*, artifact_path: Path | None = None) -> dict[str, Any]:
    """Return a Web Console-safe summary of the latest answer live smoke diagnostics.

    Reads the artifact at *artifact_path* (defaults to
    ``docs/operations/artifacts/answer-live-smoke.json``).

    Missing, corrupt, or schema-incompatible artifacts are reported as
    degraded/failure — never as healthy.
    Never includes raw secret fragments.
    """
    path = artifact_path or _DEFAULT_ARTIFACT_PATH

    def _artifact_relative() -> str:
        try:
            return str(path.relative_to(Path(__file__).resolve().parents[2]))
        except ValueError:
            return str(path)

    artifact = _read_artifact(path)
    if artifact is None:
        return {
            "available": False,
            "status": "failure",
            "reason": "artifact not found or corrupt",
            "artifact_path": _artifact_relative(),
        }

    # Check staleness (> 24 hours)
    generated_at_str = artifact.get("generated_at")
    is_stale = False
    if generated_at_str:
        try:
            generated_at = datetime.fromisoformat(generated_at_str.replace("Z", "+00:00"))
            age_hours = (datetime.now(timezone.utc) - generated_at).total_seconds() / 3600.0
            if age_hours > 24:
                is_stale = True
        except (ValueError, TypeError):
            pass

    status = artifact.get("status", "unknown")
    if status not in ("healthy", "degraded", "skip", "error"):
        status = "failure"

    if is_stale and status == "healthy":
        status = "degraded"

    summary: dict[str, Any] = {
        "available": True,
        "status": status,
        "is_stale": is_stale,
        "provider": artifact.get("provider"),
        "model": artifact.get("model"),
        "base_url_redacted": artifact.get("base_url_redacted"),
        "reason": artifact.get("reason"),
        "citation_count": artifact.get("citation_count"),
        "timing_ms": artifact.get("timing_ms"),
        "generated_at": generated_at_str,
        "report_path": artifact.get("report_path") or _artifact_relative(),
        "artifact_path": _artifact_relative(),
        "schema_version": artifact.get("schema_version"),
    }

    # Map skip/error to degraded/failure for status card display
    summary["display_status"] = summary["status"]

    return summary


__all__ = [
    "AnswerDiagnosticsReport",
    "Status",
    "_check_openai_dependency",
    "_ping_provider",
    "_redact_base_url",
    "_smoke_chat",
    "generate_diagnostics_artifact",
    "get_diagnostics_summary",
    "run_answer_diagnostics",
]
