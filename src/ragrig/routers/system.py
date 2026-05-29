"""System health, status, and local pilot routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ragrig import __version__
from ragrig.config import Settings, get_settings
from ragrig.db.session import get_session
from ragrig.health import build_reranker_health
from ragrig.local_pilot import (
    ModelConfigError,
    build_local_pilot_status,
    model_health_check,
    run_answer_smoke,
)
from ragrig.routers.runtime import get_database_check
from ragrig.vectorstore import get_vector_backend_health
from ragrig.web_console import build_system_status

router = APIRouter(tags=["system"])


class LocalPilotAnswerSmokeRequest(BaseModel):
    provider: str
    model: str | None = None
    config: dict[str, Any] | None = None


class LocalPilotModelHealthRequest(BaseModel):
    provider: str
    model: str | None = None
    config: dict[str, Any] | None = None


@router.get("/health", response_model=None)
def health(
    settings: Annotated[Settings, Depends(get_settings)],
    database_check: Annotated[Callable[[], None], Depends(get_database_check)],
) -> dict[str, Any] | JSONResponse:
    try:
        database_check()
    except Exception as exc:  # pragma: no cover - covered via contract test
        return JSONResponse(
            status_code=503,
            content={
                "status": "unhealthy",
                "app": "ok",
                "db": "error",
                "detail": str(exc),
                "reranker": build_reranker_health(settings),
                "version": __version__,
            },
        )

    return {
        "status": "healthy",
        "app": "ok",
        "db": "connected",
        "reranker": build_reranker_health(settings),
        "version": __version__,
    }


@router.get("/system/status", response_model=None)
def system_status(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    database_check: Annotated[Callable[[], None], Depends(get_database_check)],
) -> dict[str, Any]:
    detail: str | None = None
    database_ok = True
    try:
        database_check()
    except Exception as exc:  # pragma: no cover - exercised via route contract tests
        detail = str(exc)
        database_ok = False
    return build_system_status(
        session,
        settings=settings,
        vector_health=get_vector_backend_health(session, settings),
        database_ok=database_ok,
        database_detail=detail,
    )


@router.get("/local-pilot/status", response_model=None)
def local_pilot_status() -> dict[str, Any]:
    return build_local_pilot_status().model_dump()


@router.post("/local-pilot/answer-smoke", response_model=None)
def local_pilot_answer_smoke(
    request: LocalPilotAnswerSmokeRequest,
) -> dict[str, Any] | JSONResponse:
    try:
        return run_answer_smoke(
            provider=request.provider,
            model=request.model,
            config=request.config,
        )
    except ModelConfigError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": exc.code, "message": str(exc), "field": exc.field},
        )


@router.post("/local-pilot/model-health", response_model=None)
def local_pilot_model_health(
    request: LocalPilotModelHealthRequest,
) -> dict[str, Any] | JSONResponse:
    try:
        return model_health_check(
            provider=request.provider,
            model=request.model,
            config=request.config,
        )
    except ModelConfigError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": exc.code, "message": str(exc), "field": exc.field},
        )
