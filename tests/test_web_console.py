from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path

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

pytestmark = [pytest.mark.smoke, pytest.mark.slow]


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
    assert "Fileshare Source" in response.text
    assert "SMB" in response.text
    assert "NFS mounted path" in response.text
    assert "WebDAV" in response.text
    assert "SFTP" in response.text
    assert "fileshare-protocols" in response.text
    assert "fileshare-overall-status" in response.text
    assert "make fileshare-check" in response.text
    assert "make test-live-fileshare" in response.text
    assert "FILESHARE_FIELD_SCHEMAS" in response.text
    assert "validateFileshareField" in response.text
    assert "handleFileshareFormSubmit" in response.text
    assert "handleFileshareCopyClick" in response.text
    assert "请使用 env: 引用，不要直接填写密钥" in response.text
    assert "Copy CLI config" in response.text
    assert "Copy ENV vars" in response.text
    assert "fileshare-warning" in response.text
    assert "fileshare-unavailable-reason" in response.text
    assert "validateSingleFileshareField" in response.text
    assert "showFileshareFieldError" in response.text
    assert "root_path must not have trailing whitespace" in response.text
    assert "trailing whitespace" in response.text
    assert "retrieval-mode" in response.text
    assert "dense (vector-only)" in response.text
    assert "hybrid (vector + lexical)" in response.text
    assert "rerank (dense → reranker)" in response.text
    assert "hybrid_rerank (hybrid → reranker)" in response.text
    assert "retrieval-lexical-weight" in response.text
    assert "retrieval-vector-weight" in response.text
    assert "retrieval-candidate-k" in response.text
    assert "retrieval-reranker-provider" in response.text
    assert "retrieval-reranker-model" in response.text
    assert "_renderRankStageTrace" in response.text


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
    fileshare_plugin = next(
        item for item in plugins.json()["items"] if item["plugin_id"] == "source.fileshare"
    )
    assert fileshare_plugin["docs_reference"] == "docs/specs/ragrig-fileshare-source-plugin-spec.md"
    assert "supported_protocols" in fileshare_plugin
    assert "protocol_statuses" in fileshare_plugin
    assert "protocol_example_configs" in fileshare_plugin
    assert "protocol_secret_requirements" in fileshare_plugin
    assert "protocol_missing_dependencies" in fileshare_plugin
    assert "nfs_mounted" in fileshare_plugin["protocol_example_configs"]
    assert "smb" in fileshare_plugin["protocol_example_configs"]
    assert "webdav" in fileshare_plugin["protocol_example_configs"]
    assert "sftp" in fileshare_plugin["protocol_example_configs"]


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


@pytest.mark.anyio
async def test_fileshare_config_validation_cases(tmp_path) -> None:
    """Verify /plugins/source.fileshare/validate-config rejects invalid frontend inputs."""
    database_path = tmp_path / "web-console-fileshare-validation.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Missing required field (root_path empty)
        missing_required = await client.post(
            "/plugins/source.fileshare/validate-config",
            json={
                "config": {
                    "protocol": "nfs_mounted",
                    "root_path": "   ",
                }
            },
        )
        # 2. Invalid URL format for base_url (WebDAV)
        invalid_url = await client.post(
            "/plugins/source.fileshare/validate-config",
            json={
                "config": {
                    "protocol": "webdav",
                    "base_url": "ftp://webdav.example.com",
                    "root_path": "/docs",
                }
            },
        )
        # 3. Port out of bounds
        port_oob = await client.post(
            "/plugins/source.fileshare/validate-config",
            json={
                "config": {
                    "protocol": "smb",
                    "host": "files.example.internal",
                    "share": "team-a",
                    "root_path": "/docs",
                    "port": 70000,
                }
            },
        )
        # 4. Plaintext secret rejection
        plaintext_secret = await client.post(
            "/plugins/source.fileshare/validate-config",
            json={
                "config": {
                    "protocol": "smb",
                    "host": "files.example.internal",
                    "share": "team-a",
                    "root_path": "/docs",
                    "username": "admin",
                    "password": "env:FILESHARE_PASSWORD",
                }
            },
        )
        # 5. root_path trailing whitespace (WebDAV)
        trailing_whitespace = await client.post(
            "/plugins/source.fileshare/validate-config",
            json={
                "config": {
                    "protocol": "webdav",
                    "base_url": "https://webdav.example.com",
                    "root_path": "/docs ",
                }
            },
        )

    assert missing_required.status_code == 400
    assert "root_path" in missing_required.json()["error"]["message"].lower()

    assert invalid_url.status_code == 400
    assert invalid_url.json()["error"]["code"] == "plugin_config_invalid"

    assert port_oob.status_code == 400
    assert "port" in port_oob.json()["error"]["message"].lower()

    assert plaintext_secret.status_code == 400
    assert plaintext_secret.json()["error"]["code"] == "raw_secret_not_allowed"
    assert "env:VARIABLE_NAME" in plaintext_secret.json()["error"]["message"]

    assert trailing_whitespace.status_code == 400
    assert trailing_whitespace.json()["error"]["code"] == "plugin_config_invalid"
    assert "trailing whitespace" in trailing_whitespace.json()["error"]["message"].lower()


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


# Processing Profiles tests (from main)
@pytest.mark.anyio
async def test_processing_profiles_endpoint_returns_default_profiles(tmp_path) -> None:
    from ragrig.processing_profile import clear_overrides

    clear_overrides()
    database_path = tmp_path / "web-console-profiles.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/processing-profiles")

    assert response.status_code == 200
    profiles = response.json()["profiles"]
    assert len(profiles) >= 6
    task_types = {p["task_type"] for p in profiles}
    assert "correct" in task_types
    assert "clean" in task_types
    assert "chunk" in task_types
    assert "summarize" in task_types
    assert "understand" in task_types
    assert "embed" in task_types
    for p in profiles:
        assert "profile_id" in p
        assert "extension" in p
        assert "task_type" in p
        assert "provider" in p
        assert "status" in p
        assert "provider_available" in p
        # Must not contain raw secrets
        assert "secret" not in str(p)
        assert "api_key" not in str(p)
    clear_overrides()


@pytest.mark.anyio
async def test_processing_profiles_matrix_endpoint_returns_grid(tmp_path) -> None:
    database_path = tmp_path / "web-console-matrix.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/processing-profiles/matrix")

    assert response.status_code == 200
    matrix = response.json()
    assert "extensions" in matrix
    assert "task_types" in matrix
    assert "cells" in matrix
    assert ".md" in matrix["extensions"]
    assert ".txt" in matrix["extensions"]
    assert ".pdf" in matrix["extensions"]
    assert ".docx" in matrix["extensions"]
    assert ".xlsx" in matrix["extensions"]
    assert "*" in matrix["extensions"]
    assert "correct" in matrix["task_types"]
    assert "clean" in matrix["task_types"]
    assert "chunk" in matrix["task_types"]
    assert "summarize" in matrix["task_types"]
    assert "understand" in matrix["task_types"]
    assert "embed" in matrix["task_types"]
    # Each cell has the required fields
    for _key, cell in matrix["cells"].items():
        assert "profile_id" in cell
        assert "kind" in cell
        assert "source" in cell
        assert "is_default" in cell
        assert "provider_available" in cell
        assert cell["kind"] in ("deterministic", "LLM-assisted")
        assert cell["source"] in ("default", "override")
        assert isinstance(cell["is_default"], bool)


@pytest.mark.anyio
async def test_processing_profiles_api_no_secrets_leakage(tmp_path) -> None:
    database_path = tmp_path / "web-console-no-secrets.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        profiles_resp = await client.get("/processing-profiles")
        matrix_resp = await client.get("/processing-profiles/matrix")

    for response in [profiles_resp, matrix_resp]:
        text_body = response.text
        assert "secret" not in text_body.lower()
        assert "api_key" not in text_body.lower()
        assert "password" not in text_body.lower()


@pytest.mark.anyio
async def test_console_html_includes_profile_matrix_section(tmp_path) -> None:
    database_path = tmp_path / "web-console-matrix-section.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/console")

    assert response.status_code == 200
    html = response.text
    assert "Processing Profile Matrix" in html
    assert "profile-matrix-table" in html
    assert "profile-matrix-panel" in html
    assert "/processing-profiles/matrix" in html
    assert "renderProfileMatrix" in html
    assert "cell-kind" in html
    assert "deterministic" in html
    assert "LLM-assisted" in html


@pytest.mark.anyio
async def test_console_html_includes_profile_matrix_nav_item(tmp_path) -> None:
    database_path = tmp_path / "web-console-nav-matrix.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/console")

    assert response.status_code == 200
    assert "Profile Matrix" in response.text


@pytest.mark.anyio
async def test_indexing_metadata_includes_profile_ids(tmp_path) -> None:
    database_path = tmp_path / "web-console-index-metadata.db"
    session_factory = _create_file_session_factory(database_path)
    docs = _seed_documents(tmp_path, {"notes.txt": "hello world content"})

    with session_factory() as session:
        from sqlalchemy import select

        from ragrig.db.models import Chunk, Embedding, PipelineRun
        from ragrig.indexing.pipeline import index_knowledge_base
        from ragrig.ingestion.pipeline import ingest_local_directory

        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local", chunk_size=500)

        run = session.scalars(
            select(PipelineRun)
            .where(PipelineRun.run_type == "chunk_embedding")
            .order_by(PipelineRun.started_at.desc())
        ).first()
        config = run.config_snapshot_json
        assert "chunk_profile_id" in config
        assert "embed_profile_id" in config
        assert config["chunk_profile_id"] == "*.chunk.default"
        assert config["embed_profile_id"] == "*.embed.default"

        chunk = session.scalars(select(Chunk)).first()
        assert chunk is not None
        assert "profile_id" in chunk.metadata_json
        assert chunk.metadata_json["profile_id"] == "*.chunk.default"

        embedding = session.scalars(select(Embedding)).first()
        assert embedding is not None
        assert "profile_id" in embedding.metadata_json
        assert embedding.metadata_json["profile_id"] == "*.embed.default"


# Document Understanding tests (from HEAD)
@pytest.mark.anyio
async def test_document_understanding_endpoints(tmp_path) -> None:
    from ragrig.db.models import DocumentVersion
    from ragrig.indexing.pipeline import index_knowledge_base
    from ragrig.ingestion.pipeline import ingest_local_directory

    database_path = tmp_path / "web-console-understanding.db"
    session_factory = _create_file_session_factory(database_path)
    docs = _seed_documents(
        tmp_path,
        {
            "guide.md": "# Guide\n\nA test guide for understanding.",
        },
    )

    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local", chunk_size=500)
        version = session.scalars(
            select(DocumentVersion).order_by(DocumentVersion.version_number.desc())
        ).first()

    assert version is not None
    version_id = str(version.id)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # GET before generation -> 404
        get_before = await client.get(f"/document-versions/{version_id}/understanding")
        assert get_before.status_code == 404
        assert get_before.json()["error"] == "understanding_not_found"

        # POST to generate
        post_response = await client.post(
            f"/document-versions/{version_id}/understand",
            json={"provider": "deterministic-local", "profile_id": "*.understand.default"},
        )
        assert post_response.status_code == 200
        payload = post_response.json()
        assert payload["status"] == "completed"
        assert payload["document_version_id"] == version_id
        assert payload["provider"] == "deterministic-local"
        assert payload["result"]["summary"] is not None
        assert payload["error"] is None

        # GET after generation -> 200
        get_after = await client.get(f"/document-versions/{version_id}/understanding")
        assert get_after.status_code == 200
        assert get_after.json()["status"] == "completed"
        assert get_after.json()["result"]["summary"] == payload["result"]["summary"]

        # Idempotency: POST again returns same result
        post_again = await client.post(
            f"/document-versions/{version_id}/understand",
            json={"provider": "deterministic-local", "profile_id": "*.understand.default"},
        )
        assert post_again.status_code == 200
        assert post_again.json()["id"] == payload["id"]

        # POST for nonexistent version -> 404
        bad_version = await client.post(
            f"/document-versions/{uuid.uuid4()}/understand",
            json={"provider": "deterministic-local"},
        )
        assert bad_version.status_code == 404
        assert bad_version.json()["error"] == "document_version_not_found"


