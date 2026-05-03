from __future__ import annotations

import argparse
import json

import psycopg

from ragrig.config import get_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check latest chunk/embedding DB state.")
    parser.add_argument(
        "--knowledge-base",
        required=True,
        help="Knowledge base name used for chunking and embedding.",
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
                WHERE knowledge_base_id = %s AND run_type = 'chunk_embedding'
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
                """
                SELECT COUNT(*)
                FROM chunks c
                JOIN document_versions dv ON dv.id = c.document_version_id
                JOIN documents d ON d.id = dv.document_id
                WHERE d.knowledge_base_id = %s
                """,
                (knowledge_base_id,),
            )
            chunk_count = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT COUNT(*)
                FROM embeddings e
                JOIN chunks c ON c.id = e.chunk_id
                JOIN document_versions dv ON dv.id = c.document_version_id
                JOIN documents d ON d.id = dv.document_id
                WHERE d.knowledge_base_id = %s
                """,
                (knowledge_base_id,),
            )
            embedding_count = cursor.fetchone()[0]

            cursor.execute(
                """
                SELECT provider, model, dimensions, COUNT(*)
                FROM embeddings e
                JOIN chunks c ON c.id = e.chunk_id
                JOIN document_versions dv ON dv.id = c.document_version_id
                JOIN documents d ON d.id = dv.document_id
                WHERE d.knowledge_base_id = %s
                GROUP BY provider, model, dimensions
                ORDER BY provider, model, dimensions
                """,
                (knowledge_base_id,),
            )
            dimension_rows = [
                {
                    "provider": row[0],
                    "model": row[1],
                    "dimensions": row[2],
                    "count": row[3],
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

            cursor.execute(
                """
                SELECT d.uri, dv.version_number, c.chunk_index, c.char_start, c.char_end, c.text
                FROM chunks c
                JOIN document_versions dv ON dv.id = c.document_version_id
                JOIN documents d ON d.id = dv.document_id
                WHERE d.knowledge_base_id = %s
                ORDER BY d.uri, dv.version_number DESC, c.chunk_index
                LIMIT 8
                """,
                (knowledge_base_id,),
            )
            latest_chunks = [
                {
                    "uri": row[0],
                    "version_number": row[1],
                    "chunk_index": row[2],
                    "char_start": row[3],
                    "char_end": row[4],
                    "text_preview": row[5][:120],
                }
                for row in cursor.fetchall()
            ]

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
                    "chunks": chunk_count,
                    "embeddings": embedding_count,
                },
                "embedding_dimensions": dimension_rows,
                "pipeline_run_item_status_counts": item_status_counts,
                "latest_chunks": latest_chunks,
            },
            indent=2,
            sort_keys=True,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
