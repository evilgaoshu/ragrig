from __future__ import annotations

import logging
import uuid
from time import perf_counter

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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

    @app.exception_handler(HTTPException)
    async def http_exception_handler(_request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": jsonable_encoder(exc.detail)},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        request_id = request.headers.get("x-request-id")
        if request_id:
            headers = {"X-Request-ID": request_id}
        else:
            headers = {}
        logging.getLogger(__name__).exception(
            "Unhandled API exception for %s %s",
            request.method,
            request.url.path,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_server_error",
                    "message": "Internal server error",
                }
            },
            headers=headers,
        )


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