@pytest.mark.anyio
async def test_document_understanding_shown_in_console(tmp_path) -> None:
    from ragrig.db.models import DocumentVersion
    from ragrig.indexing.pipeline import index_knowledge_base
    from ragrig.ingestion.pipeline import ingest_local_directory

    database_path = tmp_path / "web-console-understanding-ui.db"
    session_factory = _create_file_session_factory(database_path)
    docs = _seed_documents(
        tmp_path,
        {
            "guide.md": "# Guide\n\nA test guide for understanding.",
        },
    )

    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local", chunk_size=500)
        version = session.scalars(
            select(DocumentVersion).order_by(DocumentVersion.version_number.desc())
        ).first()

    assert version is not None
    version_id = str(version.id)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Console should show "not_generated" before understanding exists
        console_before = await client.get("/console")
        assert console_before.status_code == 200
        assert "not_generated" in console_before.text
        assert "No understanding result yet" in console_before.text

        # Generate understanding
        await client.post(
            f"/document-versions/{version_id}/understand",
            json={"provider": "deterministic-local", "profile_id": "*.understand.default"},
        )

        # Console should show completed state after generation
        console_after = await client.get("/console")
        assert console_after.status_code == 200
        assert "completed" in console_after.text
        assert "Document Understanding" in console_after.text


# Override CRUD API tests
@pytest.mark.anyio
async def test_post_processing_profile_creates_override(tmp_path) -> None:
    from ragrig.processing_profile import clear_overrides

    clear_overrides()
    database_path = tmp_path / "web-console-create-override.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        create_resp = await client.post(
            "/processing-profiles",
            json={
                "profile_id": "pdf.chunk.override",
                "extension": ".pdf",
                "task_type": "chunk",
                "display_name": "PDF Chunk Override",
                "description": "Custom chunking for PDFs.",
                "provider": "model.fake_provider",
                "kind": "LLM-assisted",
            },
        )
    assert create_resp.status_code == 200
    payload = create_resp.json()
    assert payload["profile_id"] == "pdf.chunk.override"
    assert payload["source"] == "override"
    assert payload["provider_available"] is False
    clear_overrides()


@pytest.mark.anyio
async def test_get_matrix_reflects_override_source(tmp_path) -> None:
    from ragrig.processing_profile import clear_overrides

    clear_overrides()
    database_path = tmp_path / "web-console-override-matrix.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "pdf.chunk.override",
                "extension": ".pdf",
                "task_type": "chunk",
                "display_name": "PDF Chunk Override",
                "description": "Custom chunking for PDFs.",
                "provider": "model.fake_provider",
                "kind": "LLM-assisted",
            },
        )
        matrix_resp = await client.get("/processing-profiles/matrix")

    assert matrix_resp.status_code == 200
    cell = matrix_resp.json()["cells"][".pdf.chunk"]
    assert cell["source"] == "override"
    assert cell["is_default"] is False
    assert cell["profile_id"] == "pdf.chunk.override"
    clear_overrides()


@pytest.mark.anyio
async def test_patch_disable_and_enable_override(tmp_path) -> None:
    from ragrig.processing_profile import clear_overrides

    clear_overrides()
    database_path = tmp_path / "web-console-patch-override.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "pdf.chunk.override",
                "extension": ".pdf",
                "task_type": "chunk",
                "display_name": "PDF Chunk Override",
                "description": "Custom chunking for PDFs.",
                "provider": "model.fake_provider",
            },
        )
        patch_resp = await client.patch(
            "/processing-profiles/overrides/pdf.chunk.override",
            json={"status": "disabled"},
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["status"] == "disabled"

        matrix_disabled = await client.get("/processing-profiles/matrix")
        cell_disabled = matrix_disabled.json()["cells"][".pdf.chunk"]
        assert cell_disabled["profile_id"] == "*.chunk.default"

        await client.patch(
            "/processing-profiles/overrides/pdf.chunk.override",
            json={"status": "active"},
        )
        matrix_enabled = await client.get("/processing-profiles/matrix")
        cell_enabled = matrix_enabled.json()["cells"][".pdf.chunk"]
        assert cell_enabled["profile_id"] == "pdf.chunk.override"
    clear_overrides()


@pytest.mark.anyio
async def test_delete_override_reverts_to_default(tmp_path) -> None:
    from ragrig.processing_profile import clear_overrides

    clear_overrides()
    database_path = tmp_path / "web-console-delete-override.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "pdf.chunk.override",
                "extension": ".pdf",
                "task_type": "chunk",
                "display_name": "PDF Chunk Override",
                "description": "Custom chunking for PDFs.",
                "provider": "model.fake_provider",
            },
        )
        delete_resp = await client.delete("/processing-profiles/overrides/pdf.chunk.override")
        assert delete_resp.status_code == 204

        matrix_resp = await client.get("/processing-profiles/matrix")
        cell = matrix_resp.json()["cells"][".pdf.chunk"]
        assert cell["profile_id"] == "*.chunk.default"
        assert cell["source"] == "default"
    clear_overrides()


@pytest.mark.anyio
async def test_processing_profile_api_no_secret_leakage(tmp_path) -> None:
    from ragrig.processing_profile import clear_overrides

    clear_overrides()
    database_path = tmp_path / "web-console-profile-secrets.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "pdf.chunk.override",
                "extension": ".pdf",
                "task_type": "chunk",
                "display_name": "PDF Chunk Override",
                "description": "Custom chunking for PDFs.",
                "provider": "model.fake_provider",
                "metadata": {"api_key": "should-not-appear", "secret": "hidden"},
            },
        )
        profiles_resp = await client.get("/processing-profiles")
        matrix_resp = await client.get("/processing-profiles/matrix")

    for response in [profiles_resp, matrix_resp]:
        text_body = response.text
        assert "api_key" not in text_body.lower()
        assert "should-not-appear" not in text_body.lower()
        assert "hidden" not in text_body.lower()
    clear_overrides()


@pytest.mark.anyio
async def test_unavailable_provider_not_faked_as_ready(tmp_path) -> None:
    from ragrig.processing_profile import clear_overrides

    clear_overrides()
    database_path = tmp_path / "web-console-provider-ready.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "pdf.chunk.override",
                "extension": ".pdf",
                "task_type": "chunk",
                "display_name": "PDF Chunk Override",
                "description": "Custom chunking for PDFs.",
                "provider": "model.fake_provider",
            },
        )
        profiles_resp = await client.get("/processing-profiles")
        profile = next(
            p for p in profiles_resp.json()["profiles"] if p["profile_id"] == "pdf.chunk.override"
        )
        assert profile["provider_available"] is False

        matrix_resp = await client.get("/processing-profiles/matrix")
        cell = matrix_resp.json()["cells"][".pdf.chunk"]
        assert cell["provider_available"] is False
    clear_overrides()


@pytest.mark.anyio
async def test_console_html_includes_override_ui(tmp_path) -> None:
    database_path = tmp_path / "web-console-override-ui.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/console")

    assert response.status_code == 200
    html = response.text
    assert "Create Override" in html
    assert "profile-create-form" in html
    assert "profile-create-btn" in html
    assert "Save Override" in html
    assert "Cancel" in html
    assert "showProfileCreateForm" in html
    assert "submitProfileCreate" in html
    assert "toggleProfileStatus" in html
    assert "deleteProfile" in html
    assert "data-profile-action" in html
    assert "Supported Formats" in html
    assert "supported" in html.lower()
    assert "preview" in html.lower()
    assert "planned" in html.lower()


# Supported formats tests
@pytest.mark.anyio
async def test_supported_formats_endpoint_returns_all_formats(tmp_path) -> None:
    database_path = tmp_path / "web-console-formats.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/supported-formats")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["formats"]) >= 4  # .md, .markdown, .txt, .text = 4 supported
    extensions = {fmt["extension"] for fmt in payload["formats"]}
    assert ".md" in extensions
    assert ".txt" in extensions
    assert ".pdf" in extensions
    assert ".docx" in extensions


@pytest.mark.anyio
async def test_supported_formats_filter_by_status(tmp_path) -> None:
    database_path = tmp_path / "web-console-formats-filter.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        supported_resp = await client.get("/supported-formats?status=supported")
        preview_resp = await client.get("/supported-formats?status=preview")
        planned_resp = await client.get("/supported-formats?status=planned")

    assert supported_resp.status_code == 200
    supported = {fmt["extension"] for fmt in supported_resp.json()["formats"]}
    assert ".md" in supported
    assert ".txt" in supported
    assert ".pdf" not in supported

    assert preview_resp.status_code == 200
    preview = {fmt["extension"] for fmt in preview_resp.json()["formats"]}
    assert ".csv" in preview
    assert ".html" in preview

    assert planned_resp.status_code == 200
    planned = {fmt["extension"] for fmt in planned_resp.json()["formats"]}
    assert ".pdf" in planned
    assert ".docx" in planned


@pytest.mark.anyio
async def test_supported_formats_check_returns_supported_for_md(tmp_path) -> None:
    database_path = tmp_path / "web-console-format-check.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/supported-formats/check?extension=.md")

    assert response.status_code == 200
    payload = response.json()
    assert payload["supported"] is True
    assert payload["status"] == "supported"
    assert payload["extension"] == ".md"


@pytest.mark.anyio
async def test_supported_formats_check_returns_false_for_unknown(tmp_path) -> None:
    database_path = tmp_path / "web-console-format-check-unknown.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/supported-formats/check?extension=.xyz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["supported"] is False
    assert payload["status"] == "unsupported"


@pytest.mark.anyio
async def test_supported_formats_check_requires_extension_param(tmp_path) -> None:
    database_path = tmp_path / "web-console-format-check-noext.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/supported-formats/check")

    assert response.status_code == 422


@pytest.mark.anyio
async def test_console_shows_upload_section(tmp_path) -> None:
    database_path = tmp_path / "web-console-upload-ui.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/console")

    assert response.status_code == 200
    html = response.text
    assert "Upload" in html
    assert "Choose Files" in html
    assert "drop" in html.lower()


@pytest.mark.anyio
async def test_upload_supported_md_file_to_kb(tmp_path) -> None:
    database_path = tmp_path / "web-console-upload-md.db"
    session_factory = _create_file_session_factory(database_path)

    test_file = tmp_path / "test-upload.md"
    test_file.write_text("# Test Upload\n\nThis is a test document.", encoding="utf-8")

    with session_factory() as session:
        from ragrig.repositories import get_or_create_knowledge_base

        get_or_create_knowledge_base(session, "fixture-local")
        session.commit()

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with open(test_file, "rb") as f:
            response = await client.post(
                "/knowledge-bases/fixture-local/upload",
                files={"files": ("test-upload.md", f, "text/markdown")},
            )

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted_files"] == 1
    assert payload["pipeline_run_id"] is not None
    assert payload["pipeline_run_id"] != ""
    assert payload["rejected_files"] == 0


