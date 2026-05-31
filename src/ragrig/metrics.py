"""Prometheus metrics setup and application-level observations."""

from __future__ import annotations

import hashlib
from time import perf_counter
from typing import TYPE_CHECKING, Any

from prometheus_client import Counter, Histogram

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.requests import Request
    from starlette.responses import Response as StarletteResponse


HTTP_REQUESTS = Counter(
    "ragrig_http_requests_total",
    "Total HTTP requests handled by the API.",
    ("method", "path", "status_code"),
)

HTTP_REQUEST_DURATION = Histogram(
    "ragrig_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ("method", "path", "status_code"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

RETRIEVAL_REQUESTS = Counter(
    "ragrig_retrieval_requests_total",
    "Retrieval and answer requests grouped by hit status.",
    ("endpoint", "mode", "backend", "status"),
)

RETRIEVAL_RESULTS = Histogram(
    "ragrig_retrieval_results",
    "Number of returned retrieval results.",
    ("endpoint", "mode", "backend"),
    buckets=(0, 1, 2, 3, 5, 10, 20, 50),
)

RETRIEVAL_DEGRADED = Counter(
    "ragrig_retrieval_degraded_total",
    "Retrieval and answer requests completed with degraded retrieval behavior.",
    ("endpoint", "mode", "backend"),
)

RETRIEVAL_REQUESTS_BY_WORKSPACE = Counter(
    "ragrig_retrieval_requests_by_workspace_total",
    "Retrieval and answer requests grouped by hit status and workspace hash.",
    ("endpoint", "mode", "backend", "status", "workspace"),
)

RETRIEVAL_RESULTS_BY_WORKSPACE = Histogram(
    "ragrig_retrieval_results_by_workspace",
    "Number of returned retrieval results grouped by workspace hash.",
    ("endpoint", "mode", "backend", "workspace"),
    buckets=(0, 1, 2, 3, 5, 10, 20, 50),
)

RETRIEVAL_DEGRADED_BY_WORKSPACE = Counter(
    "ragrig_retrieval_degraded_by_workspace_total",
    "Retrieval and answer requests completed with degraded behavior by workspace hash.",
    ("endpoint", "mode", "backend", "workspace"),
)

MODEL_OPERATION_COST = Counter(
    "ragrig_model_operation_cost_usd_estimated_total",
    "Estimated model operation cost in USD.",
    ("endpoint", "operation", "provider", "model"),
)

MODEL_OPERATION_TOKENS = Counter(
    "ragrig_model_operation_tokens_estimated_total",
    "Estimated model operation tokens.",
    ("endpoint", "operation", "provider", "model", "token_type"),
)

MODEL_OPERATION_LATENCY = Histogram(
    "ragrig_model_operation_latency_seconds",
    "Model operation latency in seconds.",
    ("endpoint", "operation", "provider", "model"),
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

MODEL_OPERATION_COST_BY_WORKSPACE = Counter(
    "ragrig_model_operation_cost_usd_estimated_by_workspace_total",
    "Estimated model operation cost in USD grouped by workspace hash.",
    ("endpoint", "operation", "provider", "model", "workspace"),
)

MODEL_OPERATION_TOKENS_BY_WORKSPACE = Counter(
    "ragrig_model_operation_tokens_estimated_by_workspace_total",
    "Estimated model operation tokens grouped by workspace hash.",
    ("endpoint", "operation", "provider", "model", "workspace", "token_type"),
)

MODEL_OPERATION_LATENCY_BY_WORKSPACE = Histogram(
    "ragrig_model_operation_latency_by_workspace_seconds",
    "Model operation latency in seconds grouped by workspace hash.",
    ("endpoint", "operation", "provider", "model", "workspace"),
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


def setup_metrics(app: "FastAPI") -> None:
    """Attach Prometheus instrumentation and expose /metrics."""
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
    from starlette.responses import Response

    if getattr(app.state, "ragrig_metrics_configured", False):
        return
    app.state.ragrig_metrics_configured = True

    @app.middleware("http")
    async def metrics_middleware(request: "Request", call_next) -> "StarletteResponse":
        if request.url.path == "/metrics":
            return await call_next(request)

        started = perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            route_path = getattr(route, "path", None) or request.url.path
            labels = (
                request.method,
                _label(route_path),
                str(status_code),
            )
            HTTP_REQUESTS.labels(*labels).inc()
            HTTP_REQUEST_DURATION.labels(*labels).observe(perf_counter() - started)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def observe_retrieval_report(
    *,
    endpoint: str,
    mode: str,
    backend: str | None,
    total_results: int,
    degraded: bool = False,
    cost_latency: dict[str, Any] | None = None,
    workspace_id: object | None = None,
    include_workspace_label: bool = False,
) -> None:
    """Record retrieval/answer business metrics from an existing report."""
    normalized_results = max(0, int(total_results))
    status = "hit" if normalized_results > 0 else "zero_results"
    labels = (_label(endpoint), _label(mode), _label(backend), status)
    RETRIEVAL_REQUESTS.labels(*labels).inc()
    RETRIEVAL_RESULTS.labels(*labels[:3]).observe(normalized_results)
    if degraded:
        RETRIEVAL_DEGRADED.labels(*labels[:3]).inc()
    workspace = _workspace_label(workspace_id) if include_workspace_label else None
    if workspace:
        workspace_labels = (*labels, workspace)
        RETRIEVAL_REQUESTS_BY_WORKSPACE.labels(*workspace_labels).inc()
        RETRIEVAL_RESULTS_BY_WORKSPACE.labels(*labels[:3], workspace).observe(normalized_results)
        if degraded:
            RETRIEVAL_DEGRADED_BY_WORKSPACE.labels(*labels[:3], workspace).inc()
    observe_model_operations(endpoint=endpoint, cost_latency=cost_latency, workspace=workspace)


def observe_retrieval_error(
    *,
    endpoint: str,
    mode: str,
    backend: str | None = None,
    workspace_id: object | None = None,
    include_workspace_label: bool = False,
) -> None:
    """Record a retrieval request that failed before a report was available."""
    labels = (_label(endpoint), _label(mode), _label(backend), "error")
    RETRIEVAL_REQUESTS.labels(*labels).inc()
    if include_workspace_label:
        workspace = _workspace_label(workspace_id)
        if workspace:
            RETRIEVAL_REQUESTS_BY_WORKSPACE.labels(*labels, workspace).inc()


def observe_model_operations(
    *,
    endpoint: str,
    cost_latency: dict[str, Any] | None,
    workspace: str | None = None,
) -> None:
    """Record token, cost, and latency estimates from cost_latency operations."""
    operations = (cost_latency or {}).get("operations") or []
    if not isinstance(operations, list):
        return
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        operation_name = _label(operation.get("operation"))
        provider = _label(operation.get("provider"))
        model = _label(operation.get("model"))
        labels = (_label(endpoint), operation_name, provider, model)
        cost = max(0.0, float(operation.get("total_cost_usd_estimated") or 0.0))
        input_tokens = max(0, int(operation.get("input_tokens_estimated") or 0))
        output_tokens = max(0, int(operation.get("output_tokens_estimated") or 0))
        total_tokens = max(0, int(operation.get("total_tokens_estimated") or 0))
        latency_seconds = max(0.0, float(operation.get("latency_ms") or 0.0)) / 1000.0
        MODEL_OPERATION_COST.labels(*labels).inc(cost)
        MODEL_OPERATION_TOKENS.labels(*labels, "input").inc(input_tokens)
        MODEL_OPERATION_TOKENS.labels(*labels, "output").inc(output_tokens)
        MODEL_OPERATION_TOKENS.labels(*labels, "total").inc(total_tokens)
        MODEL_OPERATION_LATENCY.labels(*labels).observe(latency_seconds)
        if workspace:
            workspace_labels = (*labels, workspace)
            MODEL_OPERATION_COST_BY_WORKSPACE.labels(*workspace_labels).inc(cost)
            MODEL_OPERATION_TOKENS_BY_WORKSPACE.labels(*workspace_labels, "input").inc(input_tokens)
            MODEL_OPERATION_TOKENS_BY_WORKSPACE.labels(*workspace_labels, "output").inc(
                output_tokens
            )
            MODEL_OPERATION_TOKENS_BY_WORKSPACE.labels(*workspace_labels, "total").inc(total_tokens)
            MODEL_OPERATION_LATENCY_BY_WORKSPACE.labels(*workspace_labels).observe(latency_seconds)


def _label(value: object) -> str:
    text = str(value or "unknown").strip()
    return text or "unknown"


def _workspace_label(value: object | None) -> str | None:
    if value is None:
        return None
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]
    return f"ws_{digest}"
