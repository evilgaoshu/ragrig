from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from ragrig.config import get_settings
from ragrig.db.models import Document, DocumentVersion, PipelineRun
from ragrig.plugins.sources.s3.connector import ingest_s3_source


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an opt-in S3-compatible ingestion smoke check."
    )
    parser.add_argument(
        "--knowledge-base", required=True, help="Knowledge base name to create or reuse."
    )
    parser.add_argument("--bucket", required=True, help="Bucket name to scan.")
    parser.add_argument("--prefix", default="", help="Object prefix to scan.")
    parser.add_argument(
        "--endpoint-url",
        default=os.environ.get("S3_ENDPOINT_URL", "http://127.0.0.1:9000"),
        help="S3-compatible endpoint URL.",
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_REGION", "us-east-1"),
        help="AWS region name.",
    )
    parser.add_argument(
        "--use-path-style",
        action="store_true",
        default=True,
        help="Use path-style S3 addressing.",
    )
    parser.add_argument(
        "--verify-tls",
        action="store_true",
        default=False,
        help="Enable TLS verification for HTTPS endpoints.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = get_settings()
    config = {
        "bucket": args.bucket,
        "prefix": args.prefix,
        "endpoint_url": args.endpoint_url,
        "region": args.region,
        "use_path_style": args.use_path_style,
        "verify_tls": args.verify_tls,
        "access_key": "env:AWS_ACCESS_KEY_ID",
        "secret_key": "env:AWS_SECRET_ACCESS_KEY",
        "include_patterns": ["*.md", "*.markdown", "*.txt", "*.text"],
        "exclude_patterns": [],
        "max_object_size_mb": 50,
        "page_size": 1000,
        "max_retries": 3,
        "connect_timeout_seconds": 10,
        "read_timeout_seconds": 30,
    }
    if "AWS_SESSION_TOKEN" in os.environ:
        config["session_token"] = "env:AWS_SESSION_TOKEN"

    engine = create_engine(settings.sqlalchemy_runtime_database_url, pool_pre_ping=True)
    with Session(engine, expire_on_commit=False) as session:
        report = ingest_s3_source(
            session,
            knowledge_base_name=args.knowledge_base,
            config=config,
        )

        latest_run = session.scalars(
            select(PipelineRun).order_by(PipelineRun.started_at.desc())
        ).first()
        document_count = session.scalar(select(func.count(Document.id)))
        version_count = session.scalar(select(func.count(DocumentVersion.id)))

    print(
        json.dumps(
            {
                "pipeline_run_id": str(report.pipeline_run_id),
                "created_documents": report.created_documents,
                "created_versions": report.created_versions,
                "skipped_count": report.skipped_count,
                "failed_count": report.failed_count,
                "latest_run_status": latest_run.status if latest_run is not None else None,
                "document_count": document_count,
                "document_version_count": version_count,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