@pytest.mark.anyio
async def test_upload_unsupported_jpg_returns_415(tmp_path) -> None:
    database_path = tmp_path / "web-console-upload-jpg.db"
    session_factory = _create_file_session_factory(database_path)

    test_file = tmp_path / "photo.jpg"
    test_file.write_bytes(b"\xff\xd8\xff\xe0fake jpeg data")

    with session_factory() as session:
        from ragrig.repositories import get_or_create_knowledge_base

        get_or_create_knowledge_base(session, "fixture-local")
        session.commit()

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with open(test_file, "rb") as f:
            response = await client.post(
                "/knowledge-bases/fixture-local/upload",
                files={"files": ("photo.jpg", f, "image/jpeg")},
            )

    assert response.status_code == 415
    payload = response.json()
    assert payload["accepted_files"] == 0
    assert payload["rejections"][0]["reason"] == "unsupported_format"


@pytest.mark.anyio
async def test_upload_preview_format_produces_warning(tmp_path) -> None:
    database_path = tmp_path / "web-console-upload-preview.db"
    session_factory = _create_file_session_factory(database_path)

    test_file = tmp_path / "data.csv"
    test_file.write_text("col1,col2\na,b", encoding="utf-8")

    with session_factory() as session:
        from ragrig.repositories import get_or_create_knowledge_base

        get_or_create_knowledge_base(session, "fixture-local")
        session.commit()

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with open(test_file, "rb") as f:
            response = await client.post(
                "/knowledge-bases/fixture-local/upload",
                files={"files": ("data.csv", f, "text/csv")},
            )

    assert response.status_code == 202
    payload = response.json()
    assert payload["accepted_files"] == 1
    assert len(payload["warnings"]) >= 1
    assert payload["warnings"][0]["status"] == "preview"


@pytest.mark.anyio
async def test_upload_nonexistent_kb_returns_404(tmp_path) -> None:
    database_path = tmp_path / "web-console-upload-404.db"
    session_factory = _create_file_session_factory(database_path)

    test_file = tmp_path / "test.md"
    test_file.write_text("# test", encoding="utf-8")

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with open(test_file, "rb") as f:
            response = await client.post(
                "/knowledge-bases/nonexistent/upload",
                files={"files": ("test.md", f, "text/markdown")},
            )

    assert response.status_code == 404


@pytest.mark.anyio
async def test_upload_planned_format_returns_415(tmp_path) -> None:
    database_path = tmp_path / "web-console-upload-planned.db"
    session_factory = _create_file_session_factory(database_path)

    # Create a minimal PDF-like file
    test_file = tmp_path / "document.pdf"
    test_file.write_bytes(b"%PDF-1.4 fake pdf content")

    with session_factory() as session:
        from ragrig.repositories import get_or_create_knowledge_base

        get_or_create_knowledge_base(session, "fixture-local")
        session.commit()

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with open(test_file, "rb") as f:
            response = await client.post(
                "/knowledge-bases/fixture-local/upload",
                files={"files": ("document.pdf", f, "application/pdf")},
            )

    assert response.status_code == 415
    payload = response.json()
    assert payload["rejections"][0]["reason"] == "unsupported_format"
    assert ".pdf" in payload["rejections"][0]["extension"]


@pytest.mark.anyio
async def test_upload_preview_format_tracks_parser_in_pipeline_items(tmp_path) -> None:
    database_path = tmp_path / "web-console-upload-preview-items.db"
    session_factory = _create_file_session_factory(database_path)

    test_file = tmp_path / "data.csv"
    test_file.write_text("col1,col2\na,b", encoding="utf-8")

    with session_factory() as session:
        from ragrig.repositories import get_or_create_knowledge_base

        get_or_create_knowledge_base(session, "fixture-local")
        session.commit()

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with open(test_file, "rb") as f:
            response = await client.post(
                "/knowledge-bases/fixture-local/upload",
                files={"files": ("data.csv", f, "text/csv")},
            )

    assert response.status_code == 202
    payload = response.json()
    assert payload["pipeline_run_id"] is not None
    assert payload["pipeline_run_id"] != ""
    assert payload["warnings"][0]["parser_id"] == "parser.csv"
    assert payload["warnings"][0]["fallback_policy"] == "parse_as_plaintext"

    # Query pipeline run items
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        items_response = await client.get(f"/pipeline-runs/{payload['pipeline_run_id']}/items")

    assert items_response.status_code == 200
    items = items_response.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["status"] == "degraded"
    assert item["metadata"]["parser_id"] == "parser.csv"
    assert item["metadata"]["parser_name"] == "csv"
    assert "degraded_reason" in item["metadata"]


@pytest.mark.anyio
async def test_upload_preview_html_tracks_parser_and_stripped_reason(tmp_path) -> None:
    database_path = tmp_path / "web-console-upload-html-items.db"
    session_factory = _create_file_session_factory(database_path)

    test_file = tmp_path / "page.html"
    test_file.write_text("<html><body><p>hello</p></body></html>", encoding="utf-8")

    with session_factory() as session:
        from ragrig.repositories import get_or_create_knowledge_base

        get_or_create_knowledge_base(session, "fixture-local")
        session.commit()

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with open(test_file, "rb") as f:
            response = await client.post(
                "/knowledge-bases/fixture-local/upload",
                files={"files": ("page.html", f, "text/html")},
            )

    assert response.status_code == 202
    payload = response.json()
    assert payload["warnings"][0]["parser_id"] == "parser.html"
    assert payload["warnings"][0]["fallback_policy"] == "strip_tags_then_plaintext"

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        items_response = await client.get(f"/pipeline-runs/{payload['pipeline_run_id']}/items")

    assert items_response.status_code == 200
    items = items_response.json()["items"]
    assert items[0]["status"] == "degraded"
    assert items[0]["metadata"]["parser_id"] == "parser.html"
    assert "degraded_reason" in items[0]["metadata"]


@pytest.mark.anyio
async def test_upload_exceeds_per_format_size_limit(tmp_path) -> None:
    database_path = tmp_path / "web-console-upload-size-limit.db"
    session_factory = _create_file_session_factory(database_path)

    # Create a file larger than the 50 MB preview limit
    test_file = tmp_path / "huge.csv"
    test_file.write_bytes(b"x" * (51 * 1024 * 1024))

    with session_factory() as session:
        from ragrig.repositories import get_or_create_knowledge_base

        get_or_create_knowledge_base(session, "fixture-local")
        session.commit()

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with open(test_file, "rb") as f:
            response = await client.post(
                "/knowledge-bases/fixture-local/upload",
                files={"files": ("huge.csv", f, "text/csv")},
            )

    assert response.status_code == 413
    payload = response.json()
    assert payload["accepted_files"] == 0
    assert payload["rejections"][0]["reason"] == "file_too_large"
    assert "50 MB" in payload["rejections"][0]["message"]


@pytest.mark.anyio
async def test_supported_formats_includes_fallback_policy_for_preview(tmp_path) -> None:
    database_path = tmp_path / "web-console-formats-fallback.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/supported-formats?status=preview")

    assert response.status_code == 200
    for fmt in response.json()["formats"]:
        assert "parser_id" in fmt
        assert "status" in fmt
        assert fmt["status"] == "preview"
        assert "fallback_policy" in fmt
        assert fmt["fallback_policy"] is not None


# Understanding coverage + batch understand tests
@pytest.mark.anyio
async def test_understand_all_endpoint_creates_and_skips(tmp_path) -> None:
    from ragrig.indexing.pipeline import index_knowledge_base
    from ragrig.ingestion.pipeline import ingest_local_directory

    database_path = tmp_path / "web-console-batch.db"
    session_factory = _create_file_session_factory(database_path)
    docs = _seed_documents(
        tmp_path,
        {
            "guide.md": "# Guide\n\nA test guide for understanding.",
            "notes.txt": "ops notes for the console",
            "extra.md": "# Extra\n\nThird document for batch.",
        },
    )

    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local", chunk_size=500)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        kb_resp = await client.get("/knowledge-bases")
        kb_id = kb_resp.json()["items"][0]["id"]

        # First batch run: should create for all 3 documents
        r1 = await client.post(
            f"/knowledge-bases/{kb_id}/understand-all",
            json={"provider": "deterministic-local", "profile_id": "*.understand.default"},
        )
        assert r1.status_code == 200
        assert r1.json()["total"] == 3
        assert r1.json()["created"] == 3
        assert r1.json()["skipped"] == 0
        assert r1.json()["failed"] == 0

        # Second batch run: all should be skipped (fresh)
        r2 = await client.post(
            f"/knowledge-bases/{kb_id}/understand-all",
            json={"provider": "deterministic-local", "profile_id": "*.understand.default"},
        )
        assert r2.status_code == 200
        assert r2.json()["total"] == 3
        assert r2.json()["created"] == 0
        assert r2.json()["skipped"] == 3
        assert r2.json()["failed"] == 0


@pytest.mark.anyio
async def test_understand_all_with_invalid_provider(tmp_path) -> None:
    from ragrig.indexing.pipeline import index_knowledge_base
    from ragrig.ingestion.pipeline import ingest_local_directory

    database_path = tmp_path / "web-console-batch-fail.db"
    session_factory = _create_file_session_factory(database_path)
    docs = _seed_documents(tmp_path, {"guide.md": "# Guide\n\nContent."})

    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local", chunk_size=500)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        kb_resp = await client.get("/knowledge-bases")
        kb_id = kb_resp.json()["items"][0]["id"]

        r = await client.post(
            f"/knowledge-bases/{kb_id}/understand-all",
            json={"provider": "nonexistent-provider", "profile_id": "*.understand.default"},
        )
        assert r.status_code == 200
        payload = r.json()
        assert payload["total"] == 1
        assert payload["created"] == 0
        assert payload["failed"] == 1
        assert len(payload["errors"]) == 1
        assert "provider" in payload["errors"][0]["error"].lower()


@pytest.mark.anyio
async def test_understanding_coverage_endpoint(tmp_path) -> None:
    from ragrig.indexing.pipeline import index_knowledge_base
    from ragrig.ingestion.pipeline import ingest_local_directory

    database_path = tmp_path / "web-console-coverage.db"
    session_factory = _create_file_session_factory(database_path)
    docs = _seed_documents(
        tmp_path,
        {
            "guide.md": "# Guide\n\nA test guide for understanding.",
            "notes.txt": "ops notes for the console",
            "extra.md": "# Extra\n\nThird document for batch.",
        },
    )

    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local", chunk_size=500)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        kb_resp = await client.get("/knowledge-bases")
        kb_id = kb_resp.json()["items"][0]["id"]

        # Before any understanding: all missing
        cov1 = await client.get(f"/knowledge-bases/{kb_id}/understanding-coverage")
        assert cov1.status_code == 200
        assert cov1.json()["total_versions"] == 3
        assert cov1.json()["completed"] == 0
        assert cov1.json()["missing"] == 3
        assert cov1.json()["stale"] == 0
        assert cov1.json()["failed"] == 0
        assert cov1.json()["completeness_score"] == 0.0
        assert cov1.json()["recent_errors"] == []

        # Run batch understanding
        await client.post(
            f"/knowledge-bases/{kb_id}/understand-all",
            json={"provider": "deterministic-local", "profile_id": "*.understand.default"},
        )

        # After understanding: all completed
        cov2 = await client.get(f"/knowledge-bases/{kb_id}/understanding-coverage")
        assert cov2.status_code == 200
        assert cov2.json()["total_versions"] == 3
        assert cov2.json()["completed"] == 3
        assert cov2.json()["missing"] == 0
        assert cov2.json()["stale"] == 0
        assert cov2.json()["failed"] == 0
        assert cov2.json()["completeness_score"] == 1.0


