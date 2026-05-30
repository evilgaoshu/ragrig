"""OpenTelemetry tracing and structured logging setup.

Call `setup_otel(app, settings)` during app creation when enabled.
Exports traces via OTLP HTTP to the configured collector endpoint.
When ragrig_log_format='json', configures a JSON log formatter that
injects trace_id/span_id correlation fields into every log record.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ragrig.observability.logging import configure_logging

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ragrig.config import Settings

logger = logging.getLogger(__name__)


def setup_otel(app: "FastAPI", settings: "Settings") -> None:
    """Configure OpenTelemetry tracing + optional JSON structured logging."""
    configure_logging(
        log_format=settings.ragrig_log_format,
        level=settings.ragrig_log_level,
        log_file=settings.ragrig_log_file or None,
        log_max_bytes=settings.ragrig_log_max_bytes,
        log_backup_count=settings.ragrig_log_backup_count,
    )
    if not settings.ragrig_otel_enabled:
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

    logger.info(
        "OpenTelemetry tracing enabled (endpoint=%s, service=%s)",
        settings.ragrig_otel_endpoint,
        settings.ragrig_otel_service_name,
    )
