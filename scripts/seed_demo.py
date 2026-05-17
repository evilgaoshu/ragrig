"""Seed an empty RAGRig install with a tiny demo workspace.

This script is invoked by the container entrypoint when
``RAGRIG_DEMO_SEED=1`` and is also safe to run manually:

    uv run python -m scripts.seed_demo

Behavior:

- Detects whether a knowledge base named ``demo`` already exists; if so,
  exits immediately so the script is idempotent across restarts.
- Otherwise it ingests every Markdown file under ``examples/local-pilot/``
  into a fresh ``demo`` KB and runs indexing with the default
  ``deterministic-local`` embedding provider (no API keys required).

The goal is that a first-time user can run ``docker compose up`` and
immediately hit the web console with something to ask — no manual setup.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ragrig.config import get_settings
from ragrig.db.models import KnowledgeBase
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory

DEMO_KB_NAME = "demo"
DEMO_ROOT = Path(__file__).resolve().parent.parent / "examples" / "local-pilot"


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main() -> int:
    if not DEMO_ROOT.exists():
        _emit({"status": "skipped", "reason": f"demo content missing at {DEMO_ROOT}"})
        return 0

    settings = get_settings()
    engine = create_engine(settings.sqlalchemy_runtime_database_url, pool_pre_ping=True)
    try:
        with Session(engine, expire_on_commit=False) as session:
            existing = session.scalar(
                select(KnowledgeBase).where(KnowledgeBase.name == DEMO_KB_NAME).limit(1)
            )
            if existing is not None:
                _emit({"status": "skipped", "reason": "demo KB already present"})
                return 0

            ingest_report = ingest_local_directory(
                session=session,
                knowledge_base_name=DEMO_KB_NAME,
                root_path=DEMO_ROOT,
                include_patterns=["*.md", "*.txt"],
            )
            index_report = index_knowledge_base(
                session=session,
                knowledge_base_name=DEMO_KB_NAME,
            )
    finally:
        engine.dispose()

    _emit(
        {
            "status": "seeded",
            "knowledge_base": DEMO_KB_NAME,
            "documents": ingest_report.created_documents,
            "chunks_indexed": index_report.chunk_count,
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
