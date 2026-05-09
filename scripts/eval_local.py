"""CLI entry point for local evaluation: make eval-local.

Usage:
    uv run python -m scripts.eval_local
    uv run python -m scripts.eval_local --golden tests/fixtures/evaluation_golden.yaml
    uv run python -m scripts.eval_local --baseline evaluation_runs/<id>.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ragrig.config import get_settings
from ragrig.evaluation import run_evaluation
from ragrig.evaluation.report import build_evaluation_run_report
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory

DEFAULT_GOLDEN_PATH = Path("tests/fixtures/evaluation_golden.yaml")
DEFAULT_INGEST_ROOT = Path("tests/fixtures/local_ingestion")


def _ensure_indexed(session: Session, knowledge_base: str, root_path: Path) -> None:
    """Ensure the knowledge base is ingested and indexed.

    If the KB doesn't exist, ingest and index automatically.
    If it exists but has no chunks, re-index.
    """
    from ragrig.repositories import get_knowledge_base_by_name

    kb = get_knowledge_base_by_name(session, knowledge_base)
    if kb is None:
        ingest_local_directory(
            session=session,
            knowledge_base_name=knowledge_base,
            root_path=root_path,
        )
        index_knowledge_base(
            session=session,
            knowledge_base_name=knowledge_base,
            chunk_size=500,
        )
        return

    # Check if KB has chunks
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
            knowledge_base_name=knowledge_base,
            chunk_size=500,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run golden question evaluation against a local knowledge base."
    )
    parser.add_argument(
        "--golden",
        default=str(DEFAULT_GOLDEN_PATH),
        help=f"Path to golden question YAML/JSON file. Default: {DEFAULT_GOLDEN_PATH}",
    )
    parser.add_argument(
        "--knowledge-base",
        default="fixture-local",
        help="Knowledge base name to evaluate. Default: fixture-local",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of results per query. Default: 5",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Optional provider override for retrieval.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Optional model override for retrieval.",
    )
    parser.add_argument(
        "--dimensions",
        type=int,
        default=None,
        help="Optional dimensions override for retrieval.",
    )
    parser.add_argument(
        "--ingest-root",
        default=str(DEFAULT_INGEST_ROOT),
        help=(f"Root directory for local ingestion fixtures. Default: {DEFAULT_INGEST_ROOT}"),
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output path for the evaluation report JSON.",
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="Optional path to a baseline evaluation run JSON for delta computation.",
    )
    parser.add_argument(
        "--store-dir",
        default="evaluation_runs",
        help="Directory to persist evaluation runs. Default: evaluation_runs",
    )
    parser.add_argument(
        "--format",
        choices=["full", "summary"],
        default="full",
        help="Output format: full (with items) or summary (metrics only).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    golden_path = Path(args.golden)

    if not golden_path.exists():
        print(
            json.dumps(
                {
                    "error": f"Golden question file not found: {golden_path}",
                    "hint": f"Create the golden fixture at {golden_path}. "
                    "See tests/fixtures/evaluation_golden.yaml for an example.",
                },
                indent=2,
            )
        )
        return 1

    settings = get_settings()
    engine = create_engine(settings.sqlalchemy_runtime_database_url, pool_pre_ping=True)

    store_dir = Path(args.store_dir)
    baseline_path = Path(args.baseline) if args.baseline else None

    with Session(engine, expire_on_commit=False) as session:
        _ensure_indexed(session, args.knowledge_base, Path(args.ingest_root))

        run = run_evaluation(
            session=session,
            golden_path=golden_path,
            knowledge_base=args.knowledge_base,
            top_k=args.top_k,
            provider=args.provider,
            model=args.model,
            dimensions=args.dimensions,
            baseline_path=baseline_path,
            store_dir=store_dir,
        )

    report = build_evaluation_run_report(
        run,
        include_items=(args.format == "full"),
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"\nReport written to {output_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
