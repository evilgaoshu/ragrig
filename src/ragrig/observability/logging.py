from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_LOG_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar("ragrig_log_context", default=None)

_SECRET_FIELD_RE = re.compile(
    r"(api[_-]?key|authorization|bearer|client[_-]?secret|cookie|password|secret|token)",
    re.IGNORECASE,
)
_SECRET_VALUE_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"(?i)(authorization|bearer)\s*[:=]\s*([^\s,;]+)"),
    re.compile(r"sk-[A-Za-z0-9_-]+"),
]
_TEXT_FIELD_RE = re.compile(r"^(answer|evidence_text|input_text|output_text|prompt|query)$")
_PATH_FIELD_RE = re.compile(r"(^|_)(file_path|path|root_path)$")
_URI_FIELD_RE = re.compile(r"(^|_)(document_uri|source_uri|uri)$")


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_text(value: str) -> dict[str, Any]:
    return {"sha256": _hash_text(value), "length": len(value)}


def _safe_locator(value: str) -> dict[str, Any]:
    parsed = urlsplit(value)
    candidate = parsed.path if parsed.scheme else value
    basename = _redact_string(Path(candidate).name)
    payload: dict[str, Any] = {
        "basename": basename,
        "sha256": _hash_text(value),
    }
    if parsed.scheme:
        payload["scheme"] = parsed.scheme
    return payload


def _redact_string(value: str) -> str:
    redacted = value
    for pattern in _SECRET_VALUE_PATTERNS:
        if pattern.pattern.startswith("sk-"):
            redacted = pattern.sub("sk-[REDACTED]", redacted)
        else:
            redacted = pattern.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
    return redacted


def sanitize_log_value(value: Any, *, key: str | None = None) -> Any:
    """Return a JSON-safe value with secrets and sensitive free text removed."""

    key_name = (key or "").lower()
    if key_name and _SECRET_FIELD_RE.search(key_name):
        return "[REDACTED]"

    if isinstance(value, Mapping):
        return {
            str(child_key): sanitize_log_value(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [sanitize_log_value(item, key=key) for item in value]
    if isinstance(value, Path):
        return _safe_locator(str(value))
    if isinstance(value, str):
        if key_name and _TEXT_FIELD_RE.match(key_name):
            return _safe_text(value)
        if key_name and (_PATH_FIELD_RE.search(key_name) or _URI_FIELD_RE.search(key_name)):
            return _safe_locator(value)
        return _redact_string(value)
    return value


def sanitize_log_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): sanitize_log_value(value, key=str(key)) for key, value in fields.items()}


def safe_query_fields(query: str) -> dict[str, Any]:
    return {"query_sha256": _hash_text(query), "query_length": len(query)}


def get_log_context() -> dict[str, Any]:
    return dict(_LOG_CONTEXT.get() or {})


@contextmanager
def bind_log_context(**fields: Any) -> Iterator[None]:
    current = dict(_LOG_CONTEXT.get() or {})
    current.update(sanitize_log_fields(fields))
    token = _LOG_CONTEXT.set(current)
    try:
        yield
    finally:
        _LOG_CONTEXT.reset(token)


class StructuredJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self.formatMessage(record),
        }
        event = getattr(record, "event", None)
        if event:
            payload["event"] = event

        payload.update(get_log_context())
        fields = getattr(record, "structured_fields", None)
        if isinstance(fields, Mapping):
            payload.update(sanitize_log_fields(fields))

        try:
            from opentelemetry import trace

            span = trace.get_current_span()
            ctx = span.get_span_context()
            if ctx and ctx.is_valid:
                payload["trace_id"] = format(ctx.trace_id, "032x")
                payload["span_id"] = format(ctx.span_id, "016x")
        except Exception:
            pass

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, sort_keys=True)


class PlainFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        payload: dict[str, Any] = {}
        event = getattr(record, "event", None)
        if event:
            payload["event"] = event
        payload.update(get_log_context())
        fields = getattr(record, "structured_fields", None)
        if isinstance(fields, Mapping):
            payload.update(sanitize_log_fields(fields))
        if not payload:
            return base
        return f"{base} {json.dumps(payload, default=str, sort_keys=True)}"


def configure_logging(*, log_format: str = "plain", level: str = "INFO") -> None:
    root = logging.getLogger()
    resolved_level = getattr(logging, str(level).upper(), logging.INFO)
    root.setLevel(resolved_level)

    normalized_format = str(log_format or "plain").lower()
    if normalized_format == "json":
        formatter: logging.Formatter = StructuredJsonFormatter()
    else:
        formatter = PlainFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    for handler in root.handlers:
        handler.setLevel(resolved_level)
        handler.setFormatter(formatter)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    message: str | None = None,
    *,
    exc_info: bool | BaseException | tuple[Any, Any, Any] | None = None,
    **fields: Any,
) -> None:
    structured_fields = get_log_context()
    structured_fields.update(sanitize_log_fields(fields))
    logger.log(
        level,
        message or event,
        extra={
            "event": event,
            "structured_fields": structured_fields,
        },
        exc_info=exc_info,
    )
