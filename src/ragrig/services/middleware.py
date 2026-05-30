from __future__ import annotations

import logging
import uuid
from time import perf_counter

from fastapi import FastAPI, Request

from ragrig.observability import bind_log_context, log_event


def configure_structured_request_logging(app: FastAPI, logger: logging.Logger) -> None:
    async def structured_request_logging(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        started = perf_counter()
        with bind_log_context(request_id=request_id):
            log_event(
                logger,
                logging.INFO,
                "api.request.start",
                method=request.method,
                route=request.url.path,
            )
            try:
                response = await call_next(request)
            except Exception as exc:
                log_event(
                    logger,
                    logging.ERROR,
                    "api.request.failed",
                    method=request.method,
                    route=request.url.path,
                    duration_ms=round((perf_counter() - started) * 1000, 3),
                    error=str(exc),
                    exc_info=True,
                )
                raise
            response.headers["X-Request-ID"] = request_id
            log_event(
                logger,
                logging.INFO,
                "api.request.completed",
                method=request.method,
                route=request.url.path,
                status_code=response.status_code,
                duration_ms=round((perf_counter() - started) * 1000, 3),
            )
            return response

    app.middleware("http")(structured_request_logging)
