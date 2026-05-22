"""External demo release-candidate gate for the Local Pilot graph path."""

from __future__ import annotations

import argparse
import json
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.answer import generate_answer
from ragrig.answer.schema import NoEvidenceError, ProviderUnavailableError
from ragrig.db.models import Base
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.knowledge_graph import rebuild_knowledge_graph
from ragrig.repositories import get_knowledge_base_by_name
from ragrig.retrieval import search_knowledge_base
from scripts.graph_retrieval_eval_compare import (
    DEFAULT_GOLDEN_PATH,
    DEFAULT_INGEST_ROOT,
    compare_graph_retrieval_modes,
)

REPO_ROOT = Path(__file__).parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "operations" / "artifacts" / "demo-rc-gate.json"
DEFAULT_MARKDOWN_OUTPUT = REPO_ROOT / "docs" / "operations" / "artifacts" / "demo-rc-gate.md"
DEFAULT_KNOWLEDGE_BASE = "local-pilot-demo-rc"


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _check(check_id: str, passed: bool, detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "pass" if passed else "fail",
        "detail": detail,
    }


def _resolve_kb_id(session: Session, knowledge_base: str) -> str:
    kb = get_knowledge_base_by_name(session, knowledge_base)
    if kb is None:
        raise ValueError(f"knowledge base {knowledge_base!r} was not created")
    return str(kb.id)


