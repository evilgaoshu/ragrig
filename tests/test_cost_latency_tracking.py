from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.answer import generate_answer
from ragrig.db.models import Base, Embedding, PipelineRun
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.main import create_app
from ragrig.observability import estimate_model_usage, estimate_tokens
from ragrig.retrieval import search_knowledge_base
from scripts.cost_latency_check import run_cost_latency_check

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@contextmanager
def _create_session(tmp_path: Path) -> Iterator[Session]:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'cost-latency.db'}", future=True)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def _seed_indexed_kb(session: Session, tmp_path: Path, *, knowledge_base: str = "kb") -> None:
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    (docs / "guide.md").write_text(
        "# Guide\n\nRAGRig records model cost and latency for pipeline changes.\n",
        encoding="utf-8",
    )
    ingest_local_directory(session=session, knowledge_base_name=knowledge_base, root_path=docs)
    index_knowledge_base(
        session=session,
        knowledge_base_name=knowledge_base,
        chunk_size=48,
        chunk_overlap=8,
    )


def test_estimate_model_usage_uses_deterministic_zero_cost_rate() -> None:
    usage = estimate_model_usage(
        operation="embedding",
        provider="deterministic-local",
        model="hash-8d",
        input_text="abcdefgh",
    )

    assert estimate_tokens("abcdefgh") == 2
    assert usage["total_tokens_estimated"] == 2
    assert usage["total_cost_usd_estimated"] == 0
    assert usage["rate_source"] == "local_zero_cost"


def test_indexing_persists_cost_latency_summary(tmp_path: Path) -> None:
    with _create_session(tmp_path) as session:
        _seed_indexed_kb(session, tmp_path)

        run = session.scalar(select(PipelineRun).where(PipelineRun.run_type == "chunk_embedding"))
        embeddings = session.scalars(select(Embedding)).all()

    assert run is not None
    summary = run.config_snapshot_json["cost_latency_summary"]
    assert summary["operation_count"] >= 1
    assert summary["total_tokens_estimated"] > 0
    assert summary["total_latency_ms"] >= 0
    assert all("cost_latency" in embedding.metadata_json for embedding in embeddings)


def test_retrieval_and_answer_reports_cost_latency(tmp_path: Path) -> None:
    with _create_session(tmp_path) as session:
        _seed_indexed_kb(session, tmp_path)

        retrieval = search_knowledge_base(
            session=session,
            knowledge_base_name="kb",
            query="cost latency",
            top_k=1,
        )
        answer = generate_answer(
            session=session,
            knowledge_base_name="kb",
            query="How is latency tracked?",
            top_k=1,
        )

    assert retrieval.cost_latency["operation_count"] >= 1
    assert retrieval.cost_latency["phase_latencies_ms"]["query_embedding_ms"] >= 0
    assert answer.cost_latency["operation_count"] >= 2
    assert answer.cost_latency["phase_latencies_ms"]["answer_generation_ms"] >= 0


@pytest.mark.anyio
async def test_cost_latency_api_endpoint(tmp_path: Path) -> None:
    database_path = tmp_path / "cost-latency-api.db"
    engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
    Base.metadata.create_all(engine)

    def _session_factory() -> Session:
        return Session(engine, expire_on_commit=False)

    with _session_factory() as session:
        _seed_indexed_kb(session, tmp_path)

    app = create_app(check_database=lambda: None, session_factory=_session_factory)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/observability/cost-latency?knowledge_base=kb")

    engine.dispose()
    assert response.status_code == 200
    payload = response.json()
    assert payload["run_count"] >= 1
    assert payload["tracked_operation_count"] >= 1
    assert payload["aggregate"]["total_tokens_estimated"] > 0


def test_cost_latency_check_script_generates_pass_artifact() -> None:
    artifact = run_cost_latency_check()

    assert artifact["status"] == "pass"
    assert {check["status"] for check in artifact["checks"]} == {"pass"}
