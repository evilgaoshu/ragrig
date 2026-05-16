from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine, func, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.db.models import Base, Document, DocumentVersion, PipelineRun, Source
from ragrig.plugins import PluginConfigValidationError, get_plugin_registry
from ragrig.plugins.sources.database.client import FakeDatabaseClient
from ragrig.plugins.sources.database.config import DatabaseQueryConfig
from ragrig.plugins.sources.database.connector import ingest_database_source
from ragrig.plugins.sources.database.errors import DatabaseQueryError
from ragrig.web_console import dry_run_source, save_source_config, validate_source_config

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@contextmanager
def _create_session(tmp_path: Path) -> Iterator[Session]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'database-source.db'}", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def _base_config(**overrides):
    config = {
        "engine": "postgresql",
        "dsn": "env:SOURCE_DATABASE_DSN",
        "source_name": "crm",
        "queries": [
            {
                "name": "accounts",
                "sql": "select id, name, notes, tier from accounts where active = :active",
                "params": {"active": True},
                "document_id_columns": ["id"],
                "title_column": "name",
                "text_columns": ["name", "notes"],
                "metadata_columns": ["tier"],
            }
        ],
        "max_rows_per_query": 100,
    }
    config.update(overrides)
    return config


def test_database_source_config_rejects_mutating_sql_and_plaintext_dsn() -> None:
    registry = get_plugin_registry()
    with pytest.raises(PluginConfigValidationError, match="read-only"):
        registry.validate_config(
            "source.database",
            _base_config(
                queries=[
                    {
                        "name": "accounts",
                        "sql": "delete from accounts",
                    }
                ]
            ),
        )

    with pytest.raises(PluginConfigValidationError, match="env"):
        registry.validate_config(
            "source.database",
            _base_config(dsn="postgresql://user:secret@example/db"),
        )


def test_validate_source_config_accepts_database_with_env_ref() -> None:
    result = validate_source_config(
        "source.database",
        _base_config(),
        env={"SOURCE_DATABASE_DSN": "postgresql://user:secret@example/db"},
    )

    assert result["valid"] is True
    assert result["plugin_id"] == "source.database"
    assert result["config"]["dsn"] == "env:SOURCE_DATABASE_DSN"
    assert "postgresql://user:secret@example/db" not in str(result)


def test_database_source_ingest_creates_documents_and_versions(tmp_path: Path) -> None:
    rows = [
        {"id": 101, "name": "Acme", "notes": "Escalation playbook", "tier": "enterprise"},
        {"id": 102, "name": "Beta", "notes": "Renewal checklist", "tier": "growth"},
    ]
    client = FakeDatabaseClient({"accounts": rows})

    with _create_session(tmp_path) as session:
        report = ingest_database_source(
            session=session,
            knowledge_base_name="kb",
            config=_base_config(),
            env={"SOURCE_DATABASE_DSN": "postgresql://user:top-secret@example/db"},
            client=client,
        )

        sources = session.scalars(select(Source)).all()
        documents = session.scalars(select(Document).order_by(Document.uri)).all()
        versions = session.scalars(
            select(DocumentVersion).order_by(DocumentVersion.created_at)
        ).all()
        runs = session.scalars(select(PipelineRun)).all()

    assert report.created_documents == 2
    assert report.created_versions == 2
    assert report.skipped_count == 0
    assert client.queries == ["accounts"]
    assert [source.kind for source in sources] == ["database"]
    assert sources[0].uri == "database://postgresql/crm"
    assert all(
        document.uri.startswith("database://postgresql/crm/accounts/") for document in documents
    )
    assert all("top-secret" not in document.uri for document in documents)
    assert {version.parser_name for version in versions} == {"database_row"}
    assert any("Escalation playbook" in version.extracted_text for version in versions)
    assert {"tier": "enterprise"} in [
        version.metadata_json["metadata_columns"] for version in versions
    ]
    assert runs[0].run_type == "database_ingest"
    assert runs[0].config_snapshot_json["dsn"] == "env:SOURCE_DATABASE_DSN"


