"""Prometheus metrics setup.

Instruments the FastAPI app with prometheus-fastapi-instrumentator.
Call `setup_metrics(app)` during app creation when metrics are enabled.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def setup_metrics(app: "FastAPI") -> None:
    """Attach Prometheus instrumentation and expose /metrics."""
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_respect_env_var=False,
        excluded_handlers=["/metrics", "/health"],
        body_handlers=[],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
