from collections.abc import Callable

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from ragrig import __version__
from ragrig.config import get_settings
from ragrig.health import create_database_check


def create_app(check_database: Callable[[], None] | None = None) -> FastAPI:
    settings = get_settings()
    database_check = check_database or create_database_check(settings)

    app = FastAPI(title="RAGRig", version=__version__)

    @app.get("/health", response_model=None)
    def health() -> dict[str, str] | JSONResponse:
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
                    "version": __version__,
                },
            )

        return {
            "status": "healthy",
            "app": "ok",
            "db": "connected",
            "version": __version__,
        }

    return app


app = create_app()
