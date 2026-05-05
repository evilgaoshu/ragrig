from __future__ import annotations

import argparse
import json
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ragrig.config import get_settings
from ragrig.plugins.sinks.object_storage.connector import export_to_object_storage


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an opt-in object storage export smoke check.")
    parser.add_argument(
        "--knowledge-base",
        default=os.environ.get("EXPORT_OBJECT_STORAGE_KB", "fixture-local"),
    )
    parser.add_argument("--bucket", default=os.environ.get("EXPORT_OBJECT_STORAGE_BUCKET"))
    parser.add_argument(
        "--prefix",
        default=os.environ.get("EXPORT_OBJECT_STORAGE_PREFIX", "ragrig-export"),
    )
    parser.add_argument(
        "--endpoint-url", default=os.environ.get("EXPORT_OBJECT_STORAGE_ENDPOINT_URL")
    )
    parser.add_argument("--region", default=os.environ.get("EXPORT_OBJECT_STORAGE_REGION"))
    parser.add_argument(
        "--use-path-style",
        action="store_true",
        default=_env_bool("EXPORT_OBJECT_STORAGE_USE_PATH_STYLE"),
    )
    parser.add_argument(
        "--no-verify-tls",
        action="store_true",
        default=not _env_bool("EXPORT_OBJECT_STORAGE_VERIFY_TLS", True),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=_env_bool("EXPORT_OBJECT_STORAGE_DRY_RUN", True),
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        default=_env_bool("EXPORT_OBJECT_STORAGE_OVERWRITE"),
    )
    parser.add_argument(
        "--path-template",
        default=os.environ.get(
            "EXPORT_OBJECT_STORAGE_PATH_TEMPLATE",
            "{knowledge_base}/{run_id}/{artifact}.{format}",
        ),
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if not args.bucket:
        raise SystemExit(
            "Object storage bucket is required. Pass --bucket or set EXPORT_OBJECT_STORAGE_BUCKET."
        )

    settings = get_settings()
    engine = create_engine(settings.sqlalchemy_runtime_database_url, pool_pre_ping=True)
    with Session(engine, expire_on_commit=False) as session:
        report = export_to_object_storage(
            session,
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
                "path_template": args.path_template,
                "overwrite": args.overwrite,
                "dry_run": args.dry_run,
                "include_retrieval_artifact": True,
                "include_markdown_summary": True,
                "max_retries": 2,
                "connect_timeout_seconds": 10,
                "read_timeout_seconds": 30,
                "object_metadata": {"smoke": "true"},
            },
        )

    print(
        json.dumps(
            {
                "knowledge_base": args.knowledge_base,
                "bucket": args.bucket,
                "prefix": args.prefix,
                "dry_run": report.dry_run,
                "pipeline_run_id": report.pipeline_run_id,
                "artifact_keys": report.artifact_keys,
                "planned_count": report.planned_count,
                "uploaded_count": report.uploaded_count,
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
