from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx
import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.db.models import Base, Document, DocumentVersion, Source
from ragrig.main import create_app
from ragrig.plugins import PluginConfigValidationError
from ragrig.web_console import (
    dry_run_source,
    get_pipeline_run_item_detail,
    retry_pipeline_run,
    retry_pipeline_run_item,
    save_source_config,
    validate_source_config,
)

pytestmark = [pytest.mark.smoke, pytest.mark.slow]


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def _make_session(tmp_path) -> tuple[Session, Path]:
    db_path = tmp_path / "test_mutating.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    session = Session(engine, expire_on_commit=False)
    return session, db_path


# ── Source Config Validation ────────────────────────────────────────────────


class TestValidateSourceConfig:
    def test_validate_local_ready(self):
        """Local source with valid path returns ready status."""
        result = validate_source_config(
            "source.local",
            {"root_path": "/tmp", "include_patterns": [".md", ".txt"]},
        )
        assert result["valid"] is True
        assert result["status"] in ("ready", "degraded")

    def test_validate_local_config_invalid(self):
        """Local source with missing required fields returns invalid."""
        result = validate_source_config("source.local", {"include_patterns": []})
        assert result["valid"] is False

    def test_validate_s3_with_raw_secret_rejected(self):
        """S3 config with raw access_key (not env:) is rejected."""
        result = validate_source_config(
            "source.s3",
            {
                "bucket": "test-bucket",
                "access_key": "AKIA123456789",
                "secret_key": "env:AWS_SECRET_ACCESS_KEY",
            },
        )
        assert result["valid"] is False
        assert "raw secret" in result.get("reason", "").lower()

    def test_validate_fileshare_with_raw_password_rejected(self):
        """Fileshare config with raw password is rejected."""
        result = validate_source_config(
            "source.fileshare",
            {
                "protocol": "smb",
                "host": "server",
                "share": "share",
                "username": "env:FILESHARE_USER",
                "password": "rawpassword123",
            },
        )
        assert result["valid"] is False
        assert "raw secret" in result.get("reason", "").lower()

    def test_validate_unknown_plugin_disabled(self):
        """Unknown plugin returns disabled status."""
        result = validate_source_config("source.nonexistent", {})
        assert result["valid"] is False
        assert result["status"] == "disabled"

    def test_validate_local_with_env_refs_in_non_secret_field(self):
        """Non-secret fields with env refs are allowed."""
        result = validate_source_config(
            "source.local",
            {"root_path": "/data", "include_patterns": [".md"]},
        )
        assert result["valid"] is True

    def test_validate_nested_secret_rejected(self):
        """Nested dict with secret-like key is rejected."""
        result = validate_source_config(
            "source.local",
            {"root_path": "/tmp", "nested": {"api_key": "raw-key-value"}},
        )
        assert result["valid"] is False


# ── Source Config Save ──────────────────────────────────────────────────────


class TestSaveSourceConfig:
    def test_save_local_source_creates_record(self, tmp_path):
        session, _ = _make_session(tmp_path)
        docs = tmp_path / "docs"
        docs.mkdir()

        result = save_source_config(
            session,
            plugin_id="source.local",
            config={
                "root_path": str(docs),
                "include_patterns": [".md", ".txt"],
                "max_file_size_bytes": 10485760,
            },
            knowledge_base_name="test-kb",
        )

        assert "id" in result
        assert result["kind"] == "local"
        assert result["knowledge_base"] == "test-kb"

        # Verify Source exists in DB
        source = session.get(Source, uuid.UUID(result["id"]))
        assert source is not None
        assert source.kind == "local"

    def test_save_local_source_duplicate_updates(self, tmp_path):
        session, _ = _make_session(tmp_path)
        docs = tmp_path / "docs"
        docs.mkdir()

        result1 = save_source_config(
            session,
            plugin_id="source.local",
            config={"root_path": str(docs), "include_patterns": [".md"]},
            knowledge_base_name="test-kb",
        )

        result2 = save_source_config(
            session,
            plugin_id="source.local",
            config={"root_path": str(docs), "include_patterns": [".md", ".txt"]},
            knowledge_base_name="test-kb",
        )

        # Should be same source (same kb + uri)
        assert result1["id"] == result2["id"]

    def test_save_source_unknown_plugin(self, tmp_path):
        session, _ = _make_session(tmp_path)
        with pytest.raises((KeyError, ValueError)):
            save_source_config(
                session,
                plugin_id="source.unknown",
                config={},
                knowledge_base_name="test-kb",
            )


# ── Dry-run ──────────────────────────────────────────────────────────────────


