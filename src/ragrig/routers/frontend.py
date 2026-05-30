from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

router = APIRouter(tags=["frontend"])
DIST_ROOT = Path(__file__).resolve().parents[1] / "static" / "dist"


@router.get("/ragrig-icon.svg", include_in_schema=False)
def react_icon() -> FileResponse:
    return FileResponse(DIST_ROOT / "ragrig-icon.svg")


@router.get("/", include_in_schema=False)
@router.get("/{path:path}", include_in_schema=False)
def react_app(path: str = "") -> FileResponse:
    if path == "console" or path == "app" or path.startswith("app/"):
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(DIST_ROOT / "index.html")


def configure_frontend(app: FastAPI) -> None:
    if not DIST_ROOT.exists():
        return
    app.mount("/assets", StaticFiles(directory=DIST_ROOT / "assets"), name="react-assets")
    app.include_router(router)
