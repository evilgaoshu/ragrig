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

from ragrig.db.models import Base, KnowledgeBase
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.understanding import build_knowledge_map, knowledge_map_to_dict
from ragrig.understanding.service import understand_all_versions

DEFAULT_OUTPUT = Path("docs/operations/artifacts/knowledge-map-check.json")
DEFAULT_KNOWLEDGE_BASE = "knowledge-map-fixture"
SCHEMA_VERSION = "1.0.0"

FIXTURE_DOCS = {
    "architecture.md": (
        "# RAGRig Architecture\n\n"
        "RAGRig uses PostgreSQL and Qdrant for retrieval. "
        "The Architecture guide explains ingestion and retrieval boundaries.\n"
    ),
    "operations.md": (
        "# PostgreSQL Operations\n\n"
        "PostgreSQL backs RAGRig audit events and retrieval metadata. "
        "Operations teams review RAGRig status before each pilot.\n"
    ),
    "evaluation.md": (
        "# Evaluation Workflow\n\n"
        "Evaluation compares RAGRig retrieval quality after reindex. "
        "The Workflow records expected citations and quality gates.\n"
    ),
}


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def run_knowledge_map_check(
    *,
    knowledge_base: str = DEFAULT_KNOWLEDGE_BASE,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated = generated_at or datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix="ragrig-knowledge-map-") as temp:
        temp_dir = Path(temp)
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        for filename, body in FIXTURE_DOCS.items():
            (docs_dir / filename).write_text(body, encoding="utf-8")

        engine = create_engine(f"sqlite+pysqlite:///{temp_dir / 'knowledge-map.db'}", future=True)
        Base.metadata.create_all(engine)
        try:
            with Session(engine, expire_on_commit=False) as session:
                ingest_local_directory(
                    session=session,
                    knowledge_base_name=knowledge_base,
                    root_path=docs_dir,
                )
                kb = session.scalar(
                    select(KnowledgeBase).where(KnowledgeBase.name == knowledge_base)
                )
                if kb is None:
                    raise RuntimeError("knowledge base was not created")

                batch = understand_all_versions(
                    session,
                    knowledge_base_id=str(kb.id),
                    provider="deterministic-local",
                    profile_id="*.understand.default",
                    trigger_source="knowledge-map-check",
                    operator="ci",
                )
                knowledge_map = build_knowledge_map(
                    session,
                    str(kb.id),
                    generated_at=generated,
                )
                if knowledge_map is None:
                    raise RuntimeError("knowledge map was not generated")
        finally:
            engine.dispose()

    map_dict = knowledge_map_to_dict(knowledge_map)
    checks = [
        {
            "name": "understanding_batch_completed",
            "status": "pass" if batch.total == 3 and batch.failed == 0 else "fail",
            "detail": {
                "total": batch.total,
                "created": batch.created,
                "skipped": batch.skipped,
                "failed": batch.failed,
            },
        },
        {
            "name": "document_relationships_present",
            "status": ("pass" if map_dict["stats"]["document_relationship_edges"] >= 2 else "fail"),
            "detail": {
                "document_relationship_edges": map_dict["stats"]["document_relationship_edges"],
            },
        },
        {
            "name": "cross_document_entities_present",
            "status": ("pass" if map_dict["stats"]["cross_document_entity_count"] >= 1 else "fail"),
            "detail": {
                "cross_document_entity_count": map_dict["stats"]["cross_document_entity_count"],
            },
        },
    ]
    status = "pass" if all(check["status"] == "pass" for check in checks) else "failure"
    return {
        "artifact": "knowledge-map-check",
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated.isoformat(),
        "status": status,
        "workflow": {
            "database": "ephemeral_sqlite",
            "knowledge_base": knowledge_base,
            "provider": "deterministic-local",
            "profile_id": "*.understand.default",
            "fixture_documents": sorted(FIXTURE_DOCS),
        },
        "checks": checks,
        "knowledge_map": map_dict,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic knowledge map / cross-document understanding smoke."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--knowledge-base", default=DEFAULT_KNOWLEDGE_BASE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    artifact = run_knowledge_map_check(knowledge_base=args.knowledge_base)
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
