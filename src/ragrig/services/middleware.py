from __future__ import annotations

import logging
import uuid
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from ragrig.config import Settings
from ragrig.observability import bind_log_context, log_event
from ragrig.services.common import ServiceError, service_error_response


def _parse_cors_origins(raw: str) -> list[str]:
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def configure_cors(app: FastAPI, settings: Settings) -> None:
    origins = _parse_cors_origins(settings.ragrig_cors_origins)
    origin_regex = settings.ragrig_cors_allow_origin_regex.strip() or None
    if not origins and origin_regex is None:
        return
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=origin_regex,
        allow_credentials=settings.ragrig_cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def configure_service_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ServiceError)
    async def service_error_handler(_request: Request, exc: ServiceError):
        return service_error_response(exc)


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
