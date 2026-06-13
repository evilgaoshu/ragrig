"""Optional Langfuse trace adapter."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from typing import Any

from ragrig.evaluation.report import _sanitize_dict

LangfuseClientFactory = Callable[..., Any]


def emit_langfuse_trace(
    settings: Any,
    *,
    name: str,
    metadata: Mapping[str, Any] | None = None,
    input_metadata: Mapping[str, Any] | None = None,
    output_metadata: Mapping[str, Any] | None = None,
    client_factory: LangfuseClientFactory | None = None,
) -> dict[str, Any]:
    """Emit a high-level Langfuse trace when explicitly enabled.

    The adapter never raises into request/evaluation paths. Diagnostics are
    intentionally compact and secret-free.
    """
    enabled = bool(getattr(settings, "ragrig_langfuse_enabled", False))
    if not enabled:
        return {"enabled": False, "status": "disabled"}

    public_key = str(getattr(settings, "ragrig_langfuse_public_key", "") or "")
    secret_key = str(getattr(settings, "ragrig_langfuse_secret_key", "") or "")
    host = str(getattr(settings, "ragrig_langfuse_host", "") or "")
    if not public_key or not secret_key:
        return {
            "enabled": True,
            "status": "degraded",
            "degraded_reason": "missing_credentials",
        }

    try:
        factory = client_factory or _load_langfuse_factory()
    except Exception as exc:
        return {
            "enabled": True,
            "status": "degraded",
            "degraded_reason": "missing_dependency",
            "error": type(exc).__name__,
        }

    try:
        client = factory(public_key=public_key, secret_key=secret_key, host=host)
        trace_kwargs = {
            "name": name,
            "metadata": _sanitize_dict(dict(metadata or {})),
        }
        if input_metadata is not None:
            trace_kwargs["input"] = _sanitize_dict(dict(input_metadata))
        if output_metadata is not None:
            trace_kwargs["output"] = _sanitize_dict(dict(output_metadata))
        trace = getattr(client, "trace", None)
        if callable(trace):
            trace(**trace_kwargs)
        else:
            start_trace = getattr(client, "start_trace", None)
            if callable(start_trace):
                start_trace(**trace_kwargs)
            else:
                raise RuntimeError("Langfuse client does not expose trace")
        flush = getattr(client, "flush", None)
        if callable(flush):
            flush()
    except Exception as exc:
        return {
            "enabled": True,
            "status": "degraded",
            "degraded_reason": "adapter_error",
            "error": type(exc).__name__,
        }

    return {"enabled": True, "status": "sent"}


def _load_langfuse_factory() -> LangfuseClientFactory:
    module = importlib.import_module("langfuse")
    factory = getattr(module, "Langfuse", None)
    if not callable(factory):
        raise RuntimeError("langfuse module does not expose Langfuse")
    return factory
