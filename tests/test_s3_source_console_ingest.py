from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

import httpx
import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from ragrig.db.models import Base, Chunk, Document, DocumentVersion, Embedding, PipelineRun
from ragrig.main import create_app
from ragrig.plugins.sources.s3.client import FakeS3Client, FakeS3Object

pytestmark = [pytest.mark.smoke, pytest.mark.slow]


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def _create_file_session_factory(database_path) -> Callable[[], Session]:
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        future=True,
        poolclass=NullPool,
    )
    Base.metadata.create_all(engine)

    def _factory() -> Session:
        return Session(engine, expire_on_commit=False)

    return _factory


def _s3_config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "bucket": "docs",
        "prefix": "team-a",
        "endpoint_url": "http://localhost:9000",
        "region": "us-east-1",
        "use_path_style": True,
        "verify_tls": True,
        "access_key": "env:AWS_ACCESS_KEY_ID",
        "secret_key": "env:AWS_SECRET_ACCESS_KEY",
        "include_patterns": ["*.md", "*.txt"],
        "exclude_patterns": [],
        "max_object_size_mb": 1,
        "page_size": 100,
        "max_retries": 1,
        "connect_timeout_seconds": 5,
        "read_timeout_seconds": 10,
    }
    config.update(overrides)
    return config


def _fake_object(
    key: str,
    body: bytes,
    *,
    etag: str,
    content_type: str = "text/markdown",
) -> FakeS3Object:
    return FakeS3Object(
        key=key,
        body=body,
        etag=etag,
        last_modified=datetime(2026, 5, 15, tzinfo=timezone.utc),
        content_type=content_type,
    )


@pytest.mark.anyio
async def test_s3_console_run_ingest_creates_documents_chunks_and_embeddings(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "actual-access-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "actual-secret-key")
    monkeypatch.setattr(
        "ragrig.plugins.sources.s3.connector.build_boto3_client",
        lambda config: FakeS3Client(
            objects=[
                _fake_object(
                    "team-a/guide.md",
                    b"# Guide\n\nRAGRig local pilot content for S3 ingest.\n",
                    etag="etag-guide-v1",
                )
            ]
        ),
    )

    session_factory = _create_file_session_factory(tmp_path / "s3-console-ingest.db")
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/sources/run-ingest",
            json={
                "plugin_id": "source.s3",
                "knowledge_base": "fixture-s3-console",
                "config": _s3_config(),
            },
        )

        assert response.status_code == 202
        assert "actual-secret-key" not in response.text
        payload = response.json()
        assert payload["plugin_id"] == "source.s3"
        assert payload["knowledge_base"] == "fixture-s3-console"
        assert payload["ingestion"]["created_versions"] == 1
        assert payload["ingestion"]["failed_count"] == 0
        assert payload["indexing"]["chunk_count"] >= 1
        assert payload["indexing"]["embedding_count"] >= 1

    with session_factory() as session:
        document = session.scalars(select(Document)).one()
        version = session.scalars(select(DocumentVersion)).one()
        chunk = session.scalars(select(Chunk)).one()
        embedding = session.scalars(select(Embedding)).one()
        runs = session.scalars(select(PipelineRun).order_by(PipelineRun.started_at.asc())).all()

        assert document.uri == "s3://docs/team-a/guide.md"
        assert document.metadata_json["object_key"] == "team-a/guide.md"
        assert version.parser_config_json["plugin_id"] == "parser.markdown"
        assert "RAGRig local pilot content" in chunk.text
        assert embedding.provider == "deterministic-local"
        assert [run.run_type for run in runs] == ["s3_ingest", "chunk_embedding"]

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        chunks_response = await client.get(f"/document-versions/{version.id}/chunks")
        assert chunks_response.status_code == 200
        chunks = chunks_response.json()["items"]
        assert chunks[0]["text"] == chunk.text


@pytest.mark.anyio
async def test_s3_console_run_ingest_reports_missing_env_without_leaking_values(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "actual-secret-key")

    session_factory = _create_file_session_factory(tmp_path / "s3-console-ingest-error.db")
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/sources/run-ingest",
            json={
                "plugin_id": "source.s3",
                "knowledge_base": "fixture-s3-console",
                "config": _s3_config(),
            },
        )

    assert response.status_code == 400
    assert "actual-secret-key" not in response.text
    assert response.json()["error"]


@pytest.mark.anyio
async def test_console_exposes_s3_run_ingest_controls(tmp_path) -> None:
    session_factory = _create_file_session_factory(tmp_path / "s3-console-html.db")
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/console")

    assert response.status_code == 200
    assert "Run ingest" in response.text
    assert "/sources/run-ingest" in response.text
    assert "runSourceIngestForm" in response.text
    assert "source-ingest-result" in response.text