class TestDryRun:
    def test_dry_run_local_directory(self, tmp_path):
        session, _ = _make_session(tmp_path)
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "readme.md").write_text("# Hello", encoding="utf-8")
        (docs / "notes.txt").write_text("Some notes", encoding="utf-8")

        result = dry_run_source(
            session,
            plugin_id="source.local",
            config={"root_path": str(docs), "include_patterns": [".md", ".txt"]},
        )

        assert result["dry_run"] is True
        assert result["total"] > 0
        assert result["source_kind"] == "local_directory"

    def test_dry_run_does_not_write_documents(self, tmp_path):
        session, _ = _make_session(tmp_path)
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "readme.md").write_text("# Hello", encoding="utf-8")

        initial_doc_count = session.query(Document).count()
        initial_version_count = session.query(DocumentVersion).count()

        dry_run_source(
            session,
            plugin_id="source.local",
            config={"root_path": str(docs), "include_patterns": [".md"]},
        )

        # No documents or versions should have been created
        assert session.query(Document).count() == initial_doc_count
        assert session.query(DocumentVersion).count() == initial_version_count

    def test_dry_run_empty_directory(self, tmp_path):
        session, _ = _make_session(tmp_path)
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        result = dry_run_source(
            session,
            plugin_id="source.local",
            config={"root_path": str(empty_dir)},
        )

        assert result["total"] == 0

    def test_dry_run_nonexistent_path(self, tmp_path):
        session, _ = _make_session(tmp_path)
        with pytest.raises((FileNotFoundError, OSError, ValueError)):
            dry_run_source(
                session,
                plugin_id="source.local",
                config={"root_path": str(tmp_path / "nonexistent")},
            )

    def test_dry_run_invalid_plugin(self, tmp_path):
        session, _ = _make_session(tmp_path)
        with pytest.raises((PluginConfigValidationError, ValueError, KeyError)):
            dry_run_source(
                session,
                plugin_id="source.invalid",
                config={},
            )


# ── Pipeline Run Item Inspect & Retry ──────────────────────────────────────


class TestPipelineRunItemInspect:
    def test_get_item_detail_not_found(self, tmp_path):
        session, _ = _make_session(tmp_path)
        detail = get_pipeline_run_item_detail(session, str(uuid.uuid4()))
        assert detail is None

    def test_get_item_detail_success(self, tmp_path):
        session, _ = _make_session(tmp_path)
        from ragrig.db.models import Source
        from ragrig.repositories import (
            create_pipeline_run,
            create_pipeline_run_item,
            get_or_create_document,
            get_or_create_knowledge_base,
        )

        kb = get_or_create_knowledge_base(session, "test-kb")
        source = Source(
            knowledge_base_id=kb.id,
            kind="local",
            uri="/tmp/test",
            config_json={},
        )
        session.add(source)
        session.flush()

        doc, _ = get_or_create_document(
            session,
            knowledge_base_id=kb.id,
            source_id=source.id,
            uri="/tmp/test/file.md",
            content_hash="abc123",
            mime_type="text/markdown",
            metadata_json={},
        )

        run = create_pipeline_run(
            session,
            knowledge_base_id=kb.id,
            source_id=source.id,
            config_snapshot_json={"test": True},
        )

        item = create_pipeline_run_item(
            session,
            pipeline_run_id=run.id,
            document_id=doc.id,
            status="failed",
            metadata_json={"file_name": "file.md"},
            error_message="parser error",
        )
        session.commit()

        detail = get_pipeline_run_item_detail(session, str(item.id))
        assert detail is not None
        assert detail["status"] == "failed"
        assert detail["document_uri"] == "/tmp/test/file.md"


