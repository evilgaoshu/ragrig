from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ragrig.answer.service import generate_answer
from ragrig.db.models import Base
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.knowledge_graph import get_knowledge_graph, rebuild_knowledge_graph
from ragrig.main import create_app
from ragrig.repositories import get_knowledge_base_by_name
from ragrig.retrieval import search_knowledge_base

pytestmark = [pytest.mark.integration]


def _seed_docs(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "architecture.md").write_text(
        "# Architecture\n\n"
        "AlphaProject uses Postgres for retrieval metadata. "
        "BillingPolicy depends on AlphaProject evidence citations.",
        encoding="utf-8",
    )
    (docs / "billing.md").write_text(
        "# Billing\n\n"
        "BillingPolicy references AlphaProject owners during renewal review. "
        "Postgres stores the audit trail for BillingPolicy changes.",
        encoding="utf-8",
    )
    return docs


def _index_fixture_kb(session: Session, tmp_path: Path, *, kb_name: str = "kg-fixture") -> str:
    ingest_local_directory(
        session=session,
        knowledge_base_name=kb_name,
        root_path=_seed_docs(tmp_path),
    )
    index_knowledge_base(
        session=session,
        knowledge_base_name=kb_name,
        chunk_size=1000,
    )
    kb = get_knowledge_base_by_name(session, kb_name)
    assert kb is not None
    return str(kb.id)


def _create_file_session_factory(database_path: Path) -> Callable[[], Session]:
    engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
    Base.metadata.create_all(engine)

    def _factory() -> Session:
        return Session(engine, expire_on_commit=False)

    return _factory


def test_rebuild_knowledge_graph_persists_source_backed_kg_lite(
    sqlite_session: Session, tmp_path: Path
) -> None:
    kb_id = _index_fixture_kb(sqlite_session, tmp_path)

    graph = rebuild_knowledge_graph(sqlite_session, kb_id)

    assert graph.status == "ready"
    assert graph.stats.entity_count >= 3
    assert graph.stats.mention_count >= 4
    assert graph.stats.relation_count >= 1
    assert graph.stats.relation_evidence_count >= 1
    assert graph.stats.claim_count >= 2
    assert graph.stats.graph_evidence_chunk_count >= 1
    assert any(entity.display_name == "AlphaProject" for entity in graph.entities)
    assert all(entity.evidence_chunks for entity in graph.entities[:3])
    assert all(relation.evidence for relation in graph.relations)
    assert all(claim.source_chunk_id for claim in graph.claims)

    reloaded = get_knowledge_graph(sqlite_session, kb_id)
    assert reloaded.stats.entity_count == graph.stats.entity_count


def test_graph_retrieval_mode_expands_entity_evidence(
    sqlite_session: Session, tmp_path: Path
) -> None:
    kb_id = _index_fixture_kb(sqlite_session, tmp_path)
    rebuild_knowledge_graph(sqlite_session, kb_id)

    report = search_knowledge_base(
        session=sqlite_session,
        knowledge_base_name="kg-fixture",
        query="BillingPolicy AlphaProject relationship",
        top_k=3,
        mode="graph",
    )

    assert report.total_results >= 1
    assert report.graph_context["matched_entities"]
    assert report.graph_context["chunk_scores"]
    assert any(
        stage["stage"] == "graph_expand"
        for result in report.results
        for stage in result.rank_stage_trace.get("stages", [])
    )


def test_answer_trace_includes_rank_and_graph_explainability(
    sqlite_session: Session, tmp_path: Path
) -> None:
    kb_id = _index_fixture_kb(sqlite_session, tmp_path)
    rebuild_knowledge_graph(sqlite_session, kb_id)

    answer = generate_answer(
        session=sqlite_session,
        knowledge_base_name="kg-fixture",
        query="How are BillingPolicy and AlphaProject related?",
        top_k=3,
        mode="graph",
    )

    assert answer.grounding_status == "grounded"
    assert answer.retrieval_trace["graph_context"]["matched_entities"]
    assert answer.retrieval_trace["result_traces"]
    assert any(
        stage["stage"] == "graph_expand"
        for trace in answer.retrieval_trace["result_traces"]
        for stage in trace["rank_stage_trace"]["stages"]
    )


@pytest.mark.anyio
async def test_knowledge_graph_api_rebuild_and_read(tmp_path: Path) -> None:
    session_factory = _create_file_session_factory(tmp_path / "kg-api.db")
    with session_factory() as session:
        kb_id = _index_fixture_kb(session, tmp_path, kb_name="kg-api-fixture")

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        rebuild = await client.post(
            f"/knowledge-bases/{kb_id}/knowledge-graph/rebuild",
            json={"reset": True},
        )
        assert rebuild.status_code == 200
        payload = rebuild.json()
        assert payload["stats"]["entity_count"] >= 3

        response = await client.get(f"/knowledge-bases/{kb_id}/knowledge-graph")
        assert response.status_code == 200
        assert response.json()["stats"]["relation_evidence_count"] >= 1
