from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.db.models import Base
from ragrig.workflows import resume_ingestion_dag, run_ingestion_dag


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def build_smoke_summary() -> dict[str, object]:
    with TemporaryDirectory(prefix="ragrig-dag-") as temp_dir:
        root = Path(temp_dir)
        docs = root / "docs"
        docs.mkdir()
        (docs / "smoke.md").write_text("# Smoke\n\nDAG fixture.", encoding="utf-8")
        engine = create_engine(f"sqlite+pysqlite:///{root / 'dag.db'}", future=True)
        Base.metadata.create_all(engine)
        with Session(engine, expire_on_commit=False) as session:
            failed = run_ingestion_dag(
                session,
                knowledge_base_name="dag-smoke",
                root_path=docs,
                failure_node="embed",
            )
            resumed = resume_ingestion_dag(session, pipeline_run_id=failed.pipeline_run_id)
    return {
        "schema_version": "pipeline-dag-smoke/v1",
        "initial_status": failed.status,
        "initial_failed_node": failed.failed_node,
        "failure_queue": failed.failure_queue,
        "resume_status": resumed["status"] if resumed else "missing",
        "resume_failure_queue": resumed["failure_queue"] if resumed else [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic ingestion DAG smoke coverage.")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()
    summary = build_smoke_summary()
    rendered = json.dumps(summary, indent=2 if args.pretty else None, sort_keys=True)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