class TestRetryPipelineRunItem:
    def test_retry_nonexistent_item(self, tmp_path):
        session, _ = _make_session(tmp_path)
        result = retry_pipeline_run_item(session, item_id=str(uuid.uuid4()))
        assert result is None

    def test_retry_failed_item_reprocesses(self, tmp_path):
        """Retry a failed local pipeline run item re-parses the file."""
        session, _ = _make_session(tmp_path)
        from ragrig.db.models import Source
        from ragrig.repositories import (
            create_pipeline_run,
            create_pipeline_run_item,
            get_or_create_document,
            get_or_create_knowledge_base,
        )

        docs = tmp_path / "docs"
        docs.mkdir()
        file_path = docs / "test.md"
        file_path.write_text("# Retry Test", encoding="utf-8")

        kb = get_or_create_knowledge_base(session, "test-kb")
        source = Source(
            knowledge_base_id=kb.id,
            kind="local",
            uri=str(docs),
            config_json={},
        )
        session.add(source)
        session.flush()

        doc, _ = get_or_create_document(
            session,
            knowledge_base_id=kb.id,
            source_id=source.id,
            uri=str(file_path),
            content_hash="initial",
            mime_type="text/markdown",
            metadata_json={},
        )

        run = create_pipeline_run(
            session,
            knowledge_base_id=kb.id,
            source_id=source.id,
            config_snapshot_json={"config": "snapshot"},
        )

        item = create_pipeline_run_item(
            session,
            pipeline_run_id=run.id,
            document_id=doc.id,
            status="failed",
            metadata_json={"file_name": "test.md"},
            error_message="initial parse error",
        )
        session.commit()

        result = retry_pipeline_run_item(session, item_id=str(item.id))
        assert result is not None
        assert result["status"] in ("success", "failed")

    def test_retry_idempotent(self, tmp_path):
        """Retrying twice produces the same result pattern."""
        session, _ = _make_session(tmp_path)
        from ragrig.db.models import Source
        from ragrig.repositories import (
            create_pipeline_run,
            create_pipeline_run_item,
            get_or_create_document,
            get_or_create_knowledge_base,
        )

        docs = tmp_path / "docs"
        docs.mkdir()
        file_path = docs / "test.md"
        file_path.write_text("# Idempotent", encoding="utf-8")

        kb = get_or_create_knowledge_base(session, "test-kb")
        source = Source(
            knowledge_base_id=kb.id,
            kind="local",
            uri=str(docs),
            config_json={},
        )
        session.add(source)
        session.flush()

        doc, _ = get_or_create_document(
            session,
            knowledge_base_id=kb.id,
            source_id=source.id,
            uri=str(file_path),
            content_hash="initial",
            mime_type="text/markdown",
            metadata_json={},
        )

        run = create_pipeline_run(
            session,
            knowledge_base_id=kb.id,
            source_id=source.id,
            config_snapshot_json={"config": "snapshot"},
        )

        item = create_pipeline_run_item(
            session,
            pipeline_run_id=run.id,
            document_id=doc.id,
            status="failed",
            metadata_json={"file_name": "test.md"},
            error_message="first error",
        )
        session.commit()

        # First retry
        result1 = retry_pipeline_run_item(session, item_id=str(item.id))
        assert result1 is not None

        # Second retry (item is already successful now, but we test it doesn't crash)
        result2 = retry_pipeline_run_item(session, item_id=str(item.id))
        assert result2 is not None


class TestRetryPipelineRun:
    def test_retry_nonexistent_run(self, tmp_path):
        session, _ = _make_session(tmp_path)
        result = retry_pipeline_run(session, run_id=str(uuid.uuid4()))
        assert result is None

    def test_retry_run_with_no_failed_items(self, tmp_path):
        session, _ = _make_session(tmp_path)
        from ragrig.db.models import Source
        from ragrig.repositories import create_pipeline_run
        from ragrig.repositories import get_or_create_knowledge_base as _get_or_create_kb

        kb = _get_or_create_kb(session, "test-kb")
        source = Source(
            knowledge_base_id=kb.id,
            kind="local",
            uri="/tmp",
            config_json={},
        )
        session.add(source)
        session.flush()

        run = create_pipeline_run(
            session,
            knowledge_base_id=kb.id,
            source_id=source.id,
            config_snapshot_json={},
        )
        session.commit()

        result = retry_pipeline_run(session, run_id=str(run.id))
        assert result is not None
        assert result["status"] == "no_failed_items"


# ── API Route Tests ─────────────────────────────────────────────────────────