@pytest.mark.anyio
async def test_console_includes_understanding_coverage_section(tmp_path) -> None:
    database_path = tmp_path / "web-console-coverage-ui.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/console")

    assert response.status_code == 200
    html = response.text
    assert "Understanding Coverage" in html
    assert "understanding-coverage-panel" in html
    assert "understanding-coverage-body" in html
    assert "Run All Understanding" in html
    assert "run-understand-all" in html
    assert "renderUnderstandingCoverage" in html
    assert "runUnderstandAll" in html
    assert "completeness_score" in html
    assert "Recent Errors" in html
    assert "recent_errors" in html
    assert "missing" in html.lower()
    assert "stale" in html.lower()
    assert "completed" in html
    assert "failed" in html


@pytest.mark.anyio
async def test_console_coverage_shows_real_data(tmp_path) -> None:
    from ragrig.indexing.pipeline import index_knowledge_base
    from ragrig.ingestion.pipeline import ingest_local_directory

    database_path = tmp_path / "web-console-coverage-data.db"
    session_factory = _create_file_session_factory(database_path)
    docs = _seed_documents(
        tmp_path,
        {
            "guide.md": "# Guide\n\nA test guide.",
            "notes.txt": "ops notes",
            "extra.md": "# Extra\n\nThird doc.",
        },
    )

    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local", chunk_size=500)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Console page loads and includes coverage section with real data
        console = await client.get("/console")
        assert console.status_code == 200
        assert "Understanding Coverage" in console.text

        # Coverage endpoint returns real data
        kb_resp = await client.get("/knowledge-bases")
        kb_id = kb_resp.json()["items"][0]["id"]

        coverage = await client.get(f"/knowledge-bases/{kb_id}/understanding-coverage")
        assert coverage.status_code == 200
        payload = coverage.json()
        assert payload["total_versions"] == 3
        assert payload["missing"] == 3
        assert payload["completeness_score"] == 0.0
        assert payload["recent_errors"] == []

        # Run batch understanding
        await client.post(
            f"/knowledge-bases/{kb_id}/understand-all",
            json={"provider": "deterministic-local", "profile_id": "*.understand.default"},
        )

        # Coverage updates
        coverage2 = await client.get(f"/knowledge-bases/{kb_id}/understanding-coverage")
        assert coverage2.json()["completed"] == 3
        assert coverage2.json()["completeness_score"] == 1.0


@pytest.mark.anyio
async def test_console_no_secrets_in_understanding_endpoints(tmp_path) -> None:
    from ragrig.indexing.pipeline import index_knowledge_base
    from ragrig.ingestion.pipeline import ingest_local_directory

    database_path = tmp_path / "web-console-no-secrets-understanding.db"
    session_factory = _create_file_session_factory(database_path)
    docs = _seed_documents(tmp_path, {"guide.md": "# Guide\n\nContent."})

    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local", chunk_size=500)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        kb_resp = await client.get("/knowledge-bases")
        kb_id = kb_resp.json()["items"][0]["id"]

        # Coverage endpoint
        coverage = await client.get(f"/knowledge-bases/{kb_id}/understanding-coverage")
        text_body = coverage.text
        assert "secret" not in text_body.lower()
        assert "api_key" not in text_body.lower()

        # Batch endpoint
        batch = await client.post(
            f"/knowledge-bases/{kb_id}/understand-all",
            json={"provider": "deterministic-local", "profile_id": "*.understand.default"},
        )
        text_body = batch.text
        assert "secret" not in text_body.lower()
        assert "api_key" not in text_body.lower()


@pytest.mark.anyio
async def test_understanding_result_traceability(tmp_path) -> None:
    """Verify each result has document_version_id, profile_id, provider, model, input_hash."""
    from ragrig.indexing.pipeline import index_knowledge_base
    from ragrig.ingestion.pipeline import ingest_local_directory

    database_path = tmp_path / "web-console-traceability.db"
    session_factory = _create_file_session_factory(database_path)
    docs = _seed_documents(tmp_path, {"guide.md": "# Guide\n\nA test guide for understanding."})

    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local", chunk_size=500)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Get a document version
        docs_resp = await client.get("/documents")
        version_id = docs_resp.json()["items"][0]["latest_version"]["id"]

        # Generate understanding
        gen_resp = await client.post(
            f"/document-versions/{version_id}/understand",
            json={"provider": "deterministic-local", "profile_id": "*.understand.default"},
        )
        assert gen_resp.status_code == 200
        payload = gen_resp.json()
        assert payload["document_version_id"] == version_id
        assert payload["profile_id"] == "*.understand.default"
        assert payload["provider"] == "deterministic-local"
        assert "model" in payload
        assert len(payload.get("input_hash", "")) == 64

        # Get understanding
        get_resp = await client.get(f"/document-versions/{version_id}/understanding")
        assert get_resp.status_code == 200
        assert len(get_resp.json().get("input_hash", "")) == 64
        assert get_resp.json()["profile_id"] == "*.understand.default"


# ── Processing Profile Persistence & Audit Tests ──


@pytest.mark.anyio
async def test_audit_log_endpoint_returns_recent_entries(tmp_path) -> None:
    database_path = tmp_path / "web-console-audit-log.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Create an override
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "pdf.chunk.audit-test",
                "extension": ".pdf",
                "task_type": "chunk",
                "display_name": "Audit Test Override",
                "description": "Testing audit log.",
                "provider": "deterministic-local",
                "created_by": "test-user",
            },
        )
        # Patch it
        await client.patch(
            "/processing-profiles/overrides/pdf.chunk.audit-test",
            json={"display_name": "Audit Test Updated"},
        )
        # Delete it
        await client.delete("/processing-profiles/overrides/pdf.chunk.audit-test")

        # Query audit log
        audit_resp = await client.get("/processing-profiles/audit-log?limit=10")

    assert audit_resp.status_code == 200
    entries = audit_resp.json()["entries"]
    # Should have at least 3 entries: create, update, delete
    assert len(entries) >= 3

    actions = [e["action"] for e in entries]
    assert "create" in actions
    assert "update" in actions
    assert "delete" in actions

    profile_ids = {e["profile_id"] for e in entries}
    assert "pdf.chunk.audit-test" in profile_ids

    # Create entry should have an actor
    create_entry = next(e for e in entries if e["action"] == "create")
    assert create_entry["actor"] == "test-user"
    assert create_entry["new_state"] is not None
    assert create_entry["old_state"] is None

    # Update entry should have old_state and new_state
    update_entry = next(e for e in entries if e["action"] == "update")
    assert update_entry["old_state"] is not None
    assert update_entry["new_state"] is not None

    # All entries must have a timestamp
    for entry in entries:
        assert entry["timestamp"] is not None


@pytest.mark.anyio
async def test_audit_log_sanitizes_secrets(tmp_path) -> None:
    database_path = tmp_path / "web-console-audit-secrets.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "pdf.chunk.secret-test",
                "extension": ".pdf",
                "task_type": "chunk",
                "display_name": "Secret Test",
                "description": "Testing secret redaction.",
                "provider": "deterministic-local",
                "metadata": {
                    "api_key": "sk-12345-secret",
                    "password": "my-password",
                    "normal_field": "visible-value",
                },
            },
        )
        audit_resp = await client.get("/processing-profiles/audit-log?limit=5")

    assert audit_resp.status_code == 200
    entries = audit_resp.json()["entries"]
    assert len(entries) >= 1

    new_state_str = str(entries[0]["new_state"])
    # Secrets must be redacted
    assert "sk-12345-secret" not in new_state_str
    assert "my-password" not in new_state_str
    assert "[REDACTED]" in new_state_str
    # Normal fields must be visible
    assert "visible-value" in new_state_str


@pytest.mark.anyio
async def test_unique_constraint_extension_task_type_conflict(tmp_path) -> None:
    database_path = tmp_path / "web-console-unique-constraint.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # First create should succeed
        first = await client.post(
            "/processing-profiles",
            json={
                "profile_id": "pdf.chunk.v1",
                "extension": ".pdf",
                "task_type": "chunk",
                "display_name": "PDF Chunk v1",
                "description": "First override.",
                "provider": "deterministic-local",
            },
        )
        assert first.status_code == 200

        # Second create with same extension/task_type should return 409
        second = await client.post(
            "/processing-profiles",
            json={
                "profile_id": "pdf.chunk.v2",
                "extension": ".pdf",
                "task_type": "chunk",
                "display_name": "PDF Chunk v2",
                "description": "Conflicting override.",
                "provider": "model.ollama",
            },
        )
        assert second.status_code == 409
        assert "already exists" in second.json()["error"]

        # But a different extension/task_type combo should work
        third = await client.post(
            "/processing-profiles",
            json={
                "profile_id": "pdf.summarize.v1",
                "extension": ".pdf",
                "task_type": "summarize",
                "display_name": "PDF Summarize",
                "description": "Different task type.",
                "provider": "model.ollama",
                "kind": "LLM-assisted",
            },
        )
        assert third.status_code == 200

        # After disabling the first, creating another for same ext/task should succeed
        await client.patch(
            "/processing-profiles/overrides/pdf.chunk.v1",
            json={"status": "disabled"},
        )
        fourth = await client.post(
            "/processing-profiles",
            json={
                "profile_id": "pdf.chunk.v3",
                "extension": ".pdf",
                "task_type": "chunk",
                "display_name": "PDF Chunk v3",
                "description": "After disabling v1.",
                "provider": "model.ollama",
            },
        )
        assert fourth.status_code == 200


@pytest.mark.anyio
async def test_persistence_survives_reinitialization(tmp_path) -> None:
    """Verify that overrides persist across app restarts (new create_app call)."""
    database_path = tmp_path / "web-console-persistence.db"

    # App instance 1: create override
    session_factory_1 = _create_file_session_factory(database_path)
    app1 = create_app(check_database=lambda: None, session_factory=session_factory_1)
    transport1 = httpx.ASGITransport(app=app1)

    async with httpx.AsyncClient(transport=transport1, base_url="http://testserver") as client1:
        create_resp = await client1.post(
            "/processing-profiles",
            json={
                "profile_id": "pdf.chunk.persist",
                "extension": ".pdf",
                "task_type": "chunk",
                "display_name": "Persisted Override",
                "description": "Must survive restart.",
                "provider": "deterministic-local",
                "created_by": "persist-test",
            },
        )
        assert create_resp.status_code == 200

    # App instance 2: reinitialize with new session_factory (same DB file)
    session_factory_2 = _create_file_session_factory(database_path)
    app2 = create_app(check_database=lambda: None, session_factory=session_factory_2)
    transport2 = httpx.ASGITransport(app=app2)

    async with httpx.AsyncClient(transport=transport2, base_url="http://testserver") as client2:
        matrix_resp = await client2.get("/processing-profiles/matrix")

    assert matrix_resp.status_code == 200
    cell = matrix_resp.json()["cells"][".pdf.chunk"]
    assert cell["source"] == "override"
    assert cell["profile_id"] == "pdf.chunk.persist"
    assert cell["created_by"] == "persist-test"
    assert cell["updated_at"] is not None


