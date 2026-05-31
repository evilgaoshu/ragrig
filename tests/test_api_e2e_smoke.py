from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ragrig.auth import DEFAULT_WORKSPACE_ID
from ragrig.config import Settings
from ragrig.db.models import Base
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.main import create_app
from ragrig.repositories import get_knowledge_base_by_name

pytestmark = [pytest.mark.integration, pytest.mark.smoke]


def _session_factory(database_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def test_api_auth_write_retrieval_and_rate_limit_smoke(tmp_path) -> None:
    factory = _session_factory(tmp_path / "api-smoke.db")
    settings = Settings(
        ragrig_auth_enabled=True,
        ragrig_rate_limit_enabled=True,
        ragrig_rate_limit_search_rpm=1,
        ragrig_rate_limit_burst_factor=1.0,
    )
    app = create_app(
        check_database=lambda: None,
        session_factory=factory,
        settings=settings,
    )
    client = TestClient(app)

    register = client.post(
        "/auth/register",
        json={"email": "smoke-owner@example.com", "password": "hunter2hunter2"},
    )
    assert register.status_code == 201
    token = register.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    create_kb = client.post("/knowledge-bases", json={"name": "smoke-kb"}, headers=headers)
    assert create_kb.status_code == 201
    with factory() as session:
        assert get_knowledge_base_by_name(
            session,
            "smoke-kb",
            workspace_id=DEFAULT_WORKSPACE_ID,
        )

    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.txt").write_text("authenticated retrieval target phrase", encoding="utf-8")
    with factory() as session:
        ingest_local_directory(session=session, knowledge_base_name="smoke-kb", root_path=docs)
        index_knowledge_base(session=session, knowledge_base_name="smoke-kb", chunk_size=500)

    search_payload = {
        "knowledge_base": "smoke-kb",
        "query": "authenticated retrieval target phrase",
        "top_k": 1,
    }
    search = client.post("/retrieval/search", json=search_payload, headers=headers)
    assert search.status_code == 200
    body = search.json()
    assert body["total_results"] == 1
    assert body["results"][0]["document_uri"].endswith("guide.txt")

    limited = client.post("/retrieval/search", json=search_payload, headers=headers)
    assert limited.status_code == 429
    assert "Retry-After" in limited.headers
