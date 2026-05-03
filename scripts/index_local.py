from __future__ import annotations

import argparse
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ragrig.config import get_settings
from ragrig.indexing import index_knowledge_base


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Chunk and embed the latest ingested document versions for a knowledge base."
    )
    parser.add_argument("--knowledge-base", required=True, help="Knowledge base name to index.")
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=500,
        help="Maximum characters per chunk.",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=50,
        help="Character overlap between adjacent chunks.",
    )
    parser.add_argument(
        "--embedding-dimensions",
        type=int,
        default=8,
        help="Deterministic local embedding dimensions.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = get_settings()
    engine = create_engine(settings.sqlalchemy_runtime_database_url, pool_pre_ping=True)

    with Session(engine, expire_on_commit=False) as session:
        report = index_knowledge_base(
            session=session,
            knowledge_base_name=args.knowledge_base,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
            embedding_dimensions=args.embedding_dimensions,
        )

    print(
        json.dumps(
            {
                "chunk_count": report.chunk_count,
                "embedding_count": report.embedding_count,
                "failed_count": report.failed_count,
                "indexed_count": report.indexed_count,
                "pipeline_run_id": str(report.pipeline_run_id),
                "skipped_count": report.skipped_count,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
