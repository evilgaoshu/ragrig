"""OpenTelemetry tracing and structured logging setup.

Call `setup_otel(app, settings)` during app creation when enabled.
Exports traces via OTLP HTTP to the configured collector endpoint.
When ragrig_log_format='json', configures a JSON log formatter that
injects trace_id/span_id correlation fields into every log record.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ragrig.config import Settings

logger = logging.getLogger(__name__)


class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line with OTel correlation fields."""

    def format(self, record: logging.LogRecord) -> str:
        import json
        from datetime import UTC, datetime

        payload: dict = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": self.formatMessage(record),
        }
        # Inject active span context when available
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
        return json.dumps(payload, default=str)


def _configure_json_logging() -> None:
    formatter = _JsonFormatter()
    root = logging.getLogger()
    for handler in root.handlers:
        handler.setFormatter(formatter)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        root.addHandler(handler)


def setup_otel(app: "FastAPI", settings: "Settings") -> None:
    """Configure OpenTelemetry tracing + optional JSON structured logging."""
    if not settings.ragrig_otel_enabled:
        if settings.ragrig_log_format == "json":
            _configure_json_logging()
        return

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:
        logger.warning("OpenTelemetry packages not installed, tracing disabled: %s", exc)
        return

    resource = Resource.create({SERVICE_NAME: settings.ragrig_otel_service_name})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=f"{settings.ragrig_otel_endpoint.rstrip('/')}/v1/traces",
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    SQLAlchemyInstrumentor().instrument(enable_commenter=False)

    if settings.ragrig_log_format == "json":
        _configure_json_logging()

    logger.info(
        "OpenTelemetry tracing enabled (endpoint=%s, service=%s)",
        settings.ragrig_otel_endpoint,
        settings.ragrig_otel_service_name,
    )
