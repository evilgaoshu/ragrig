from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ragrig.config import get_settings
from ragrig.db.models import DocumentVersion, PipelineRun
from ragrig.plugins.sources.s3.connector import ingest_s3_source


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an opt-in S3-compatible ingestion smoke check."
    )
    parser.add_argument(
        "--knowledge-base",
        default=os.environ.get("S3_CHECK_KB", "fixture-s3"),
    )
    parser.add_argument("--bucket", default=os.environ.get("S3_BUCKET"), required=False)
    parser.add_argument("--prefix", default=os.environ.get("S3_PREFIX", "ragrig-smoke"))
    parser.add_argument("--endpoint-url", default=os.environ.get("S3_ENDPOINT_URL"))
    parser.add_argument("--region", default=os.environ.get("S3_REGION"))
    parser.add_argument(
        "--use-path-style", action="store_true", default=_env_bool("S3_USE_PATH_STYLE")
    )
    parser.add_argument(
        "--no-verify-tls", action="store_true", default=not _env_bool("S3_VERIFY_TLS", True)
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=int(os.environ.get("S3_PAGE_SIZE", "100")),
    )
    parser.add_argument(
        "--max-object-size-mb",
        type=float,
        default=float(os.environ.get("S3_MAX_OBJECT_SIZE_MB", "50")),
    )
    parser.add_argument(
        "--max-retries", type=int, default=int(os.environ.get("S3_MAX_RETRIES", "2"))
    )
    parser.add_argument(
        "--seed-from",
        default=os.environ.get("S3_SEED_FROM", "tests/fixtures/local_ingestion"),
        help="Optional local directory to upload into the target bucket before ingesting.",
    )
    return parser


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _seed_bucket(
    *,
    bucket: str,
    prefix: str,
    endpoint_url: str | None,
    region: str | None,
    use_path_style: bool,
    verify_tls: bool,
    source_root: Path,
) -> list[str]:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError

    if not source_root.exists():
        return []

    session = boto3.session.Session(
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        aws_session_token=os.environ.get("AWS_SESSION_TOKEN"),
        region_name=region,
    )
    client = session.client(
        "s3",
        endpoint_url=endpoint_url,
        verify=verify_tls,
        config=Config(s3={"addressing_style": "path" if use_path_style else "auto"}),
    )
    try:
        client.create_bucket(Bucket=bucket)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
            raise

    uploaded: list[str] = []
    for path in sorted(source_root.rglob("*")):
        if not path.is_file():
            continue
        key_prefix = prefix.strip("/")
        key = path.relative_to(source_root).as_posix()
        if key_prefix:
            key = f"{key_prefix}/{key}"
        client.put_object(Bucket=bucket, Key=key, Body=path.read_bytes())
        uploaded.append(key)
    return uploaded


def main() -> int:
    args = build_parser().parse_args()
    if not args.bucket:
        raise SystemExit("S3 bucket is required. Pass --bucket or set S3_BUCKET.")

    seeded = _seed_bucket(
        bucket=args.bucket,
        prefix=args.prefix,
        endpoint_url=args.endpoint_url,
        region=args.region,
        use_path_style=args.use_path_style,
        verify_tls=not args.no_verify_tls,
        source_root=Path(args.seed_from),
    )

    settings = get_settings()
    engine = create_engine(settings.sqlalchemy_runtime_database_url, pool_pre_ping=True)
    with Session(engine, expire_on_commit=False) as session:
        report = ingest_s3_source(
            session=session,
            knowledge_base_name=args.knowledge_base,
            config={
                "bucket": args.bucket,
                "prefix": args.prefix,
                "endpoint_url": args.endpoint_url,
                "region": args.region,
                "use_path_style": args.use_path_style,
                "verify_tls": not args.no_verify_tls,
                "access_key": "env:AWS_ACCESS_KEY_ID",
                "secret_key": "env:AWS_SECRET_ACCESS_KEY",
                "session_token": (
                    "env:AWS_SESSION_TOKEN" if os.environ.get("AWS_SESSION_TOKEN") else None
                ),
                "include_patterns": ["*.md", "*.txt", "*.markdown", "*.text"],
                "exclude_patterns": [],
                "max_object_size_mb": args.max_object_size_mb,
                "page_size": args.page_size,
                "max_retries": args.max_retries,
                "connect_timeout_seconds": 10,
                "read_timeout_seconds": 30,
            },
        )
        latest_run = session.scalars(
            select(PipelineRun).order_by(PipelineRun.started_at.desc())
        ).first()
        version_count = session.scalars(select(DocumentVersion)).all()

    print(
        json.dumps(
            {
                "knowledge_base": args.knowledge_base,
                "bucket": args.bucket,
                "prefix": args.prefix,
                "seeded_keys": seeded,
                "report": {
                    "pipeline_run_id": str(report.pipeline_run_id),
                    "created_documents": report.created_documents,
                    "created_versions": report.created_versions,
                    "skipped_count": report.skipped_count,
                    "failed_count": report.failed_count,
                },
                "latest_run": {
                    "status": latest_run.status if latest_run is not None else None,
                    "total_items": latest_run.total_items if latest_run is not None else None,
                    "success_count": latest_run.success_count if latest_run is not None else None,
                    "failure_count": latest_run.failure_count if latest_run is not None else None,
                },
                "document_version_count": len(version_count),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
