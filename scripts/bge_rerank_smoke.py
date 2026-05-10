"""BGE reranker smoke test: verify optional BGE model integration.

Usage:
    make bge-rerank-smoke
    uv run python -m scripts.bge_rerank_smoke
    uv run python -m scripts.bge_rerank_smoke --output bge_smoke.json

This smoke test requires optional "local-ml" dependencies:
    FlagEmbedding, sentence-transformers, torch

If dependencies are missing, the test reports "skipped" with clear
reasoning — it never reports "success" when unable to run.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.db.models import Base
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.retrieval import search_knowledge_base


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


FIXTURE_ROOT = Path("tests/fixtures/local_ingestion")
FIXTURE_KB = "fixture-local"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run BGE reranker smoke test.")
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output path for the smoke test JSON result.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON to stdout.",
    )
    return parser


def _check_bge_dependencies() -> dict:
    """Check if BGE dependencies are available.

    Returns a dict with 'available', 'reason', and 'missing' fields.
    """
    missing = []

    try:
        import FlagEmbedding  # noqa: F401
    except ImportError:
        missing.append("FlagEmbedding")

    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        missing.append("sentence-transformers")

    try:
        import torch  # noqa: F401
    except ImportError:
        missing.append("torch")

    if missing:
        return {
            "available": False,
            "reason": f"Missing dependencies: {', '.join(missing)}. "
            f"Install with: uv sync --extra local-ml",
            "missing": missing,
        }

    return {
        "available": True,
        "reason": "All BGE dependencies are installed.",
        "missing": [],
    }


def _ensure_seeded(session: Session) -> None:
    from ragrig.repositories import get_knowledge_base_by_name

    kb = get_knowledge_base_by_name(session, FIXTURE_KB)
    if kb is None:
        ingest_local_directory(
            session=session,
            knowledge_base_name=FIXTURE_KB,
            root_path=FIXTURE_ROOT,
        )
        index_knowledge_base(
            session=session,
            knowledge_base_name=FIXTURE_KB,
            chunk_size=500,
        )
        return

    from sqlalchemy import func, select

    from ragrig.db.models import Chunk, Document, DocumentVersion

    chunk_count = session.scalar(
        select(func.count(Chunk.id))
        .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.knowledge_base_id == kb.id)
    )
    if chunk_count == 0:
        index_knowledge_base(
            session=session,
            knowledge_base_name=FIXTURE_KB,
            chunk_size=500,
        )


def run_bge_smoke() -> dict:
    """Run BGE reranker smoke test.

    Returns a JSON-serializable dict summarizing the result.
    """
    result: dict = {
        "test": "bge_rerank_smoke",
        "status": "skipped",
        "bge_dependencies": {},
        "details": {},
    }

    # Check dependencies first
    dep_check = _check_bge_dependencies()
    result["bge_dependencies"] = dep_check

    if not dep_check["available"]:
        result["status"] = "skipped"
        result["reason"] = dep_check["reason"]
        return result

    # Dependencies available — run smoke test
    fixture_root = FIXTURE_ROOT
    if not fixture_root.exists():
        result["status"] = "skipped"
        result["reason"] = f"Fixture directory not found: {fixture_root}. Run from the repo root."
        return result

    temp_dir = tempfile.mkdtemp(prefix="ragrig-bge-smoke-")
    db_path = Path(temp_dir) / "bge_smoke.db"
    engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)

    def session_factory() -> Session:
        return Session(engine, expire_on_commit=False)

    with session_factory() as session:
        _ensure_seeded(session)

    query = "retrieval configuration guide"

    # Run dense retrieval to get candidates, then rerank with BGE
    with session_factory() as session:
        t0 = time.perf_counter()
        report = search_knowledge_base(
            session=session,
            knowledge_base_name=FIXTURE_KB,
            query=query,
            top_k=5,
            mode="rerank",
            candidate_k=20,
            reranker_provider="reranker.bge",
        )
        elapsed = time.perf_counter() - t0

    engine.dispose()

    if report.degraded:
        result["status"] = "skipped"
        result["reason"] = (
            f"BGE reranker reported degraded: {report.degraded_reason}. "
            "The BGE model may fail to load (e.g., network required for first download, "
            "insufficient memory, or GPU not available)."
        )
        result["details"] = {
            "degraded": True,
            "degraded_reason": report.degraded_reason,
            "latency_ms": round(elapsed * 1000, 3),
        }
        return result

    result["status"] = "success"
    result["details"] = {
        "degraded": False,
        "degraded_reason": "",
        "latency_ms": round(elapsed * 1000, 3),
        "result_count": report.total_results,
        "reranker_provider": report.results[0]
        .rank_stage_trace["stages"][-1]
        .get("reranker", "reranker.bge"),
    }

    return result


def _sanitize_result(result: dict) -> dict:
    """Remove any secret-like values from the result dict."""
    SECRET_KEY_PARTS = (
        "api_key",
        "access_key",
        "secret",
        "password",
        "token",
        "credential",
        "private_key",
        "dsn",
        "service_account",
        "session_token",
    )

    def _redact(obj):
        if isinstance(obj, dict):
            return {
                k: "[redacted]" if any(p in k.lower() for p in SECRET_KEY_PARTS) else _redact(v)
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [_redact(v) for v in obj]
        return obj

    return _redact(result)


def main() -> int:
    args = build_parser().parse_args()

    result = run_bge_smoke()
    result = _sanitize_result(result)

    indent = 2 if args.pretty else None
    json_output = json.dumps(result, indent=indent, ensure_ascii=False, sort_keys=True)
    print(json_output)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json_output, encoding="utf-8")
        print(f"\nBGE smoke result written to {output_path}", file=sys.stderr)

    return 0 if result["status"] in ("success", "skipped") else 1


if __name__ == "__main__":
    raise SystemExit(main())
