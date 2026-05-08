from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.config import Settings
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
    assert "Plugin Readiness" in response.text
    assert "Vector Backend Readiness" in response.text
    assert "Plugin / Data Source Setup Wizard" in response.text
    assert "Validate Config" in response.text
    assert "no raw secrets" in response.text
    assert "repeat(auto-fit, minmax(150px, 1fr))" in response.text
    assert "Backend · metric · score semantics" in response.text


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
        plugins = await client.get("/plugins")

    assert system_status.status_code == 200
    assert system_status.json()["db"]["dialect"] == "sqlite"
    assert system_status.json()["vector"]["backend"] == "pgvector"
    assert system_status.json()["vector"]["health"]["healthy"] is True
    assert system_status.json()["vector"]["health"]["dependency_status"] == "ready"
    assert system_status.json()["vector"]["health"]["provider"] == "deterministic-local"
    assert system_status.json()["vector"]["health"]["model"] == "hash-8d"
    assert system_status.json()["vector"]["health"]["total_vectors"] >= 2
    assert system_status.json()["vector"]["health"]["score_semantics"] == (
        "pgvector uses cosine distance; retrieval score is 1 - distance."
    )
    assert system_status.json()["vector"]["health"]["collections"][0]["backend"] == "pgvector"
    assert system_status.json()["vector"]["health"]["collections"][0]["metadata"]["provider"] == (
        "deterministic-local"
    )
    assert knowledge_bases.status_code == 200
    assert knowledge_bases.json()["items"][0]["name"] == "fixture-local"
    assert knowledge_bases.json()["items"][0]["vector_backend"] == "pgvector"
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
    provider_names = {item["name"] for item in models.json()["registered_providers"]}
    assert {
        "deterministic-local",
        "model.ollama",
        "model.lm_studio",
        "model.openai",
        "model.vertex_ai",
        "model.bedrock",
        "embedding.bge",
        "reranker.bge",
    } <= provider_names
    llm_shell = models.json()["registry_shell"]["llm"]
    assert llm_shell["status"] == "ready"
    assert {"model.lm_studio", "model.ollama"} <= set(llm_shell["providers"])
    assert {"model.openai", "model.vertex_ai", "model.bedrock"} <= set(llm_shell["providers"])
    assert models.json()["registry_shell"]["reranker"]["status"] == "ready"
    assert plugins.status_code == 200
    plugin_ids = {item["plugin_id"] for item in plugins.json()["items"]}
    assert "source.local" in plugin_ids
    assert "source.s3" in plugin_ids
    assert "sink.object_storage" in plugin_ids
    assert "model.ollama" in plugin_ids
    assert "model.openai" in plugin_ids
    s3_plugin = next(item for item in plugins.json()["items"] if item["plugin_id"] == "source.s3")
    assert s3_plugin["example_config"]["bucket"] == "docs"
    assert s3_plugin["docs_reference"] == "docs/specs/ragrig-s3-source-plugin-spec.md"


@pytest.mark.anyio
async def test_plugin_config_validation_accepts_registry_example_configs(tmp_path) -> None:
    database_path = tmp_path / "web-console-plugin-validation.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        plugins = await client.get("/plugins")
        configurable_plugins = [
            item for item in plugins.json()["items"] if item["configurable"] is True
        ]
        assert configurable_plugins
        for plugin in configurable_plugins:
            response = await client.post(
                f"/plugins/{plugin['plugin_id']}/validate-config",
                json={"config": plugin["example_config"]},
            )
            assert response.status_code == 200, (plugin["plugin_id"], response.text)
            payload = response.json()
            assert payload["valid"] is True
            assert payload["plugin_id"] == plugin["plugin_id"]
            for key, value in plugin["example_config"].items():
                assert payload["config"][key] == value
            assert "next_steps" in payload
            assert "missing_dependencies" in payload


