from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ragrig.config import get_settings
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.ingestion.scanner import scan_paths


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Ingest a local Markdown/Text directory into RAGRig."
    )
    parser.add_argument(
        "--knowledge-base",
        required=True,
        help="Knowledge base name to create or reuse.",
    )
    parser.add_argument("--root-path", required=True, help="Root directory to scan.")
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="Glob pattern to include. Repeat to pass multiple patterns.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Glob pattern to exclude. Repeat to pass multiple patterns.",
    )
    parser.add_argument(
        "--max-file-size-bytes",
        type=int,
        default=10 * 1024 * 1024,
        help="Skip files larger than this many bytes.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned work without writing to DB.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root_path = Path(args.root_path).resolve()
    include_patterns = args.include or None
    exclude_patterns = args.exclude or None

    if args.dry_run:
        scan_result = scan_paths(
            root_path=root_path,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            max_file_size_bytes=args.max_file_size_bytes,
        )
        payload = {
            "dry_run": True,
            "knowledge_base": args.knowledge_base,
            "root_path": str(root_path),
            "discovered": [str(item.path) for item in scan_result.discovered],
            "skipped": [
                {"path": str(item.path), "reason": item.reason} for item in scan_result.skipped
            ],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    settings = get_settings()
    engine = create_engine(settings.sqlalchemy_runtime_database_url, pool_pre_ping=True)
    with Session(engine, expire_on_commit=False) as session:
        report = ingest_local_directory(
            session=session,
            knowledge_base_name=args.knowledge_base,
            root_path=root_path,
            include_patterns=include_patterns,
            exclude_patterns=exclude_patterns,
            max_file_size_bytes=args.max_file_size_bytes,
        )

    print(
        json.dumps(
            {
                "pipeline_run_id": str(report.pipeline_run_id),
                "created_documents": report.created_documents,
                "created_versions": report.created_versions,
                "skipped_count": report.skipped_count,
                "failed_count": report.failed_count,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