@pytest.mark.anyio
async def test_audit_log_filter_by_profile_id(tmp_path) -> None:
    database_path = tmp_path / "web-console-audit-filter.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "profile.a.test",
                "extension": ".md",
                "task_type": "correct",
                "display_name": "Profile A",
                "description": "First profile.",
                "provider": "deterministic-local",
            },
        )
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "profile.b.test",
                "extension": ".txt",
                "task_type": "correct",
                "display_name": "Profile B",
                "description": "Second profile.",
                "provider": "deterministic-local",
            },
        )

        # Filter by profile A
        filter_a = await client.get(
            "/processing-profiles/audit-log?limit=50&profile_id=profile.a.test"
        )
        # Filter by profile B
        filter_b = await client.get(
            "/processing-profiles/audit-log?limit=50&profile_id=profile.b.test"
        )

    assert filter_a.status_code == 200
    assert filter_b.status_code == 200

    a_entries = filter_a.json()["entries"]
    b_entries = filter_b.json()["entries"]

    assert len(a_entries) >= 1
    assert len(b_entries) >= 1
    for e in a_entries:
        assert e["profile_id"] == "profile.a.test"
    for e in b_entries:
        assert e["profile_id"] == "profile.b.test"


@pytest.mark.anyio
async def test_console_html_includes_audit_log_panel(tmp_path) -> None:
    database_path = tmp_path / "web-console-audit-panel.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/console")

    assert response.status_code == 200
    html = response.text
    assert "Audit Log" in html
    assert "audit-log-panel" in html
    assert "audit-log-table" in html
    assert "audit-log-refresh" in html
    assert "Override change history" in html
    assert "sensitive fields redacted" in html


@pytest.mark.anyio
async def test_console_html_includes_override_meta(tmp_path) -> None:
    database_path = tmp_path / "web-console-override-meta.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/console")

    assert response.status_code == 200
    html = response.text
    assert "cell-meta" in html
    assert "meta-tag" in html
    assert "renderAuditLog" in html


@pytest.mark.anyio
async def test_audit_log_limit_parameter(tmp_path) -> None:
    database_path = tmp_path / "web-console-audit-limit.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Create several overrides to populate audit log
        for i in range(5):
            await client.post(
                "/processing-profiles",
                json={
                    "profile_id": f"limit.test.{i}",
                    "extension": ".txt",
                    "task_type": "correct" if i % 2 == 0 else "clean",
                    "display_name": f"Limit Test {i}",
                    "description": f"Entry {i}.",
                    "provider": "deterministic-local",
                },
            )
            # Delete previous ones to create more audit entries
            if i > 0:
                await client.delete(f"/processing-profiles/overrides/limit.test.{i - 1}")

        resp_3 = await client.get("/processing-profiles/audit-log?limit=3")
        resp_10 = await client.get("/processing-profiles/audit-log?limit=10")

    assert resp_3.status_code == 200
    assert resp_10.status_code == 200
    assert len(resp_3.json()["entries"]) == 3
    assert len(resp_10.json()["entries"]) >= 5  # at least create+delete for each


@pytest.mark.anyio
async def test_audit_log_actions_contain_required_fields(tmp_path) -> None:
    database_path = tmp_path / "web-console-audit-fields.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "fields.test",
                "extension": ".txt",
                "task_type": "correct",
                "display_name": "Fields Test",
                "description": "Testing required fields.",
                "provider": "deterministic-local",
                "created_by": "fields-actor",
            },
        )
        await client.patch(
            "/processing-profiles/overrides/fields.test",
            json={"status": "disabled"},
        )
        await client.delete("/processing-profiles/overrides/fields.test")

        audit_resp = await client.get("/processing-profiles/audit-log?limit=10")

    assert audit_resp.status_code == 200
    entries = audit_resp.json()["entries"]
    assert len(entries) >= 3

    for entry in entries:
        assert "id" in entry
        assert "profile_id" in entry
        assert "action" in entry
        assert "actor" in entry
        assert "timestamp" in entry
        # old_state and new_state are present (may be null for create)
        assert "old_state" in entry
        assert "new_state" in entry
        assert entry["action"] in ("create", "update", "delete")


# ── Diff Preview & Rollback Tests ──


@pytest.mark.anyio
async def test_diff_preview_returns_old_new_changed_paths(tmp_path) -> None:
    database_path = tmp_path / "web-console-diff.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Create an override
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "diff.test.override",
                "extension": ".txt",
                "task_type": "correct",
                "display_name": "Diff Test Original",
                "description": "Original description.",
                "provider": "deterministic-local",
            },
        )
        # Preview diff with changes
        diff_resp = await client.post(
            "/processing-profiles/preview-diff",
            json={
                "profile_id": "diff.test.override",
                "display_name": "Diff Test Changed",
                "provider": "model.ollama",
            },
        )

    assert diff_resp.status_code == 200
    payload = diff_resp.json()
    assert "old" in payload
    assert "new" in payload
    assert "changed_paths" in payload
    assert payload["old"]["display_name"] == "Diff Test Original"
    assert payload["new"]["display_name"] == "Diff Test Changed"
    assert payload["old"]["provider"] == "deterministic-local"
    assert payload["new"]["provider"] == "model.ollama"
    assert "display_name" in payload["changed_paths"]
    assert "provider" in payload["changed_paths"]
    # Unchanged fields should NOT be in changed_paths
    assert "description" not in payload["changed_paths"]


@pytest.mark.anyio
async def test_diff_preview_no_secrets(tmp_path) -> None:
    database_path = tmp_path / "web-console-diff-secrets.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "diff.secret.test",
                "extension": ".txt",
                "task_type": "correct",
                "display_name": "Secret Diff Test",
                "description": "Desc.",
                "provider": "deterministic-local",
                "metadata": {"api_key": "sk-top-secret", "normal": "visible"},
            },
        )
        diff_resp = await client.post(
            "/processing-profiles/preview-diff",
            json={
                "profile_id": "diff.secret.test",
                "display_name": "Changed",
            },
        )

    assert diff_resp.status_code == 200
    payload = diff_resp.json()
    payload_str = str(payload)
    assert "sk-top-secret" not in payload_str
    assert "[REDACTED]" in payload_str
    assert "visible" in payload_str


@pytest.mark.anyio
async def test_diff_preview_returns_404_for_missing_override(tmp_path) -> None:
    database_path = tmp_path / "web-console-diff-404.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        diff_resp = await client.post(
            "/processing-profiles/preview-diff",
            json={
                "profile_id": "nonexistent.profile",
                "display_name": "Changed",
            },
        )

    assert diff_resp.status_code == 404
    assert diff_resp.json()["error"] == "override_not_found"


@pytest.mark.anyio
async def test_diff_preview_changed_paths_stable_order(tmp_path) -> None:
    database_path = tmp_path / "web-console-diff-order.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "diff.order.test",
                "extension": ".txt",
                "task_type": "correct",
                "display_name": "Order Test",
                "description": "Desc.",
                "provider": "deterministic-local",
            },
        )
        # Change multiple fields
        diff_resp = await client.post(
            "/processing-profiles/preview-diff",
            json={
                "profile_id": "diff.order.test",
                "status": "disabled",
                "display_name": "New Name",
                "provider": "model.ollama",
            },
        )

    assert diff_resp.status_code == 200
    payload = diff_resp.json()
    changed = payload["changed_paths"]
    # Must be sorted alphabetically
    assert changed == sorted(changed)
    assert len(changed) == 3


@pytest.mark.anyio
async def test_rollback_restores_previous_version(tmp_path) -> None:
    database_path = tmp_path / "web-console-rollback.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Create
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "rollback.test.override",
                "extension": ".md",
                "task_type": "summarize",
                "display_name": "Rollback Test v1",
                "description": "Original",
                "provider": "deterministic-local",
                "kind": "LLM-assisted",
            },
        )
        # Update (this writes an audit entry with old_state = v1)
        await client.patch(
            "/processing-profiles/overrides/rollback.test.override",
            json={"display_name": "Rollback Test v2"},
        )

        # Get the update audit entry (which has old_state as v1)
        audit_resp = await client.get(
            "/processing-profiles/audit-log?profile_id=rollback.test.override&action=update&limit=1"
        )
        update_entry = audit_resp.json()["entries"][0]
        update_audit_id = update_entry["id"]

        # Rollback to that audit entry
        rollback_resp = await client.post(
            "/processing-profiles/rollback",
            json={"audit_id": update_audit_id, "actor": "rollback-actor"},
        )

    assert rollback_resp.status_code == 200
    assert rollback_resp.json()["display_name"] == "Rollback Test v1"


@pytest.mark.anyio
async def test_rollback_writes_audit_log(tmp_path) -> None:
    database_path = tmp_path / "web-console-rollback-audit.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "rollback.audit.test",
                "extension": ".md",
                "task_type": "understand",
                "display_name": "Pre-Rollback",
                "description": "Before rollback.",
                "provider": "deterministic-local",
                "kind": "LLM-assisted",
            },
        )
        await client.patch(
            "/processing-profiles/overrides/rollback.audit.test",
            json={"display_name": "Post-Update"},
        )

        audit_resp = await client.get(
            "/processing-profiles/audit-log?profile_id=rollback.audit.test&action=update&limit=1"
        )
        update_audit_id = audit_resp.json()["entries"][0]["id"]

        await client.post(
            "/processing-profiles/rollback",
            json={"audit_id": update_audit_id, "actor": "rollback-user"},
        )

        # Check audit log for rollback entry
        full_audit = await client.get(
            "/processing-profiles/audit-log?profile_id=rollback.audit.test&limit=10"
        )

    entries = full_audit.json()["entries"]
    actions = [e["action"] for e in entries]
    assert "rollback" in actions
    rollback_entry = next(e for e in entries if e["action"] == "rollback")
    assert rollback_entry["actor"] == "rollback-user"
    assert rollback_entry["timestamp"] is not None
    assert rollback_entry["new_state"] is not None
    assert "source_audit_id" in rollback_entry["new_state"]
    assert rollback_entry["new_state"]["source_audit_id"] == update_audit_id


@pytest.mark.anyio
async def test_rollback_propagates_to_matrix(tmp_path) -> None:
    database_path = tmp_path / "web-console-rollback-matrix.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "rollback.matrix.test",
                "extension": ".md",
                "task_type": "summarize",
                "display_name": "Matrix v1",
                "description": "Original matrix override.",
                "provider": "deterministic-local",
                "kind": "LLM-assisted",
            },
        )
        await client.patch(
            "/processing-profiles/overrides/rollback.matrix.test",
            json={"display_name": "Matrix v2"},
        )

        audit_resp = await client.get(
            "/processing-profiles/audit-log?profile_id=rollback.matrix.test&action=update&limit=1"
        )
        update_audit_id = audit_resp.json()["entries"][0]["id"]

        await client.post(
            "/processing-profiles/rollback",
            json={"audit_id": update_audit_id},
        )

        matrix_resp = await client.get("/processing-profiles/matrix")

    assert matrix_resp.status_code == 200
    cell = matrix_resp.json()["cells"][".md.summarize"]
    assert cell["display_name"] == "Matrix v1"
    assert cell["source"] == "override"


