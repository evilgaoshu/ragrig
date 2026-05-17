"""Smoke test for scripts.seed_demo — idempotent demo bootstrap."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from ragrig.db.models import Base, KnowledgeBase

REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.integration


def _run_seed(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    db_path = tmp_path / "demo-seed.db"
    db_url = f"sqlite+pysqlite:///{db_path}"

    # Prime the schema so the script doesn't need alembic to run.
    engine = create_engine(db_url, future=True)
    Base.metadata.create_all(engine)
    engine.dispose()

    env = os.environ.copy()
    env["DATABASE_URL"] = db_url
    # The script imports ragrig.config which validates settings — keep auth
    # off so we don't trip the production guard that requires a secret key
    # when ragrig_auth_enabled is True.
    env["RAGRIG_AUTH_ENABLED"] = "false"
    return subprocess.run(
        [sys.executable, "-m", "scripts.seed_demo"],
        capture_output=True,
        text=True,
        env=env,
        cwd=REPO_ROOT,
        check=False,
    )


def _kb_count(db_path: Path, kb_name: str) -> int:
    engine = create_engine(f"sqlite+pysqlite:///{db_path}", future=True)
    try:
        with Session(engine) as session:
            kbs = list(session.scalars(select(KnowledgeBase).where(KnowledgeBase.name == kb_name)))
            return len(kbs)
    finally:
        engine.dispose()


def test_seed_creates_demo_kb_then_is_idempotent(tmp_path: Path) -> None:
    first = _run_seed(tmp_path)
    assert first.returncode == 0, first.stderr
    assert "seeded" in first.stdout
    assert _kb_count(tmp_path / "demo-seed.db", "demo") == 1

    # Run again — should be a no-op, no second KB created.
    second = _run_seed(tmp_path)
    assert second.returncode == 0, second.stderr
    assert "skipped" in second.stdout
    assert _kb_count(tmp_path / "demo-seed.db", "demo") == 1
