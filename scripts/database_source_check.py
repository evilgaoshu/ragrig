from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.db.models import Base, Document, DocumentVersion, PipelineRun, Source
from ragrig.plugins.sources.database.client import FakeDatabaseClient
from ragrig.plugins.sources.database.connector import ingest_database_source

DEFAULT_OUTPUT = Path("docs/operations/artifacts/database-source-check.json")
SCHEMA_VERSION = "1.0.0"
DEFAULT_KNOWLEDGE_BASE = "database-source-fixture"


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def _config(engine: str) -> dict[str, object]:
    return {
        "engine": engine,
        "dsn": "env:SOURCE_DATABASE_DSN",
        "source_name": f"{engine}-fixture",
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


def run_database_source_check(
    *,
    knowledge_base: str = DEFAULT_KNOWLEDGE_BASE,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated = generated_at or datetime.now(timezone.utc)
    rows = [
        {"id": 1, "name": "Acme", "notes": "PostgreSQL/MySQL read fixture", "tier": "enterprise"},
        {"id": 2, "name": "Beta", "notes": "Incremental unchanged fixture", "tier": "growth"},
    ]

    with tempfile.TemporaryDirectory(prefix="ragrig-database-source-") as temp:
        db_path = Path(temp) / "database-source.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)
        try:
            with Session(engine, expire_on_commit=False) as session:
                pg_report = ingest_database_source(
                    session=session,
                    knowledge_base_name=knowledge_base,
                    config=_config("postgresql"),
                    env={"SOURCE_DATABASE_DSN": "postgresql://user:postgres-secret@example/db"},
                    client=FakeDatabaseClient({"accounts": rows}),
                )
                pg_repeat_report = ingest_database_source(
                    session=session,
                    knowledge_base_name=knowledge_base,
                    config=_config("postgresql"),
                    env={"SOURCE_DATABASE_DSN": "postgresql://user:postgres-secret@example/db"},
                    client=FakeDatabaseClient({"accounts": rows}),
                )
                mysql_report = ingest_database_source(
                    session=session,
                    knowledge_base_name=knowledge_base,
                    config=_config("mysql"),
                    env={"SOURCE_DATABASE_DSN": "mysql+pymysql://user:mysql-secret@example/db"},
                    client=FakeDatabaseClient({"accounts": rows}),
                )
                documents = session.scalars(select(Document).order_by(Document.uri)).all()
                versions = session.scalars(select(DocumentVersion)).all()
                runs = session.scalars(select(PipelineRun).order_by(PipelineRun.started_at)).all()
                sources = session.scalars(select(Source).order_by(Source.uri)).all()
        finally:
            engine.dispose()

    serialized_evidence = json.dumps(
        {
            "document_uris": [document.uri for document in documents],
            "run_errors": [run.error_message for run in runs],
            "run_config_snapshots": [run.config_snapshot_json for run in runs],
            "source_uris": [source.uri for source in sources],
        },
        sort_keys=True,
    )
    checks = [
        {
            "name": "postgresql_read_path_created_versions",
            "status": "pass" if pg_report.created_versions == 2 else "fail",
            "detail": pg_report.__dict__ | {"pipeline_run_id": str(pg_report.pipeline_run_id)},
        },
        {
            "name": "incremental_unchanged_rows_skipped",
            "status": (
                "pass"
                if pg_repeat_report.created_versions == 0 and pg_repeat_report.skipped_count == 2
                else "fail"
            ),
            "detail": pg_repeat_report.__dict__
            | {"pipeline_run_id": str(pg_repeat_report.pipeline_run_id)},
        },
        {
            "name": "mysql_read_path_created_versions",
            "status": "pass" if mysql_report.created_versions == 2 else "fail",
            "detail": mysql_report.__dict__
            | {"pipeline_run_id": str(mysql_report.pipeline_run_id)},
        },
        {
            "name": "no_dsn_leakage",
            "status": (
                "pass"
                if "postgres-secret" not in serialized_evidence
                and "mysql-secret" not in serialized_evidence
                else "fail"
            ),
            "detail": {
                "documents": len(documents),
                "versions": len(versions),
                "sources": [source.uri for source in sources],
            },
        },
    ]
    status = "pass" if all(check["status"] == "pass" for check in checks) else "failure"
    return {
        "artifact": "database-source-check",
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated.isoformat(),
        "status": status,
        "workflow": {
            "database": "ephemeral_sqlite_metadata",
            "knowledge_base": knowledge_base,
            "source_engines": ["postgresql", "mysql"],
            "client": "FakeDatabaseClient",
            "fixture_rows": len(rows),
        },
        "checks": checks,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic PostgreSQL/MySQL database source connector smoke."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--knowledge-base", default=DEFAULT_KNOWLEDGE_BASE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    artifact = run_database_source_check(knowledge_base=args.knowledge_base)
    rendered = json.dumps(
        artifact,
        ensure_ascii=False,
        indent=2 if args.pretty else None,
        sort_keys=True,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if artifact["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
