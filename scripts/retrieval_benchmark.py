"""Retrieval benchmark CLI: measure latency across retrieval modes.

Usage:
    make retrieval-benchmark
    uv run python -m scripts.retrieval_benchmark
    uv run python -m scripts.retrieval_benchmark --iterations 10 --output benchmark.json
"""

from __future__ import annotations

import argparse
import json
import statistics
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
DEFAULT_TOP_K = 5
DEFAULT_CANDIDATE_K = 20
DEFAULT_ITERATIONS = 5
BENCHMARK_QUERIES = [
    "retrieval configuration guide",
    "embedding dimensions",
    "chunking pipeline",
    "knowledge base setup",
    "vector search backend",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run retrieval benchmarks across dense/hybrid/rerank/hybrid_rerank modes."
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
        help=f"Number of iterations per mode per query. Default: {DEFAULT_ITERATIONS}",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output path for the benchmark JSON summary.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON to stdout.",
    )
    return parser


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


def _run_benchmark_for_mode(
    session_factory,
    mode: str,
    queries: list[str],
    iterations: int,
    top_k: int,
    candidate_k: int,
) -> dict:
    latencies: list[float] = []
    total_results = 0
    degraded = False
    degraded_reason = ""

    for query in queries:
        for _ in range(iterations):
            with session_factory() as session:
                t0 = time.perf_counter()
                report = search_knowledge_base(
                    session=session,
                    knowledge_base_name=FIXTURE_KB,
                    query=query,
                    top_k=top_k,
                    mode=mode,
                    candidate_k=candidate_k,
                )
                elapsed = time.perf_counter() - t0
                latencies.append(elapsed)
                total_results += report.total_results
                if report.degraded:
                    degraded = True
                    degraded_reason = degraded_reason or report.degraded_reason

    sorted_latencies = sorted(latencies)
    n = len(sorted_latencies)
    p50 = sorted_latencies[n // 2]
    p95_idx = int(n * 0.95)
    p95 = sorted_latencies[min(p95_idx, n - 1)]

    return {
        "mode": mode,
        "top_k": top_k,
        "candidate_k": candidate_k,
        "iterations": n,
        "p50_latency_ms": round(p50 * 1000, 3),
        "p95_latency_ms": round(p95 * 1000, 3),
        "min_latency_ms": round(sorted_latencies[0] * 1000, 3),
        "max_latency_ms": round(sorted_latencies[-1] * 1000, 3),
        "mean_latency_ms": round(statistics.mean(latencies) * 1000, 3),
        "result_count": total_results,
        "degraded": degraded,
        "degraded_reason": degraded_reason if degraded else "",
    }


def run_benchmarks(
    *,
    iterations: int = DEFAULT_ITERATIONS,
    top_k: int = DEFAULT_TOP_K,
    candidate_k: int = DEFAULT_CANDIDATE_K,
    queries: list[str] | None = None,
    database_url: str | None = None,
) -> dict:
    queries = queries or BENCHMARK_QUERIES

    if database_url:
        engine = create_engine(database_url, future=True)
        Base.metadata.create_all(engine)
    else:
        temp_dir = tempfile.mkdtemp(prefix="ragrig-benchmark-")
        db_path = Path(temp_dir) / "benchmark.db"
        engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
        Base.metadata.create_all(engine)

    def session_factory() -> Session:
        return Session(engine, expire_on_commit=False)

    with session_factory() as session:
        _ensure_seeded(session)

    modes = ["dense", "hybrid", "rerank", "hybrid_rerank"]
    mode_results = []
    for mode in modes:
        result = _run_benchmark_for_mode(
            session_factory,
            mode=mode,
            queries=queries,
            iterations=iterations,
            top_k=top_k,
            candidate_k=candidate_k,
        )
        mode_results.append(result)

    engine.dispose()

    return {
        "knowledge_base": FIXTURE_KB,
        "queries": queries,
        "iterations_per_query": iterations,
        "database": database_url or "sqlite:///:memory: (temp)",
        "modes": mode_results,
    }


def _sanitize_summary(summary: dict) -> dict:
    """Remove any secret-like values from the summary before output.

    Recursively walks the dict and replaces values whose keys look like
    secrets with "[redacted]".
    """
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

    return _redact(summary)


def main() -> int:
    args = build_parser().parse_args()
    fixture_root = FIXTURE_ROOT
    if not fixture_root.exists():
        print(
            json.dumps(
                {
                    "error": f"Fixture directory not found: {fixture_root}",
                    "hint": (
                        "Run from the repo root; "
                        "the fixture directory is tests/fixtures/local_ingestion"
                    ),
                }
            ),
            file=sys.stderr,
        )
        return 1

    summary = run_benchmarks(
        iterations=args.iterations,
    )
    summary = _sanitize_summary(summary)

    indent = 2 if args.pretty else None
    json_output = json.dumps(summary, indent=indent, ensure_ascii=False, sort_keys=True)
    print(json_output)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(json_output, encoding="utf-8")
        print(f"\nBenchmark summary written to {output_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