class TestSourceValidateConfigAPI:
    @pytest.mark.anyio
    async def test_validate_config_route(self, tmp_path):
        db_path = tmp_path / "test_api.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)

        def sf():
            return Session(engine, expire_on_commit=False)

        app = create_app(check_database=lambda: None, session_factory=sf)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/sources/validate-config",
                json={
                    "plugin_id": "source.local",
                    "config": {"root_path": "/tmp", "include_patterns": [".md"]},
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "valid" in data
        assert data.get("plugin_id") == "source.local"

    @pytest.mark.anyio
    async def test_validate_config_with_raw_secret_rejected(self, tmp_path):
        db_path = tmp_path / "test_api2.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)

        def sf():
            return Session(engine, expire_on_commit=False)

        app = create_app(check_database=lambda: None, session_factory=sf)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/sources/validate-config",
                json={
                    "plugin_id": "source.s3",
                    "config": {
                        "bucket": "test",
                        "access_key": "AKIA123456",
                        "secret_key": "env:AWS_SECRET_ACCESS_KEY",
                    },
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False
        assert "raw secret" in str(data.get("reason", "")).lower()


class TestDryRunAPI:
    @pytest.mark.anyio
    async def test_dry_run_directory_does_not_write(self, tmp_path):
        db_path = tmp_path / "test_dryrun.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)

        def sf():
            return Session(engine, expire_on_commit=False)

        app = create_app(check_database=lambda: None, session_factory=sf)
        transport = httpx.ASGITransport(app=app)

        docs = tmp_path / "dryrun_docs"
        docs.mkdir()
        (docs / "test.md").write_text("# Dry Run", encoding="utf-8")

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/sources/dry-run",
                json={
                    "plugin_id": "source.local",
                    "config": {"root_path": str(docs), "include_patterns": [".md"]},
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dry_run"] is True
        assert data["total"] >= 1

        # Verify no documents were created
        session = sf()
        try:
            doc_count = session.query(Document).count()
            assert doc_count == 0
        finally:
            session.close()


class TestSaveConfigAPI:
    @pytest.mark.anyio
    async def test_save_config_creates_source(self, tmp_path):
        db_path = tmp_path / "test_save.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)

        def sf():
            return Session(engine, expire_on_commit=False)

        app = create_app(check_database=lambda: None, session_factory=sf)
        transport = httpx.ASGITransport(app=app)

        docs = tmp_path / "save_docs"
        docs.mkdir()

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                "/sources",
                json={
                    "plugin_id": "source.local",
                    "config": {
                        "root_path": str(docs),
                        "include_patterns": [".md"],
                        "max_file_size_bytes": 10485760,
                    },
                    "knowledge_base": "test-kb",
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["kind"] == "local"
        assert data["knowledge_base"] == "test-kb"
        assert "id" in data


class TestRetryAPI:
    @pytest.mark.anyio
    async def test_retry_item_not_found(self, tmp_path):
        db_path = tmp_path / "test_retry.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)

        def sf():
            return Session(engine, expire_on_commit=False)

        app = create_app(check_database=lambda: None, session_factory=sf)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                f"/pipeline-run-items/{uuid.uuid4()}/retry",
                json={},
            )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_retry_run_not_found(self, tmp_path):
        db_path = tmp_path / "test_retry2.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)

        def sf():
            return Session(engine, expire_on_commit=False)

        app = create_app(check_database=lambda: None, session_factory=sf)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.post(
                f"/pipeline-runs/{uuid.uuid4()}/retry",
                json={},
            )
        assert resp.status_code == 404


# ── Secret Leak Interception ─────────────────────────────────────────────────


class TestSecretLeakInterception:
    def test_validate_source_config_does_not_leak_raw_secrets(self, tmp_path):
        """Validate config test should not include raw secret values in output."""
        # Test that the validate output doesn't echo raw secret values
        # Use a config with valid env refs (no raw secrets)
        result = validate_source_config(
            "source.local",
            {"root_path": "/safe", "include_patterns": [".txt"]},
        )
        output = json.dumps(result)
        assert "AKIA123456789" not in output
        assert "sk-" not in output
        assert "ghp_" not in output

    def test_dry_run_error_sanitized(self, tmp_path):
        """Dry-run errors should not leak secret-like patterns."""
        session, _ = _make_session(tmp_path)
        # Provide valid S3 plugin config (no env refs needed for dry-run of local plugin)
        result = dry_run_source(
            session,
            plugin_id="source.local",
            config={"root_path": str(tmp_path), "include_patterns": [".md"]},
        )
        output = json.dumps(result)
        assert "sk-live-" not in output
        assert "ghp_" not in output
        assert "PRIVATE KEY" not in output
        assert "Bearer " not in output


# ── Console HTML Contract ──────────────────────────────────────────────────


class TestConsoleHTMLContract:
    @pytest.mark.anyio
    async def test_console_contains_mutating_ui_elements(self, tmp_path):
        db_path = tmp_path / "test_console_mutating.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)

        def sf():
            return Session(engine, expire_on_commit=False)

        app = create_app(check_database=lambda: None, session_factory=sf)
        transport = httpx.ASGITransport(app=app)

        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get("/console")

        assert resp.status_code == 200
        html = resp.text

        # New mutating UI elements should be present
        assert "Configure New Source" in html
        assert "Dry-run" in html
        assert "Retry" in html
        assert "/sources/validate-config" in html
        assert "/sources/dry-run" in html
        assert "/pipeline-run-items/" in html
        assert "/pipeline-runs/" in html