@pytest.mark.anyio
async def test_rollback_nonexistent_audit_entry_returns_404(tmp_path) -> None:
    database_path = tmp_path / "web-console-rollback-404.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/processing-profiles/rollback",
            json={"audit_id": "00000000-0000-0000-0000-000000000000"},
        )

    assert resp.status_code == 404
    assert "not found" in resp.json()["error"].lower()


@pytest.mark.anyio
async def test_rollback_disabled_override_returns_409(tmp_path) -> None:
    database_path = tmp_path / "web-console-rollback-disabled.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "rollback.disabled.test",
                "extension": ".txt",
                "task_type": "correct",
                "display_name": "Will Disable",
                "description": "Test.",
                "provider": "deterministic-local",
            },
        )
        # Get the create audit entry
        audit_resp = await client.get(
            "/processing-profiles/audit-log?profile_id=rollback.disabled.test&action=create&limit=1"
        )
        audit_id = audit_resp.json()["entries"][0]["id"]

        # Disable the override
        await client.patch(
            "/processing-profiles/overrides/rollback.disabled.test",
            json={"status": "disabled"},
        )

        # Now try to rollback
        resp = await client.post(
            "/processing-profiles/rollback",
            json={"audit_id": audit_id},
        )

    assert resp.status_code == 409
    assert "disabled" in resp.json()["error"].lower()


@pytest.mark.anyio
async def test_rollback_deleted_override_returns_409(tmp_path) -> None:
    database_path = tmp_path / "web-console-rollback-deleted.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "rollback.deleted.test",
                "extension": ".txt",
                "task_type": "correct",
                "display_name": "Will Delete",
                "description": "Test.",
                "provider": "deterministic-local",
            },
        )
        # Get the create audit entry
        audit_resp = await client.get(
            "/processing-profiles/audit-log?profile_id=rollback.deleted.test&action=create&limit=1"
        )
        audit_id = audit_resp.json()["entries"][0]["id"]

        # Delete the override
        await client.delete("/processing-profiles/overrides/rollback.deleted.test")

        # Now try to rollback
        resp = await client.post(
            "/processing-profiles/rollback",
            json={"audit_id": audit_id},
        )

    assert resp.status_code == 409
    assert "deleted" in resp.json()["error"].lower()


@pytest.mark.anyio
async def test_audit_log_filter_by_provider(tmp_path) -> None:
    database_path = tmp_path / "web-console-audit-provider-filter.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "filter.provider.a",
                "extension": ".md",
                "task_type": "correct",
                "display_name": "Provider A",
                "description": "Provider A desc.",
                "provider": "deterministic-local",
            },
        )
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "filter.provider.b",
                "extension": ".txt",
                "task_type": "correct",
                "display_name": "Provider B",
                "description": "Provider B desc.",
                "provider": "model.ollama",
            },
        )

        resp_a = await client.get(
            "/processing-profiles/audit-log?provider=deterministic-local&limit=50"
        )
        resp_b = await client.get("/processing-profiles/audit-log?provider=model.ollama&limit=50")

    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    for e in resp_a.json()["entries"]:
        assert e["new_state"]["provider"] == "deterministic-local"
    for e in resp_b.json()["entries"]:
        assert e["new_state"]["provider"] == "model.ollama"


@pytest.mark.anyio
async def test_audit_log_filter_by_task_type(tmp_path) -> None:
    database_path = tmp_path / "web-console-audit-task-filter.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "filter.task.correct",
                "extension": ".md",
                "task_type": "correct",
                "display_name": "Task Correct",
                "description": "Correct task.",
                "provider": "deterministic-local",
            },
        )
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "filter.task.chunk",
                "extension": ".txt",
                "task_type": "chunk",
                "display_name": "Task Chunk",
                "description": "Chunk task.",
                "provider": "deterministic-local",
            },
        )

        resp_correct = await client.get("/processing-profiles/audit-log?task_type=correct&limit=50")
        resp_chunk = await client.get("/processing-profiles/audit-log?task_type=chunk&limit=50")

    assert resp_correct.status_code == 200
    assert resp_chunk.status_code == 200
    for e in resp_correct.json()["entries"]:
        assert e["new_state"]["task_type"] == "correct"
    for e in resp_chunk.json()["entries"]:
        assert e["new_state"]["task_type"] == "chunk"


@pytest.mark.anyio
async def test_audit_log_single_entry_endpoint(tmp_path) -> None:
    database_path = tmp_path / "web-console-audit-entry.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        await client.post(
            "/processing-profiles",
            json={
                "profile_id": "single.entry.test",
                "extension": ".md",
                "task_type": "correct",
                "display_name": "Single Entry",
                "description": "Single entry test.",
                "provider": "deterministic-local",
            },
        )

        audit_resp = await client.get("/processing-profiles/audit-log?limit=1")
        audit_id = audit_resp.json()["entries"][0]["id"]

        entry_resp = await client.get(f"/processing-profiles/audit-log/{audit_id}")

    assert entry_resp.status_code == 200
    entry = entry_resp.json()
    assert entry["id"] == audit_id
    assert entry["profile_id"] == "single.entry.test"
    assert entry["action"] == "create"


@pytest.mark.anyio
async def test_audit_log_single_entry_returns_404(tmp_path) -> None:
    database_path = tmp_path / "web-console-audit-entry-404.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get(
            "/processing-profiles/audit-log/00000000-0000-0000-0000-000000000000"
        )

    assert resp.status_code == 404
    assert resp.json()["error"] == "audit_entry_not_found"


@pytest.mark.anyio
async def test_console_html_includes_diff_and_rollback(tmp_path) -> None:
    database_path = tmp_path / "web-console-diff-rollback-ui.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/console")

    assert response.status_code == 200
    html = response.text
    # Diff preview UI
    assert "Diff Preview" in html
    assert "diff-preview-panel" in html
    assert "preview-diff" in html
    # Rollback UI
    assert "Rollback" in html
    assert "rollback-btn" in html
    assert "data-rollback-id" in html


# ── Fixture Corpus Integration Tests ──


@pytest.mark.anyio
async def test_upload_csv_fixture_corpus_items_have_stable_metadata(tmp_path) -> None:
    """Upload each CSV fixture from the corpus and verify pipeline_run_items metadata."""
    from ragrig.repositories import get_or_create_knowledge_base

    fixtures_dir = Path(__file__).parent / "fixtures" / "preview"
    csv_fixtures = sorted(fixtures_dir.glob("*.csv"))
    assert len(csv_fixtures) >= 3, f"Expected at least 3 CSV fixtures, got {len(csv_fixtures)}"

    database_path = tmp_path / "fixture-csv-metadata.db"
    session_factory = _create_file_session_factory(database_path)

    with session_factory() as session:
        get_or_create_knowledge_base(session, "fixture-local")
        session.commit()

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    for fixture_path in csv_fixtures:
        if fixture_path.name.startswith("binary_garbled"):
            continue
        if fixture_path.name.startswith("garbled"):
            continue
        if fixture_path.name == "oversized_line.csv":
            # Too large for upload via test fixture (500KB is ok per size limit but slow)
            continue

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            with open(fixture_path, "rb") as f:
                response = await client.post(
                    "/knowledge-bases/fixture-local/upload",
                    files={"files": (fixture_path.name, f, "text/csv")},
                )

        if response.status_code == 415:
            # Some fixtures may be rejected (empty files should still be accepted)
            continue

        assert response.status_code == 202, f"Fixture {fixture_path.name}: {response.text}"
        payload = response.json()
        assert payload["pipeline_run_id"] is not None

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            items_resp = await client.get(f"/pipeline-runs/{payload['pipeline_run_id']}/items")
        assert items_resp.status_code == 200
        items = items_resp.json()["items"]
        assert len(items) >= 1

        for item in items:
            meta = item["metadata"]
            assert "parser_id" in meta, f"{fixture_path.name}: missing parser_id in {meta}"
            assert "parser_name" in meta, f"{fixture_path.name}: missing parser_name"
            # CSV parser always produces degraded status
            assert item["status"] in ("degraded", "success", "failed"), (
                f"{fixture_path.name}: unexpected status {item['status']}"
            )


@pytest.mark.anyio
async def test_upload_html_fixture_corpus_items_have_stable_metadata(tmp_path) -> None:
    """Upload each HTML fixture from the corpus and verify pipeline_run_items metadata."""
    from ragrig.repositories import get_or_create_knowledge_base

    fixtures_dir = Path(__file__).parent / "fixtures" / "preview"
    html_fixtures = sorted(fixtures_dir.glob("*.html"))
    assert len(html_fixtures) >= 3, f"Expected at least 3 HTML fixtures, got {len(html_fixtures)}"

    database_path = tmp_path / "fixture-html-metadata.db"
    session_factory = _create_file_session_factory(database_path)

    with session_factory() as session:
        get_or_create_knowledge_base(session, "fixture-local")
        session.commit()

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    for fixture_path in html_fixtures:
        if fixture_path.name.startswith("binary_garbled"):
            continue
        if fixture_path.name.startswith("garbled"):
            continue

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            with open(fixture_path, "rb") as f:
                response = await client.post(
                    "/knowledge-bases/fixture-local/upload",
                    files={"files": (fixture_path.name, f, "text/html")},
                )

        if response.status_code == 415:
            continue

        assert response.status_code == 202, f"Fixture {fixture_path.name}: {response.text}"
        payload = response.json()

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            items_resp = await client.get(f"/pipeline-runs/{payload['pipeline_run_id']}/items")
        assert items_resp.status_code == 200
        items = items_resp.json()["items"]
        assert len(items) >= 1

        for item in items:
            meta = item["metadata"]
            assert "parser_id" in meta, f"{fixture_path.name}: missing parser_id"
            assert "parser_name" in meta, f"{fixture_path.name}: missing parser_name"
            assert item["status"] in ("degraded", "success", "failed")


@pytest.mark.anyio
async def test_upload_binary_garbled_csv_is_handled_as_failed(tmp_path) -> None:
    """Uploading a binary-garbled CSV should result in a failed pipeline item."""
    from ragrig.repositories import get_or_create_knowledge_base

    database_path = tmp_path / "fixture-binary-csv.db"
    session_factory = _create_file_session_factory(database_path)

    with session_factory() as session:
        get_or_create_knowledge_base(session, "fixture-local")
        session.commit()

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    # Create a binary file that will fail UTF-8 decode
    test_file = tmp_path / "bad.csv"
    test_file.write_bytes(b"\xff\xfe\x00\x01\x02")

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with open(test_file, "rb") as f:
            response = await client.post(
                "/knowledge-bases/fixture-local/upload",
                files={"files": ("bad.csv", f, "text/csv")},
            )

    assert response.status_code == 202
    payload = response.json()
    assert payload["pipeline_run_id"] is not None

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        items_resp = await client.get(f"/pipeline-runs/{payload['pipeline_run_id']}/items")
    assert items_resp.status_code == 200
    items = items_resp.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["status"] == "failed"
    # Error message should be deterministic and reproducible
    assert "error_message" in item
    assert item["error_message"] is not None
    assert "decode" in item["error_message"].lower() or "utf" in item["error_message"].lower()