@pytest.mark.anyio
async def test_plugin_config_validation_rejects_unsafe_or_malformed_payloads(tmp_path) -> None:
    database_path = tmp_path / "web-console-plugin-validation-failures.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        raw_secret = await client.post(
            "/plugins/source.s3/validate-config",
            json={
                "config": {
                    "bucket": "docs",
                    "access_key": "literal-access-key",
                    "secret_key": "env:AWS_SECRET_ACCESS_KEY",
                }
            },
        )
        unknown_plugin = await client.post(
            "/plugins/source.unknown/validate-config",
            json={"config": {}},
        )
        malformed_config = await client.post(
            "/plugins/source.local/validate-config",
            json={"config": []},
        )
        non_configurable = await client.post(
            "/plugins/preview.office/validate-config",
            json={"config": {"enabled": True}},
        )
        malformed_json = await client.post(
            "/plugins/source.local/validate-config",
            content="{",
            headers={"Content-Type": "application/json"},
        )
        null_body = await client.post(
            "/plugins/source.local/validate-config",
            json=None,
        )

    assert raw_secret.status_code == 400
    assert raw_secret.json()["error"]["code"] == "raw_secret_not_allowed"
    assert "env:VARIABLE_NAME" in raw_secret.json()["error"]["message"]
    assert unknown_plugin.status_code == 400
    assert unknown_plugin.json()["error"]["code"] == "plugin_not_found"
    assert malformed_config.status_code == 400
    assert malformed_config.json()["error"]["code"] == "malformed_request"
    assert non_configurable.status_code == 400
    assert non_configurable.json()["error"]["code"] == "plugin_config_invalid"
    assert malformed_json.status_code == 400
    assert malformed_json.json()["error"]["code"] == "malformed_request"
    assert null_body.status_code == 400
    assert null_body.json()["error"]["code"] == "malformed_request"


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
        plugins = await client.get("/plugins")

    assert knowledge_bases.status_code == 200
    assert knowledge_bases.json() == {"items": []}
    assert documents.status_code == 200
    assert documents.json() == {"items": []}
    assert models.status_code == 200
    assert models.json()["embedding_profiles"] == []
    assert "model.ollama" in {item["name"] for item in models.json()["registered_providers"]}
    assert "model.openai" in {item["name"] for item in models.json()["registered_providers"]}
    assert plugins.status_code == 200
    assert any(item["plugin_id"] == "vector.pgvector" for item in plugins.json()["items"])


@pytest.mark.anyio
async def test_system_status_reports_qdrant_dependency_gap_without_breaking_console(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "web-console-qdrant-missing.db"
    session_factory = _create_file_session_factory(database_path)
    monkeypatch.setitem(__import__("sys").modules, "qdrant_client.http.models", None)
    monkeypatch.setitem(__import__("sys").modules, "qdrant_client", None)
    app = create_app(
        check_database=lambda: None,
        session_factory=session_factory,
        settings=Settings(vector_backend="qdrant"),
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        status_response = await client.get("/system/status")
        console_response = await client.get("/console")

    assert console_response.status_code == 200
    assert status_response.status_code == 200
    payload = status_response.json()["vector"]
    assert payload["backend"] == "qdrant"
    assert payload["status"] == "degraded"
    assert payload["health"]["healthy"] is False
    assert payload["health"]["dependency_status"] == "missing dependency"
    assert payload["health"]["error"] == "Missing dependency: qdrant-client is not installed."
    assert payload["health"]["collections"] == []


@pytest.mark.anyio
async def test_system_status_reports_unreachable_qdrant_without_white_screen(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "web-console-qdrant-unreachable.db"
    session_factory = _create_file_session_factory(database_path)

    class BrokenBackend:
        def health(self, session: Session):
            raise RuntimeError("Qdrant unreachable at configured endpoint.")

    monkeypatch.setattr("ragrig.vectorstore.get_vector_backend", lambda settings: BrokenBackend())
    app = create_app(
        check_database=lambda: None,
        session_factory=session_factory,
        settings=Settings(
            vector_backend="qdrant",
            qdrant_url="http://user:secret@localhost:6333?api_key=secret",
        ),
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        status_response = await client.get("/system/status")
        console_response = await client.get("/console")
        knowledge_bases = await client.get("/knowledge-bases")

    assert console_response.status_code == 200
    assert status_response.status_code == 200
    payload = status_response.json()["vector"]
    assert payload["backend"] == "qdrant"
    assert payload["status"] == "error"
    assert payload["health"]["dependency_status"] == "unreachable"
    assert payload["health"]["error"] == "Qdrant unreachable at configured endpoint."
    assert payload["health"]["details"]["url"] == "http://localhost:6333"
    assert knowledge_bases.status_code == 200
    assert knowledge_bases.json()["items"] == []


def test_import_guard_includes_provider_registry_as_core_module() -> None:
    from tests.test_import_guard import CORE_PATHS, REPO_ROOT

    assert REPO_ROOT / "src/ragrig/providers" in CORE_PATHS


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
    assert response.json()["vector"]["health"]["collections"] == []
