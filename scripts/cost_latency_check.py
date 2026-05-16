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

from ragrig.answer import generate_answer
from ragrig.db.models import Base, Embedding, PipelineRun
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.observability import summarize_pipeline_cost_latency
from ragrig.retrieval import search_knowledge_base

DEFAULT_OUTPUT = Path("docs/operations/artifacts/cost-latency-check.json")
DEFAULT_KNOWLEDGE_BASE = "cost-latency-fixture"
SCHEMA_VERSION = "1.0.0"


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def run_cost_latency_check(
    *,
    knowledge_base: str = DEFAULT_KNOWLEDGE_BASE,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated = generated_at or datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix="ragrig-cost-latency-") as temp:
        temp_dir = Path(temp)
        docs_dir = temp_dir / "docs"
        docs_dir.mkdir()
        (docs_dir / "guide.md").write_text(
            "# Cost Tracking\n\nRAGRig tracks cost and latency across indexing and retrieval.\n",
            encoding="utf-8",
        )

        engine = create_engine(f"sqlite+pysqlite:///{temp_dir / 'cost-latency.db'}", future=True)
        Base.metadata.create_all(engine)
        try:
            with Session(engine, expire_on_commit=False) as session:
                ingest_local_directory(
                    session=session,
                    knowledge_base_name=knowledge_base,
                    root_path=docs_dir,
                )
                index_report = index_knowledge_base(
                    session=session,
                    knowledge_base_name=knowledge_base,
                    chunk_size=48,
                    chunk_overlap=8,
                )
                retrieval_report = search_knowledge_base(
                    session=session,
                    knowledge_base_name=knowledge_base,
                    query="How does RAGRig track latency?",
                    top_k=1,
                )
                answer_report = generate_answer(
                    session=session,
                    knowledge_base_name=knowledge_base,
                    query="How does RAGRig track cost?",
                    top_k=1,
                )
                summary = summarize_pipeline_cost_latency(
                    session,
                    knowledge_base_name=knowledge_base,
                )
                indexing_run = session.scalar(
                    select(PipelineRun).where(PipelineRun.id == index_report.pipeline_run_id)
                )
                embeddings = session.scalars(select(Embedding)).all()
        finally:
            engine.dispose()

    indexing_summary = (indexing_run.config_snapshot_json or {}).get("cost_latency_summary", {})
    checks = [
        {
            "name": "indexing_run_records_cost_latency",
            "status": (
                "pass"
                if indexing_summary.get("operation_count", 0) >= 1
                and indexing_summary.get("total_tokens_estimated", 0) > 0
                else "fail"
            ),
            "detail": indexing_summary,
        },
        {
            "name": "embedding_metadata_records_usage",
            "status": (
                "pass"
                if embeddings
                and all("cost_latency" in (item.metadata_json or {}) for item in embeddings)
                else "fail"
            ),
            "detail": {"embedding_count": len(embeddings)},
        },
        {
            "name": "retrieval_report_records_latency",
            "status": (
                "pass"
                if retrieval_report.cost_latency.get("total_latency_ms", 0) >= 0
                and retrieval_report.cost_latency.get("operation_count", 0) >= 1
                else "fail"
            ),
            "detail": retrieval_report.cost_latency,
        },
        {
            "name": "answer_report_records_cost_latency",
            "status": (
                "pass"
                if answer_report.cost_latency.get("operation_count", 0) >= 2
                and answer_report.cost_latency.get("total_tokens_estimated", 0) > 0
                else "fail"
            ),
            "detail": answer_report.cost_latency,
        },
        {
            "name": "summary_endpoint_payload_shape",
            "status": (
                "pass"
                if summary.get("run_count", 0) >= 1
                and summary.get("tracked_operation_count", 0) >= 1
                else "fail"
            ),
            "detail": {
                "run_count": summary.get("run_count"),
                "tracked_operation_count": summary.get("tracked_operation_count"),
            },
        },
    ]
    status = "pass" if all(check["status"] == "pass" for check in checks) else "failure"
    return {
        "artifact": "cost-latency-check",
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated.isoformat(),
        "status": status,
        "workflow": {
            "database": "ephemeral_sqlite",
            "knowledge_base": knowledge_base,
            "provider": "deterministic-local",
        },
        "checks": checks,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic cost/latency tracking smoke.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--knowledge-base", default=DEFAULT_KNOWLEDGE_BASE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    artifact = run_cost_latency_check(knowledge_base=args.knowledge_base)
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