def test_database_source_ingest_skips_unchanged_rows(tmp_path: Path) -> None:
    client = FakeDatabaseClient(
        {"accounts": [{"id": 101, "name": "Acme", "notes": "Same", "tier": "enterprise"}]}
    )

    with _create_session(tmp_path) as session:
        first = ingest_database_source(
            session=session,
            knowledge_base_name="kb",
            config=_base_config(),
            env={"SOURCE_DATABASE_DSN": "postgresql://user:secret@example/db"},
            client=client,
        )
        second = ingest_database_source(
            session=session,
            knowledge_base_name="kb",
            config=_base_config(),
            env={"SOURCE_DATABASE_DSN": "postgresql://user:secret@example/db"},
            client=client,
        )
        version_count = session.scalar(select(func.count()).select_from(DocumentVersion))

    assert first.created_versions == 1
    assert second.created_versions == 0
    assert second.skipped_count == 1
    assert version_count == 1


def test_database_source_supports_mysql_read_path_with_fake_client(tmp_path: Path) -> None:
    config = _base_config(engine="mysql")
    client = FakeDatabaseClient(
        {
            "accounts": [
                {
                    "id": "M-1",
                    "name": "MySQL Account",
                    "notes": "Read path",
                    "tier": "pilot",
                }
            ]
        }
    )

    with _create_session(tmp_path) as session:
        report = ingest_database_source(
            session=session,
            knowledge_base_name="kb",
            config=config,
            env={"SOURCE_DATABASE_DSN": "mysql+pymysql://user:secret@example/db"},
            client=client,
        )
        source = session.scalar(select(Source))

    assert report.created_versions == 1
    assert source is not None
    assert source.uri == "database://mysql/crm"


def test_database_source_sanitizes_query_errors(tmp_path: Path) -> None:
    class FailingClient:
        def fetch_query(self, query: DatabaseQueryConfig, *, max_rows: int):
            raise DatabaseQueryError("connection failed for postgresql://user:leaked@example/db")

        def close(self) -> None:
            return None

    with _create_session(tmp_path) as session:
        with pytest.raises(DatabaseQueryError) as excinfo:
            ingest_database_source(
                session=session,
                knowledge_base_name="kb",
                config=_base_config(),
                env={"SOURCE_DATABASE_DSN": "postgresql://user:leaked@example/db"},
                client=FailingClient(),
            )
        run = session.scalar(select(PipelineRun))

    assert "leaked" not in str(excinfo.value)
    assert run is not None
    assert run.status == "failed"
    assert "leaked" not in str(run.error_message)
    assert "[redacted]" in str(run.error_message)


def test_database_dry_run_does_not_write_documents(tmp_path: Path) -> None:
    client = FakeDatabaseClient(
        {"accounts": [{"id": 101, "name": "Acme", "notes": "Dry run", "tier": "enterprise"}]}
    )

    with _create_session(tmp_path) as session:
        result = dry_run_source(
            session,
            plugin_id="source.database",
            config=_base_config(),
            env={"SOURCE_DATABASE_DSN": "postgresql://user:secret@example/db"},
            client=client,
        )

        document_count = session.scalar(select(func.count()).select_from(Document))
        version_count = session.scalar(select(func.count()).select_from(DocumentVersion))

    assert result["dry_run"] is True
    assert result["source_kind"] == "database"
    assert result["discovered_count"] == 1
    assert document_count == 0
    assert version_count == 0


def test_save_database_source_config_creates_source_record(tmp_path: Path) -> None:
    with _create_session(tmp_path) as session:
        result = save_source_config(
            session,
            plugin_id="source.database",
            config=_base_config(),
            knowledge_base_name="kb",
        )

        source = session.scalar(select(Source))

    assert result["kind"] == "database"
    assert result["uri"] == "database://postgresql/crm"
    assert source is not None
    assert source.config_json["dsn"] == "env:SOURCE_DATABASE_DSN"
