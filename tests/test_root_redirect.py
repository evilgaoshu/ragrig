"""Root path should serve the React console when the bundle is present."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ragrig.config import Settings
from ragrig.db.models import Base
from ragrig.main import create_app

pytestmark = pytest.mark.integration

DIST_ROOT = Path(__file__).resolve().parents[1] / "src" / "ragrig" / "static" / "dist"


def test_root_serves_react_app(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'root.db'}", future=True)
    Base.metadata.create_all(engine)

    def sf() -> Session:
        return Session(engine, expire_on_commit=False)

    app = create_app(
        check_database=lambda: None,
        session_factory=sf,
        settings=Settings(ragrig_auth_enabled=False),
    )
    client = TestClient(app, follow_redirects=False)
    resp = client.get("/")
    if DIST_ROOT.exists():
        assert resp.status_code == 200
        assert "RAGRig Console" in resp.text
    else:
        assert resp.status_code == 404


def test_console_route_is_removed(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'console.db'}", future=True)
    Base.metadata.create_all(engine)

    def sf() -> Session:
        return Session(engine, expire_on_commit=False)

    app = create_app(
        check_database=lambda: None,
        session_factory=sf,
        settings=Settings(ragrig_auth_enabled=False),
    )
    client = TestClient(app, follow_redirects=False)

    resp = client.get("/console")

    assert resp.status_code == 404


def test_app_prefixed_paths_are_removed(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'app-prefix.db'}", future=True)
    Base.metadata.create_all(engine)

    def sf() -> Session:
        return Session(engine, expire_on_commit=False)

    app = create_app(
        check_database=lambda: None,
        session_factory=sf,
        settings=Settings(ragrig_auth_enabled=False),
    )
    client = TestClient(app, follow_redirects=False)

    assert client.get("/app").status_code == 404
    assert client.get("/app/login").status_code == 404
