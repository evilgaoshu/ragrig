"""Root path should 302 → /app when the React bundle is present."""

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


@pytest.mark.skipif(
    not DIST_ROOT.exists(),
    reason="React dist not built locally (CI builds it inside the docker image)",
)
def test_root_redirects_to_app(tmp_path: Path) -> None:
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
    assert resp.status_code == 302
    assert resp.headers["location"] == "/app"
