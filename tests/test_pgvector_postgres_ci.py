from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text

pytestmark = [pytest.mark.integration]


def _postgres_url() -> str | None:
    raw = os.getenv("RAGRIG_PGVECTOR_TEST_DATABASE_URL")
    if not raw:
        return None
    if raw.startswith("postgresql+psycopg://"):
        return raw
    if raw.startswith("postgresql://"):
        return raw.replace("postgresql://", "postgresql+psycopg://", 1)
    return raw


def test_pgvector_cosine_distance_ordering_against_real_postgres() -> None:
    database_url = _postgres_url()
    if not database_url:
        pytest.skip("RAGRIG_PGVECTOR_TEST_DATABASE_URL is not configured")

    engine = create_engine(database_url, future=True)
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            exact_distance = conn.execute(
                text("SELECT '[1,0,0]'::vector <=> '[0,1,0]'::vector")
            ).scalar_one()
            rows = conn.execute(
                text(
                    """
                    WITH items(id, embedding) AS (
                        VALUES
                            (1, '[1,0,0]'::vector),
                            (2, '[0,1,0]'::vector),
                            (3, '[0.5,0.5,0]'::vector)
                    )
                    SELECT id, embedding <=> '[1,0,0]'::vector AS distance
                    FROM items
                    ORDER BY distance ASC, id ASC
                    """
                )
            ).all()
    finally:
        engine.dispose()

    assert float(exact_distance) == pytest.approx(1.0, abs=1e-9)
    assert [row.id for row in rows] == [1, 3, 2]
    assert float(rows[0].distance) == pytest.approx(0.0, abs=1e-9)
    assert float(rows[1].distance) == pytest.approx(1.0 - (2**-0.5), abs=1e-9)
    assert float(rows[2].distance) == pytest.approx(1.0, abs=1e-9)
