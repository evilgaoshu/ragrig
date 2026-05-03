from __future__ import annotations

import json

import psycopg

from ragrig.config import get_settings

HEAD_REVISION = "20260503_0001"

REQUIRED_TABLES = [
    "knowledge_bases",
    "sources",
    "documents",
    "document_versions",
    "chunks",
    "embeddings",
    "pipeline_runs",
    "pipeline_run_items",
]


def evaluate_database_state(
    cursor: psycopg.Cursor[tuple[object, ...]],
    expected_revision: str = HEAD_REVISION,
) -> dict[str, object]:
    cursor.execute("SELECT extname FROM pg_extension WHERE extname = 'vector';")
    extension_row = cursor.fetchone()

    cursor.execute(
        (
            "SELECT tablename FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename = ANY(%s) "
            "ORDER BY tablename;"
        ),
        (REQUIRED_TABLES,),
    )
    present_tables = {row[0] for row in cursor.fetchall()}
    missing_tables = sorted(set(REQUIRED_TABLES) - present_tables)

    cursor.execute("SELECT version_num FROM alembic_version LIMIT 1;")
    revision_row = cursor.fetchone()
    current_revision = revision_row[0] if revision_row else None

    return {
        "current_revision": current_revision,
        "extension": extension_row[0] if extension_row else None,
        "present_tables": sorted(present_tables),
        "missing_tables": missing_tables,
        "revision_matches_head": current_revision == expected_revision,
    }


def main() -> int:
    settings = get_settings()
    with psycopg.connect(settings.runtime_database_url) as connection:
        with connection.cursor() as cursor:
            state = evaluate_database_state(cursor)

    print(json.dumps(state, indent=2, sort_keys=True))
    is_valid = (
        state["extension"] == "vector"
        and not state["missing_tables"]
        and state["revision_matches_head"]
    )
    return 0 if is_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