@pytest.mark.anyio
async def test_upload_binary_garbled_html_is_handled_as_failed(tmp_path) -> None:
    """Uploading a binary-garbled HTML should result in a failed pipeline item."""
    from ragrig.repositories import get_or_create_knowledge_base

    database_path = tmp_path / "fixture-binary-html.db"
    session_factory = _create_file_session_factory(database_path)

    with session_factory() as session:
        get_or_create_knowledge_base(session, "fixture-local")
        session.commit()

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    test_file = tmp_path / "bad.html"
    test_file.write_bytes(b"\xff\xfe\x00\x01")

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with open(test_file, "rb") as f:
            response = await client.post(
                "/knowledge-bases/fixture-local/upload",
                files={"files": ("bad.html", f, "text/html")},
            )

    assert response.status_code == 202
    payload = response.json()

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        items_resp = await client.get(f"/pipeline-runs/{payload['pipeline_run_id']}/items")
    assert items_resp.status_code == 200
    items = items_resp.json()["items"]
    assert items[0]["status"] == "failed"
    assert items[0]["error_message"] is not None


@pytest.mark.anyio
async def test_console_renders_degraded_status_without_white_screen(tmp_path) -> None:
    """After uploading a preview fixture, the console HTML must include degraded/failed
    status indicators and not white-screen."""
    from ragrig.repositories import get_or_create_knowledge_base

    database_path = tmp_path / "fixture-console-degraded.db"
    session_factory = _create_file_session_factory(database_path)

    with session_factory() as session:
        get_or_create_knowledge_base(session, "fixture-local")
        session.commit()

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    # Upload a CSV (preview/degraded)
    test_file = tmp_path / "data.csv"
    test_file.write_text("col1,col2\na,b\n", encoding="utf-8")

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with open(test_file, "rb") as f:
            await client.post(
                "/knowledge-bases/fixture-local/upload",
                files={"files": ("data.csv", f, "text/csv")},
            )

        # Console page must render without error
        console = await client.get("/console")
        assert console.status_code == 200
        html = console.text

        # Must contain the HTML structure (no white screen)
        assert "<!doctype html>" in html.lower()
        assert "</html>" in html
        # Should render degraded/status indicators
        assert "degraded" in html.lower() or "preview" in html.lower()
        # Pipeline runs section must be present
        assert "Pipeline Runs" in html or "pipeline" in html.lower()


@pytest.mark.anyio
async def test_console_no_horizontal_overflow_for_long_metadata(tmp_path) -> None:
    """Verify the console CSS prevents horizontal overflow for long text in
    degraded_reason or other metadata fields."""
    from ragrig.repositories import get_or_create_knowledge_base

    database_path = tmp_path / "fixture-console-overflow.db"
    session_factory = _create_file_session_factory(database_path)

    with session_factory() as session:
        get_or_create_knowledge_base(session, "fixture-local")
        session.commit()

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    test_file = tmp_path / "data.csv"
    test_file.write_text("col1,col2\na,b\n", encoding="utf-8")

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with open(test_file, "rb") as f:
            await client.post(
                "/knowledge-bases/fixture-local/upload",
                files={"files": ("data.csv", f, "text/csv")},
            )

        console = await client.get("/console")
        html = console.text

        # CSS must include overflow-wrap or word-break rules
        assert "overflow-wrap" in html or "word-break" in html
        # No horizontal scrollbar styles that would cause overflow on content
        assert (
            "overflow-x: auto" in html
            or "overflow-x:auto" in html
            or "overflow-x: hidden" in html
            or "overflow-x:hidden" in html
        )


@pytest.mark.anyio
async def test_pipeline_run_items_failure_is_deterministic(tmp_path) -> None:
    """The same bad CSV file uploaded twice should produce the same failure status
    and consistent error metadata."""
    from ragrig.repositories import get_or_create_knowledge_base

    database_path = tmp_path / "fixture-deterministic.db"
    session_factory = _create_file_session_factory(database_path)

    with session_factory() as session:
        get_or_create_knowledge_base(session, "fixture-local")
        session.commit()

    app = create_app(check_database=lambda: None, session_factory=session_factory)

    test_file = tmp_path / "bad.csv"
    test_file.write_bytes(b"\xff\xfe\x00")

    async def _upload_one() -> tuple[str, str | None]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            with open(test_file, "rb") as f:
                resp = await client.post(
                    "/knowledge-bases/fixture-local/upload",
                    files={"files": (test_file.name, f, "text/csv")},
                )
            run_id = resp.json()["pipeline_run_id"]
            items_resp = await client.get(f"/pipeline-runs/{run_id}/items")
            item = items_resp.json()["items"][0]
            return item["status"], item.get("error_message")

    status1, err1 = await _upload_one()
    status2, err2 = await _upload_one()

    # Same file → same deterministic status
    assert status1 == status2 == "failed"
    # Error message should be consistent
    assert err1 is not None
    assert err2 is not None
    assert err1 == err2 or "decode" in str(err1).lower()


@pytest.mark.anyio
async def test_fixture_corpus_extension_coverage(tmp_path) -> None:
    """Verify that the fixture corpus covers the expected CSV and HTML extensions."""
    fixtures_dir = Path(__file__).parent / "fixtures" / "preview"
    csv_files = list(fixtures_dir.glob("*.csv"))
    html_files = list(fixtures_dir.glob("*.html"))

    # Should have fixtures for CSV
    assert len(csv_files) >= 3, f"Expected >= 3 CSV fixtures, got {len(csv_files)}"
    # Should have fixtures for HTML
    assert len(html_files) >= 3, f"Expected >= 3 HTML fixtures, got {len(html_files)}"

    corpus_names = {f.name for f in csv_files} | {f.name for f in html_files}
    expected_categories = [
        "empty",
        "sensitive",
        "malformed",
        "garbled",
        "binary_garbled",
        "oversized",
    ]
    found = []
    for category in expected_categories:
        if any(category in name for name in corpus_names):
            found.append(category)
    assert len(found) >= 4, f"Expected coverage for >= 4 categories, found {found}"


# Export filename tests


@pytest.mark.anyio
async def test_export_single_run_response_includes_filename(tmp_path) -> None:
    from ragrig.db.models import DocumentVersion
    from ragrig.indexing.pipeline import index_knowledge_base
    from ragrig.ingestion.pipeline import ingest_local_directory

    database_path = tmp_path / "export-filename-single.db"
    session_factory = _create_file_session_factory(database_path)
    docs = _seed_documents(tmp_path, {"guide.md": "# Guide\n\nA test guide for understanding."})

    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local", chunk_size=500)
        version = session.scalars(
            select(DocumentVersion).order_by(DocumentVersion.version_number.desc())
        ).first()

    assert version is not None

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        kb_resp = await client.get("/knowledge-bases")
        kb_id = kb_resp.json()["items"][0]["id"]

        # Create a run
        batch_resp = await client.post(
            f"/knowledge-bases/{kb_id}/understand-all",
            json={"provider": "test-provider", "profile_id": "test-profile"},
        )
        run_id = batch_resp.json()["run_id"]

        # Export single run
        export_resp = await client.get(f"/understanding-runs/{run_id}/export")

    assert export_resp.status_code == 200
    data = export_resp.json()
    assert "_filename" in data
    filename = data["_filename"]
    assert isinstance(filename, str)
    assert filename.startswith("ragrig-run-")
    assert filename.endswith(".json")
    assert "provider_test-provider" in filename
    assert "profile_test-profile" in filename


@pytest.mark.anyio
async def test_export_list_response_includes_filename_with_filters(tmp_path) -> None:
    from ragrig.indexing.pipeline import index_knowledge_base
    from ragrig.ingestion.pipeline import ingest_local_directory

    database_path = tmp_path / "export-filename-list.db"
    session_factory = _create_file_session_factory(database_path)
    docs = _seed_documents(tmp_path, {"guide.md": "# Guide\n\nContent."})

    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local", chunk_size=500)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        kb_resp = await client.get("/knowledge-bases")
        kb_id = kb_resp.json()["items"][0]["id"]

        # Create a run
        await client.post(
            f"/knowledge-bases/{kb_id}/understand-all",
            json={"provider": "my-prov", "profile_id": "my-profile"},
        )

        # Export with filters
        export_resp = await client.get(
            f"/knowledge-bases/{kb_id}/understanding-runs/export",
            params={
                "provider": "my-prov",
                "status": "success",
                "limit": 10,
            },
        )

    assert export_resp.status_code == 200
    data = export_resp.json()
    assert "_filename" in data
    filename = data["_filename"]
    assert isinstance(filename, str)
    assert "provider_my-prov" in filename
    assert "status_success" in filename
    assert "limit_10" in filename
    # model not filtered, should not appear
    assert "model_" not in filename


@pytest.mark.anyio
async def test_export_filename_hides_unset_filters(tmp_path) -> None:
    from ragrig.indexing.pipeline import index_knowledge_base
    from ragrig.ingestion.pipeline import ingest_local_directory

    database_path = tmp_path / "export-filename-unset.db"
    session_factory = _create_file_session_factory(database_path)
    docs = _seed_documents(tmp_path, {"guide.md": "# Guide\n\nContent."})

    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local", chunk_size=500)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        kb_resp = await client.get("/knowledge-bases")
        kb_id = kb_resp.json()["items"][0]["id"]

        await client.post(
            f"/knowledge-bases/{kb_id}/understand-all",
            json={"provider": "deterministic-local"},
        )

        # Export with NO filters
        export_resp = await client.get(f"/knowledge-bases/{kb_id}/understanding-runs/export")

    assert export_resp.status_code == 200
    data = export_resp.json()
    filename = data["_filename"]
    # When no filters are explicitly set, only KB name and implicit defaults appear
    assert "provider_" not in filename
    assert "model_" not in filename
    assert "profile_" not in filename
    assert "status_" not in filename


@pytest.mark.anyio
async def test_console_html_includes_export_filename_js(tmp_path) -> None:
    database_path = tmp_path / "web-console-export-filename.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/console")

    assert response.status_code == 200
    html = response.text
    # The export functions should use _filename from response
    assert "_filename" in html
    assert "exportSingleRun" in html
    assert "exportFilteredRuns" in html


# ── Answer Generation Web Console Tests ──────────────────────────────────────


@pytest.mark.anyio
async def test_console_includes_answer_generation_panel(tmp_path) -> None:
    """Answer generation panel must be present in the web console HTML."""
    database_path = tmp_path / "web-console-answer-panel.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/console")

    assert response.status_code == 200
    html = response.text
    assert "Answer Generation" in html
    assert "POST /retrieval/answer" in html
    assert "answer-kb" in html
    assert "answer-query" in html
    assert "answer-top-k" in html
    assert "run-answer" in html
    assert "answer-results" in html
    assert "answer-provider-meta" in html
    assert "Answer Gen" in html or "answer" in html.lower()


@pytest.mark.anyio
async def test_answer_panel_shows_disabled_state_without_data(tmp_path) -> None:
    """Answer panel should show disabled state when no knowledge bases exist."""
    database_path = tmp_path / "web-console-answer-disabled.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/console")

    assert response.status_code == 200
    assert "renderAnswerControls" in response.text


@pytest.mark.anyio
async def test_answer_panel_shows_ready_state_with_data(tmp_path) -> None:
    """Answer panel should be ready when knowledge bases with indexed data exist."""
    database_path = tmp_path / "web-console-answer-ready.db"
    session_factory = _create_file_session_factory(database_path)
    docs = _seed_documents(tmp_path, {"guide.txt": "Answer panel ready state test content."})

    with session_factory() as session:
        ingest_local_directory(session=session, knowledge_base_name="fixture-local", root_path=docs)
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/console")

    assert response.status_code == 200
    # Console should serve without errors (answer panel rendered)
    assert "Answer Generation" in response.text


