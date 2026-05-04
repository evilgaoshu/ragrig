from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.db.models import Base, DocumentVersion
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.main import create_app


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def _create_file_session_factory(database_path) -> Callable[[], Session]:
    engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
    Base.metadata.create_all(engine)

    def _factory() -> Session:
        return Session(engine, expire_on_commit=False)

    return _factory


def _seed_documents(tmp_path, files: dict[str, str]):
    docs = tmp_path / "docs"
    docs.mkdir()
    for name, content in files.items():
        (docs / name).write_text(content, encoding="utf-8")
    return docs


@pytest.mark.anyio
async def test_console_route_serves_lightweight_web_console(tmp_path) -> None:
    database_path = tmp_path / "web-console-page.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/console")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "RAGRig Web Console" in response.text
    assert "Knowledge Bases" in response.text
    assert "Retrieval Lab" in response.text


@pytest.mark.anyio
async def test_console_api_exposes_real_operations_data(tmp_path) -> None:
    database_path = tmp_path / "web-console-data.db"
    session_factory = _create_file_session_factory(database_path)
    docs = _seed_documents(
        tmp_path,
        {
            "guide.md": "# Guide\n\nretrieval ready guide",
            "notes.txt": "ops notes for the console",
        },
    )

    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local", chunk_size=500)
        latest_version = session.scalars(
            select(DocumentVersion).order_by(DocumentVersion.version_number.desc())
        ).first()

    assert latest_version is not None

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        system_status = await client.get("/system/status")
        knowledge_bases = await client.get("/knowledge-bases")
        sources = await client.get("/sources")
        pipeline_runs = await client.get("/pipeline-runs")
        documents = await client.get("/documents")
        chunks = await client.get(f"/document-versions/{latest_version.id}/chunks")
        models = await client.get("/models")

    assert system_status.status_code == 200
    assert system_status.json()["db"]["dialect"] == "sqlite"
    assert system_status.json()["vector"]["backend"] == "pgvector"
    assert system_status.json()["vector"]["health"]["healthy"] is True
    assert knowledge_bases.status_code == 200
    assert knowledge_bases.json()["items"][0]["name"] == "fixture-local"
    assert knowledge_bases.json()["items"][0]["document_count"] == 2
    assert knowledge_bases.json()["items"][0]["chunk_count"] >= 2
    assert (
        knowledge_bases.json()["items"][0]["latest_pipeline_run"]["run_type"] == "chunk_embedding"
    )
    assert sources.status_code == 200
    assert sources.json()["items"][0]["kind"] == "local_directory"
    assert pipeline_runs.status_code == 200
    assert {item["run_type"] for item in pipeline_runs.json()["items"]} == {
        "local_ingestion",
        "chunk_embedding",
    }
    assert documents.status_code == 200
    assert documents.json()["items"][0]["latest_version"]["parser_name"] in {
        "markdown",
        "plaintext",
    }
    assert chunks.status_code == 200
    assert chunks.json()["items"][0]["chunk_index"] == 0
    assert models.status_code == 200
    assert models.json()["embedding_profiles"][0]["provider"] == "deterministic-local"
    assert models.json()["registry_shell"]["llm"]["status"] == "disabled"


@pytest.mark.anyio
async def test_console_api_returns_empty_states_without_seed_data(tmp_path) -> None:
    database_path = tmp_path / "web-console-empty.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        knowledge_bases = await client.get("/knowledge-bases")
        documents = await client.get("/documents")
        models = await client.get("/models")

    assert knowledge_bases.status_code == 200
    assert knowledge_bases.json() == {"items": []}
    assert documents.status_code == 200
    assert documents.json() == {"items": []}
    assert models.status_code == 200
    assert models.json()["embedding_profiles"] == []


@pytest.mark.anyio
async def test_system_status_reports_alembic_revision_when_revision_table_exists(tmp_path) -> None:
    database_path = tmp_path / "web-console-revision.db"
    session_factory = _create_file_session_factory(database_path)
    with session_factory() as session:
        session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        session.execute(text("INSERT INTO alembic_version (version_num) VALUES ('20260503_0001')"))
        session.commit()

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/system/status")

    assert response.status_code == 200
    assert response.json()["db"]["alembic_revision"] == "20260503_0001"
    assert response.json()["vector"]["status"] == "healthy"
