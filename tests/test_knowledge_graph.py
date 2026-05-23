from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ragrig.answer.service import generate_answer
from ragrig.config import Settings
from ragrig.db.models import Base, Chunk, Workspace
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.knowledge_graph import get_knowledge_graph, rebuild_knowledge_graph
from ragrig.main import create_app
from ragrig.repositories import (
    get_knowledge_base_by_name,
    get_or_create_knowledge_base,
    set_kb_permission,
)
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
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
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
        path["matched_endpoint_count"] == 2 and path["evidence_score"] >= 0.8
        for path in report.graph_context["relation_paths"]
    )
    assert any(
        stage["stage"] == "graph_expand"
        for result in report.results
        for stage in result.rank_stage_trace.get("stages", [])
    )


def test_graph_retrieval_context_filters_protected_acl_evidence(
    sqlite_session: Session, tmp_path: Path
) -> None:
    kb_id = _index_fixture_kb(sqlite_session, tmp_path)
    for chunk in sqlite_session.scalars(select(Chunk)).all():
        chunk.metadata_json = {
            "acl": {
                "visibility": "protected",
                "allowed_principals": ["user:alice"],
            }
        }
    sqlite_session.commit()
    rebuild_knowledge_graph(sqlite_session, kb_id)

    blocked = search_knowledge_base(
        session=sqlite_session,
        knowledge_base_name="kg-fixture",
        query="BillingPolicy AlphaProject relationship",
        top_k=3,
        mode="graph",
        enforce_acl=True,
        principal_ids=["user:bob"],
    )

    assert blocked.total_results == 0
    assert blocked.graph_context.get("matched_entities") in (None, [])
    assert blocked.graph_context.get("chunk_scores") in (None, {})

    allowed = search_knowledge_base(
        session=sqlite_session,
        knowledge_base_name="kg-fixture",
        query="BillingPolicy AlphaProject relationship",
        top_k=3,
        mode="graph",
        enforce_acl=True,
        principal_ids=["user:alice"],
    )

    assert allowed.total_results >= 1
    assert allowed.graph_context["matched_entities"]
    assert allowed.graph_context["chunk_scores"]
    visible_chunk_ids = {str(result.chunk_id) for result in allowed.results}
    assert set(allowed.graph_context["chunk_scores"]).issubset(visible_chunk_ids)


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


@pytest.mark.anyio
async def test_knowledge_graph_relation_feedback_records_summary(tmp_path: Path) -> None:
    session_factory = _create_file_session_factory(tmp_path / "kg-api-feedback.db")
    with session_factory() as session:
        kb_id = _index_fixture_kb(session, tmp_path, kb_name="kg-api-feedback-fixture")

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        rebuild = await client.post(
            f"/knowledge-bases/{kb_id}/knowledge-graph/rebuild",
            json={"reset": True},
        )
        assert rebuild.status_code == 200
        relation_id = rebuild.json()["relations"][0]["id"]

        feedback = await client.post(
            f"/knowledge-bases/{kb_id}/knowledge-graph/relations/{relation_id}/feedback",
            json={"verdict": "incorrect", "note": "predicate is too broad"},
        )
        assert feedback.status_code == 200
        assert feedback.json()["feedback_summary"]["incorrect"] == 1

        response = await client.get(f"/knowledge-bases/{kb_id}/knowledge-graph")
        relation = next(item for item in response.json()["relations"] if item["id"] == relation_id)
        assert relation["metadata"]["feedback_summary"]["incorrect"] == 1


@pytest.mark.anyio
async def test_knowledge_graph_api_enforces_kb_rbac_and_workspace(tmp_path: Path) -> None:
    session_factory = _create_file_session_factory(tmp_path / "kg-api-auth.db")
    with session_factory() as session:
        kb_id = _index_fixture_kb(session, tmp_path, kb_name="kg-api-auth-fixture")

    app = create_app(
        check_database=lambda: None,
        session_factory=session_factory,
        settings=Settings(ragrig_auth_enabled=True, ragrig_open_registration=True),
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        anonymous = await client.get(f"/knowledge-bases/{kb_id}/knowledge-graph")
        assert anonymous.status_code == 401

        owner = await client.post(
            "/auth/register",
            json={"email": "owner@example.com", "password": "hunter2hunter2"},
        )
        assert owner.status_code == 201
        owner_token = owner.json()["token"]
        owner_headers = {"Authorization": f"Bearer {owner_token}"}

        viewer = await client.post(
            "/auth/register",
            json={"email": "viewer@example.com", "password": "hunter2hunter2"},
        )
        assert viewer.status_code == 201
        viewer_token = viewer.json()["token"]
        viewer_headers = {"Authorization": f"Bearer {viewer_token}"}
        viewer_me = await client.get("/auth/me", headers=viewer_headers)
        viewer_id = viewer_me.json()["user_id"]

        viewer_rebuild = await client.post(
            f"/knowledge-bases/{kb_id}/knowledge-graph/rebuild",
            json={"reset": True},
            headers=viewer_headers,
        )
        assert viewer_rebuild.status_code == 403

        owner_rebuild = await client.post(
            f"/knowledge-bases/{kb_id}/knowledge-graph/rebuild",
            json={"reset": True},
            headers=owner_headers,
        )
        assert owner_rebuild.status_code == 200

        viewer_read = await client.get(
            f"/knowledge-bases/{kb_id}/knowledge-graph",
            headers=viewer_headers,
        )
        assert viewer_read.status_code == 200
        assert viewer_read.json()["stats"]["entity_count"] >= 3

        with session_factory() as session:
            set_kb_permission(
                session,
                knowledge_base_id=uuid.UUID(kb_id),
                user_id=uuid.UUID(viewer_id),
                role="none",
            )
            session.commit()

        denied_read = await client.get(
            f"/knowledge-bases/{kb_id}/knowledge-graph",
            headers=viewer_headers,
        )
        assert denied_read.status_code == 403

        with session_factory() as session:
            other_workspace = Workspace(
                id=uuid.uuid4(),
                slug="other-workspace",
                display_name="Other Workspace",
                status="active",
                metadata_json={},
            )
            session.add(other_workspace)
            session.flush()
            other_kb = get_or_create_knowledge_base(
                session,
                "other-kg",
                workspace_id=other_workspace.id,
            )
            session.commit()
            other_kb_id = str(other_kb.id)

        cross_workspace = await client.get(
            f"/knowledge-bases/{other_kb_id}/knowledge-graph",
            headers=owner_headers,
        )
        assert cross_workspace.status_code == 404