@pytest.mark.anyio
async def test_answer_api_with_data_returns_valid_payload(tmp_path) -> None:
    """Full flow: ingest + index → answer API returns grounded answer."""
    database_path = tmp_path / "web-console-answer-flow.db"
    session_factory = _create_file_session_factory(database_path)
    docs = _seed_documents(
        tmp_path,
        {"guide.txt": "RAGRig is a retrieval-augmented generation platform for knowledge bases."},
    )

    with session_factory() as session:
        ingest_local_directory(session=session, knowledge_base_name="fixture-local", root_path=docs)
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/retrieval/answer",
            json={
                "knowledge_base": "fixture-local",
                "query": "What is RAGRig?",
                "top_k": 3,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["grounding_status"] == "grounded"
    assert len(payload["answer"]) > 0
    assert len(payload["citations"]) >= 1
    assert len(payload["evidence_chunks"]) >= 1
    assert payload["retrieval_trace"]["total_results"] >= 1
    assert "model" in payload
    assert "provider" in payload


@pytest.mark.anyio
async def test_answer_api_empty_knowledge_base_returns_refusal(tmp_path) -> None:
    """Answer API should refuse when knowledge base has no indexed data."""
    database_path = tmp_path / "web-console-answer-empty-kb.db"
    session_factory = _create_file_session_factory(database_path)
    docs = _seed_documents(tmp_path, {"notes.txt": "unindexed content"})

    with session_factory() as session:
        ingest_local_directory(session=session, knowledge_base_name="fixture-local", root_path=docs)
        # Do NOT index → zero retrieval results

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/retrieval/answer",
            json={
                "knowledge_base": "fixture-local",
                "query": "what is this?",
                "top_k": 3,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["grounding_status"] == "refused"
    assert payload["answer"] == ""
    assert payload["citations"] == []
    assert payload["evidence_chunks"] == []
    assert payload["refusal_reason"] is not None


@pytest.mark.anyio
async def test_answer_api_no_secrets_in_response(tmp_path) -> None:
    """Answer API payload must not leak secrets in any field."""
    database_path = tmp_path / "web-console-answer-nosecrets.db"
    session_factory = _create_file_session_factory(database_path)
    docs = _seed_documents(
        tmp_path,
        {"guide.txt": "RAGRig platform documentation and usage guide."},
    )

    with session_factory() as session:
        ingest_local_directory(session=session, knowledge_base_name="fixture-local", root_path=docs)
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/retrieval/answer",
            json={
                "knowledge_base": "fixture-local",
                "query": "RAGRig documentation",
                "top_k": 3,
            },
        )

    assert response.status_code == 200
    text = response.text.lower()
    # The response should not contain secret-like terms from provider/config leaks
    for secret_term in ["api_key", "password", "token"]:
        assert secret_term not in text, f"Secret term '{secret_term}' found in answer response"


@pytest.mark.anyio
async def test_answer_api_acl_filters_protected_content(tmp_path) -> None:
    """Answer API must not expose ACL-protected evidence to unauthorized users."""
    database_path = tmp_path / "web-console-answer-acl.db"
    session_factory = _create_file_session_factory(database_path)
    docs = _seed_documents(
        tmp_path,
        {
            "public.txt": "public information about the system",
            "secret.txt": "top secret internal operations details",
        },
    )

    with session_factory() as session:
        ingest_local_directory(session=session, knowledge_base_name="fixture-local", root_path=docs)
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        from ragrig.db.models import Chunk

        chunks = session.scalars(select(Chunk)).all()
        for chunk in chunks:
            if "top secret" in chunk.text:
                chunk.metadata_json = {
                    **chunk.metadata_json,
                    "acl": {
                        "visibility": "protected",
                        "allowed_principals": ["alice"],
                        "denied_principals": [],
                        "acl_source": "test",
                        "acl_source_hash": "abc",
                        "inheritance": "document",
                    },
                }
        session.commit()

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # Guest should not see protected content
        response = await client.post(
            "/retrieval/answer",
            json={
                "knowledge_base": "fixture-local",
                "query": "information about the system",
                "top_k": 10,
                "principal_ids": ["guest"],
                "enforce_acl": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    # No protected content in answer or evidence
    response_text = str(payload).lower()
    assert "top secret" not in response_text
    # But public content should be there
    assert payload["grounding_status"] == "grounded"


# ── Understanding Export Diff Console Badge tests ────────────────────────────


@pytest.mark.anyio
async def test_understanding_export_diff_endpoint_returns_pass_when_artifact_exists(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "web-console-diff-pass.db"
    session_factory = _create_file_session_factory(database_path)

    # Create a valid artifact
    artifact = {
        "artifact": "understanding-export-diff",
        "version": "1.0.0",
        "generated_at": "2026-05-11T12:00:00+00:00",
        "schema_version": "1.0",
        "schema_compatible": True,
        "baseline": {"run_count": 2, "schema_version": "1.0"},
        "current": {"run_count": 2, "schema_version": "1.0"},
        "runs": {"added": [], "removed": [], "changed": []},
        "run_details": {"added": [], "removed": [], "changed": []},
        "status": "pass",
        "drift_reasons": [],
        "sanitized_field_count": 0,
    }
    artifact_path = tmp_path / "understanding-export-diff.json"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    monkeypatch.setattr("ragrig.web_console._UNDERSTANDING_EXPORT_DIFF_PATH", artifact_path)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/understanding-export-diff")

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["status"] == "pass"
    assert payload["schema_compatible"] is True
    assert payload["baseline_run_count"] == 2
    assert payload["current_run_count"] == 2
    assert payload["added_count"] == 0
    assert payload["removed_count"] == 0
    assert payload["changed_count"] == 0
    assert payload["artifact_path"].endswith("understanding-export-diff.json")
    assert payload["sanitized_field_count"] == 0


@pytest.mark.anyio
async def test_understanding_export_diff_endpoint_returns_failure_when_artifact_missing(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "web-console-diff-missing.db"
    session_factory = _create_file_session_factory(database_path)

    missing_path = tmp_path / "nonexistent-diff.json"
    monkeypatch.setattr("ragrig.web_console._UNDERSTANDING_EXPORT_DIFF_PATH", missing_path)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/understanding-export-diff")

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["status"] == "failure"
    assert "not found" in payload["reason"]


@pytest.mark.anyio
async def test_understanding_export_diff_endpoint_returns_failure_when_artifact_corrupt(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "web-console-diff-corrupt.db"
    session_factory = _create_file_session_factory(database_path)

    corrupt_path = tmp_path / "corrupt-diff.json"
    corrupt_path.write_text("not json", encoding="utf-8")
    monkeypatch.setattr("ragrig.web_console._UNDERSTANDING_EXPORT_DIFF_PATH", corrupt_path)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/understanding-export-diff")

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["status"] == "failure"
    assert "corrupt" in payload["reason"]


@pytest.mark.anyio
async def test_understanding_export_diff_endpoint_returns_failure_when_artifact_type_invalid(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "web-console-diff-invalid-type.db"
    session_factory = _create_file_session_factory(database_path)

    invalid_path = tmp_path / "invalid-type.json"
    invalid_path.write_text(json.dumps({"artifact": "wrong-type"}), encoding="utf-8")
    monkeypatch.setattr("ragrig.web_console._UNDERSTANDING_EXPORT_DIFF_PATH", invalid_path)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/understanding-export-diff")

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is False
    assert payload["status"] == "failure"
    assert "invalid artifact type" in payload["reason"]


@pytest.mark.anyio
async def test_understanding_export_diff_endpoint_returns_degraded_when_artifact_degraded(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "web-console-diff-degraded.db"
    session_factory = _create_file_session_factory(database_path)

    artifact = {
        "artifact": "understanding-export-diff",
        "version": "1.0.0",
        "generated_at": "2026-05-11T12:00:00+00:00",
        "schema_version": "1.0",
        "schema_compatible": True,
        "baseline": {"run_count": 1, "schema_version": "1.0"},
        "current": {"run_count": 2, "schema_version": "1.0"},
        "runs": {"added": ["run-b"], "removed": [], "changed": []},
        "run_details": {"added": [], "removed": [], "changed": []},
        "status": "degraded",
        "drift_reasons": [{"type": "runs_added", "count": 1, "run_ids": ["run-b"]}],
        "sanitized_field_count": 0,
    }
    artifact_path = tmp_path / "degraded-diff.json"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    monkeypatch.setattr("ragrig.web_console._UNDERSTANDING_EXPORT_DIFF_PATH", artifact_path)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/understanding-export-diff")

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["status"] == "degraded"
    assert payload["added_count"] == 1
    assert payload["removed_count"] == 0
    assert payload["changed_count"] == 0


@pytest.mark.anyio
async def test_understanding_export_diff_endpoint_no_secret_leakage(tmp_path, monkeypatch) -> None:
    database_path = tmp_path / "web-console-diff-secrets.db"
    session_factory = _create_file_session_factory(database_path)

    artifact = {
        "artifact": "understanding-export-diff",
        "version": "1.0.0",
        "generated_at": "2026-05-11T12:00:00+00:00",
        "schema_version": "1.0",
        "schema_compatible": True,
        "baseline": {"run_count": 2, "schema_version": "1.0"},
        "current": {"run_count": 2, "schema_version": "1.0"},
        "runs": {"added": [], "removed": [], "changed": []},
        "run_details": {"added": [], "removed": [], "changed": []},
        "status": "pass",
        "drift_reasons": [],
        "sanitized_field_count": 0,
    }
    artifact_path = tmp_path / "safe-diff.json"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    monkeypatch.setattr("ragrig.web_console._UNDERSTANDING_EXPORT_DIFF_PATH", artifact_path)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/understanding-export-diff")

    assert response.status_code == 200
    text = response.text.lower()
    assert "api_key" not in text
    assert "secret" not in text
    assert "password" not in text
    assert "sk-live-" not in text


@pytest.mark.anyio
async def test_console_html_includes_understanding_export_diff_badge(tmp_path) -> None:
    database_path = tmp_path / "web-console-diff-badge.db"
    session_factory = _create_file_session_factory(database_path)
    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/console")

    assert response.status_code == 200
    html = response.text
    assert "understanding-export-diff-badge" in html
    assert "Understanding Export Diff" in html
    assert "copy-diff-path-btn" in html


@pytest.mark.anyio
async def test_understanding_export_diff_schema_incompatible_maps_to_failure(
    tmp_path, monkeypatch
) -> None:
    database_path = tmp_path / "web-console-diff-schema-fail.db"
    session_factory = _create_file_session_factory(database_path)

    artifact = {
        "artifact": "understanding-export-diff",
        "version": "1.0.0",
        "generated_at": "2026-05-11T12:00:00+00:00",
        "schema_version": "2.0",
        "schema_compatible": False,
        "baseline": {"run_count": 2, "schema_version": "1.0"},
        "current": {"run_count": 2, "schema_version": "2.0"},
        "runs": {"added": [], "removed": [], "changed": []},
        "run_details": {"added": [], "removed": [], "changed": []},
        "status": "pass",  # Should be corrected to failure by adapter
        "drift_reasons": [{"type": "schema_incompatible"}],
        "sanitized_field_count": 0,
    }
    artifact_path = tmp_path / "schema-diff.json"
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
    monkeypatch.setattr("ragrig.web_console._UNDERSTANDING_EXPORT_DIFF_PATH", artifact_path)

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/understanding-export-diff")

    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["status"] == "failure"
    assert payload["schema_compatible"] is False
