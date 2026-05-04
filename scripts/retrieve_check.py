from __future__ import annotations

import argparse
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ragrig.config import get_settings
from ragrig.retrieval import RetrievalError, search_knowledge_base


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a retrieval query against indexed chunks for a knowledge base."
    )
    parser.add_argument("--knowledge-base", required=True, help="Knowledge base name to query.")
    parser.add_argument("--query", required=True, help="Query text to embed and search.")
    parser.add_argument("--top-k", type=int, default=3, help="Maximum result rows to return.")
    parser.add_argument(
        "--dimensions",
        type=int,
        default=None,
        help="Optional deterministic-local embedding dimensions override.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = get_settings()
    engine = create_engine(settings.sqlalchemy_runtime_database_url, pool_pre_ping=True)

    try:
        with Session(engine, expire_on_commit=False) as session:
            report = search_knowledge_base(
                session=session,
                knowledge_base_name=args.knowledge_base,
                query=args.query,
                top_k=args.top_k,
                dimensions=args.dimensions,
            )
    except RetrievalError as exc:
        print(
            json.dumps(
                {
                    "error": {
                        "code": exc.code,
                        "message": str(exc),
                        "details": exc.details,
                    }
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "knowledge_base": report.knowledge_base,
                "query": report.query,
                "top_k": report.top_k,
                "provider": report.provider,
                "model": report.model,
                "dimensions": report.dimensions,
                "distance_metric": report.distance_metric,
                "total_results": report.total_results,
                "results": [
                    {
                        "document_id": str(result.document_id),
                        "document_version_id": str(result.document_version_id),
                        "chunk_id": str(result.chunk_id),
                        "chunk_index": result.chunk_index,
                        "document_uri": result.document_uri,
                        "source_uri": result.source_uri,
                        "text_preview": result.text_preview,
                        "distance": result.distance,
                        "score": result.score,
                        "chunk_metadata": result.chunk_metadata,
                    }
                    for result in report.results
                ],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