def run_demo_rc_gate(
    *,
    database_path: Path,
    ingest_root: Path = DEFAULT_INGEST_ROOT,
    golden_path: Path = DEFAULT_GOLDEN_PATH,
    knowledge_base: str = DEFAULT_KNOWLEDGE_BASE,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
    Base.metadata.create_all(engine)
    try:
        with Session(engine, expire_on_commit=False) as session:
            ingest = ingest_local_directory(
                session=session,
                knowledge_base_name=knowledge_base,
                root_path=ingest_root,
                include_patterns=["*.md", "*.markdown"],
            )
            index = index_knowledge_base(
                session=session,
                knowledge_base_name=knowledge_base,
                chunk_size=500,
                chunk_overlap=50,
                force_reindex=True,
            )
            graph = rebuild_knowledge_graph(session, _resolve_kb_id(session, knowledge_base))

            comparison = compare_graph_retrieval_modes(
                session=session,
                golden_path=golden_path,
                knowledge_base=knowledge_base,
                modes=("dense", "graph", "hybrid_graph"),
                top_k=5,
                store_dir=database_path.parent / "evaluation_runs",
                run_prefix="demo-rc",
                generated_at=generated_at,
            )

            graph_search = search_knowledge_base(
                session=session,
                knowledge_base_name=knowledge_base,
                query="How do the handbook and FAQ together explain grounded citations?",
                top_k=5,
                mode="hybrid_graph",
            )
            answer_summary = _run_answer_probe(session, knowledge_base)

            checks = [
                _check(
                    "corpus_ingested",
                    ingest.created_documents >= 2 and ingest.failed_count == 0,
                    {
                        "created_documents": ingest.created_documents,
                        "created_versions": ingest.created_versions,
                        "failed_count": ingest.failed_count,
                    },
                ),
                _check(
                    "index_ready",
                    index.indexed_count >= 2 and index.failed_count == 0,
                    {
                        "indexed_count": index.indexed_count,
                        "chunk_count": index.chunk_count,
                        "failed_count": index.failed_count,
                    },
                ),
                _check(
                    "knowledge_graph_ready",
                    graph.status == "ready"
                    and graph.stats.entity_count >= 2
                    and graph.stats.claim_count >= 1
                    and graph.stats.graph_evidence_chunk_count >= 1,
                    {
                        "status": graph.status,
                        "stats": graph.stats.model_dump(),
                    },
                ),
                _check(
                    "graph_eval_comparison_ready",
                    _comparison_ready(comparison),
                    {
                        "winner": comparison.get("winner"),
                        "quality_gate_status": (comparison.get("quality_gate") or {}).get("status"),
                        "result_modes": [result["mode"] for result in comparison["results"]],
                        "item_error_counts": {
                            result["mode"]: result.get("item_error_count", 0)
                            for result in comparison["results"]
                        },
                    },
                ),
                _check(
                    "graph_retrieval_trace_ready",
                    graph_search.total_results >= 1
                    and bool(graph_search.graph_context.get("matched_entities"))
                    and bool(graph_search.graph_context.get("chunk_scores")),
                    {
                        "total_results": graph_search.total_results,
                        "matched_entity_count": len(
                            graph_search.graph_context.get("matched_entities") or []
                        ),
                        "graph_chunk_score_count": len(
                            graph_search.graph_context.get("chunk_scores") or {}
                        ),
                    },
                ),
                _check(
                    "grounded_answer_ready",
                    answer_summary["status"] == "pass",
                    answer_summary,
                ),
            ]

            status = "pass" if all(check["status"] == "pass" for check in checks) else "fail"
            report = {
                "artifact": "demo-rc-gate",
                "schema_version": "1.0.0",
                "generated_at": generated_at.isoformat() if generated_at else _now(),
                "status": status,
                "workflow": {
                    "knowledge_base": knowledge_base,
                    "ingest_root": _display(ingest_root),
                    "golden_path": _display(golden_path),
                    "database": _display(database_path),
                    "retrieval_modes": ["dense", "graph", "hybrid_graph"],
                },
                "checks": checks,
                "comparison": {
                    "winner": comparison.get("winner"),
                    "baseline_mode": comparison.get("baseline_mode"),
                    "quality_gate": comparison.get("quality_gate"),
                    "results": comparison.get("results"),
                },
            }
            report["markdown_summary"] = render_markdown_summary(report)
            return report
    finally:
        engine.dispose()


def _run_answer_probe(session: Session, knowledge_base: str) -> dict[str, Any]:
    query = "What makes a Local Pilot answer trustworthy?"
    try:
        answer = generate_answer(
            session=session,
            knowledge_base_name=knowledge_base,
            query=query,
            top_k=5,
            provider="deterministic-local",
            mode="hybrid_graph",
        )
    except NoEvidenceError as exc:
        return {"status": "fail", "query": query, "error": str(exc)}
    except ProviderUnavailableError as exc:
        return {"status": "fail", "query": query, "error": str(exc)}

    graph_context = answer.retrieval_trace.get("graph_context") or {}
    return {
        "status": "pass" if answer.grounding_status == "grounded" and answer.citations else "fail",
        "query": query,
        "grounding_status": answer.grounding_status,
        "citation_count": len(answer.citations),
        "evidence_chunk_count": len(answer.evidence_chunks),
        "matched_entity_count": len(graph_context.get("matched_entities") or []),
    }


def _comparison_ready(comparison: dict[str, Any]) -> bool:
    results = comparison.get("results") or []
    modes = {result.get("mode") for result in results}
    if not {"dense", "graph", "hybrid_graph"}.issubset(modes):
        return False
    for result in results:
        metrics = result.get("metrics") or {}
        if result.get("status") != "completed":
            return False
        if result.get("item_error_count", 0) != 0:
            return False
        if metrics.get("total_questions", 0) <= 0:
            return False
    return True


def render_markdown_summary(report: dict[str, Any]) -> str:
    lines = [
        "# Demo RC Gate",
        "",
        f"- Generated at: `{report.get('generated_at', 'unknown')}`",
        f"- Status: `{report.get('status', 'unknown')}`",
        f"- Knowledge base: `{report.get('workflow', {}).get('knowledge_base', 'unknown')}`",
        "",
        "## Checks",
        "",
        "| Check | Status |",
        "|---|---|",
    ]
    for check in report.get("checks", []):
        lines.append(f"| {check['id']} | {check['status']} |")
    comparison = report.get("comparison") or {}
    lines += [
        "",
        "## Retrieval Comparison",
        "",
        f"- Baseline mode: `{comparison.get('baseline_mode', 'unknown')}`",
        f"- Winner: `{comparison.get('winner', 'unknown')}`",
    ]
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the external demo RC gate.")
    parser.add_argument("--database-path", type=Path, default=None)
    parser.add_argument("--ingest-root", type=Path, default=DEFAULT_INGEST_ROOT)
    parser.add_argument("--golden-path", type=Path, default=DEFAULT_GOLDEN_PATH)
    parser.add_argument("--knowledge-base", default=DEFAULT_KNOWLEDGE_BASE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--pretty", action="store_true")
    return parser


def _run_with_database(
    database_path: Path | None,
    callback: Callable[[Path], dict[str, Any]],
) -> dict[str, Any]:
    if database_path is not None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        return callback(database_path)
    with tempfile.TemporaryDirectory(prefix="ragrig-demo-rc-") as temp:
        return callback(Path(temp) / "demo-rc-gate.db")


def main() -> int:
    args = build_parser().parse_args()
    report = _run_with_database(
        args.database_path,
        lambda db_path: run_demo_rc_gate(
            database_path=db_path,
            ingest_root=args.ingest_root,
            golden_path=args.golden_path,
            knowledge_base=args.knowledge_base,
        ),
    )

    indent = 2 if args.pretty else None
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=indent, sort_keys=True),
            encoding="utf-8",
        )
    if args.markdown_output is not None:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(report["markdown_summary"], encoding="utf-8")

    print(json.dumps(report, indent=indent, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
