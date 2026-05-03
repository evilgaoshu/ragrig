from __future__ import annotations

import argparse
import json

import psycopg

from ragrig.config import get_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check latest local-ingestion DB state.")
    parser.add_argument(
        "--knowledge-base",
        required=True,
        help="Knowledge base name used for ingestion.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = get_settings()

    with psycopg.connect(settings.runtime_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT kb.id, kb.name
                FROM knowledge_bases kb
                WHERE kb.name = %s
                LIMIT 1
                """,
                (args.knowledge_base,),
            )
            knowledge_base_row = cursor.fetchone()
            if knowledge_base_row is None:
                print(json.dumps({"error": "knowledge_base_not_found"}, indent=2, sort_keys=True))
                return 1

            knowledge_base_id, knowledge_base_name = knowledge_base_row

            cursor.execute(
                """
                SELECT id, status, total_items, success_count, failure_count, config_snapshot_json
                FROM pipeline_runs
                WHERE knowledge_base_id = %s AND run_type = 'local_ingestion'
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (knowledge_base_id,),
            )
            run_row = cursor.fetchone()
            if run_row is None:
                print(json.dumps({"error": "pipeline_run_not_found"}, indent=2, sort_keys=True))
                return 1

            run_id, status, total_items, success_count, failure_count, config_snapshot = run_row

            cursor.execute(
                "SELECT COUNT(*) FROM sources WHERE knowledge_base_id = %s",
                (knowledge_base_id,),
            )
            source_count = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM documents WHERE knowledge_base_id = %s",
                (knowledge_base_id,),
            )
            document_count = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM document_versions dv
                JOIN documents d ON d.id = dv.document_id
                WHERE d.knowledge_base_id = %s
                """,
                (knowledge_base_id,),
            )
            document_version_count = cursor.fetchone()[0]

            cursor.execute(
                "SELECT COUNT(*) FROM pipeline_run_items WHERE pipeline_run_id = %s",
                (run_id,),
            )
            pipeline_run_item_count = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT d.uri, dv.version_number, dv.content_hash, dv.extracted_text
                FROM document_versions dv
                JOIN documents d ON d.id = dv.document_id
                WHERE d.knowledge_base_id = %s
                ORDER BY d.uri, dv.version_number DESC
                LIMIT 5
                """,
                (knowledge_base_id,),
            )
            latest_versions = [
                {
                    "uri": row[0],
                    "version_number": row[1],
                    "content_hash": row[2],
                    "content_preview": row[3][:120],
                }
                for row in cursor.fetchall()
            ]

            cursor.execute(
                """
                SELECT status, COUNT(*)
                FROM pipeline_run_items
                WHERE pipeline_run_id = %s
                GROUP BY status
                ORDER BY status
                """,
                (run_id,),
            )
            item_status_counts = {row[0]: row[1] for row in cursor.fetchall()}

    print(
        json.dumps(
            {
                "knowledge_base": {"id": str(knowledge_base_id), "name": knowledge_base_name},
                "latest_pipeline_run": {
                    "id": str(run_id),
                    "status": status,
                    "total_items": total_items,
                    "success_count": success_count,
                    "failure_count": failure_count,
                    "config_snapshot": config_snapshot,
                },
                "counts": {
                    "sources": source_count,
                    "documents": document_count,
                    "document_versions": document_version_count,
                    "pipeline_run_items": pipeline_run_item_count,
                },
                "pipeline_run_item_status_counts": item_status_counts,
                "latest_document_versions": latest_versions,
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
