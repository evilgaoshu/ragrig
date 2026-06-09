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
from ragrig.db.models import (
    AuditEvent,
    Base,
    Chunk,
    KnowledgeGraphRelation,
    PipelineRun,
    Workspace,
)
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.knowledge_graph import (
    ExtractedClaim,
    ExtractedEntity,
    ExtractedRelationship,
    KnowledgeGraphExtraction,
    get_knowledge_graph,
    rebuild_knowledge_graph,
)
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


def _index_fixture_kb(
    session: Session,
    tmp_path: Path,
    *,
    kb_name: str = "kg-fixture",
    kg_extract: bool = False,
) -> str:
    ingest_local_directory(
        session=session,
        knowledge_base_name=kb_name,
        root_path=_seed_docs(tmp_path),
    )
    index_knowledge_base(
        session=session,
        knowledge_base_name=kb_name,
        chunk_size=1000,
        kg_extract=kg_extract,
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


def test_index_pipeline_optional_kg_stage_records_trace_and_audit(
    sqlite_session: Session, tmp_path: Path
) -> None:
    kb_id = _index_fixture_kb(sqlite_session, tmp_path, kg_extract=True)

    graph = get_knowledge_graph(sqlite_session, kb_id)
    run = sqlite_session.scalars(
        select(PipelineRun).where(PipelineRun.run_type == "chunk_embedding")
    ).one()
    audit = sqlite_session.scalars(
        select(AuditEvent).where(AuditEvent.event_type == "kg_extract")
    ).one()

    assert run is not None
    assert run.config_snapshot_json["stages"] == ["chunk", "embed", "index", "kg_extract"]
    assert run.config_snapshot_json["kg_extract_result"]["status"] == "completed"
    assert graph.trace["pipeline_run_id"] == str(run.id)
    assert graph.trace["source_document_version_count"] == 2
    assert graph.trace["source_document_version_fingerprint"]
    assert audit.run_id == run.id


def test_provider_extractor_contract_persists_source_backed_outputs(
    sqlite_session: Session, tmp_path: Path
) -> None:
    kb_id = _index_fixture_kb(sqlite_session, tmp_path)

    class FixtureExtractor:
        name = "fixture-provider"
        version = "fixture-v1"

        def extract(self, sources):
            source = sources[0]
            return KnowledgeGraphExtraction(
                entities=[
                    ExtractedEntity(name="AlphaProject", source_chunk_id=source.chunk_id),
                    ExtractedEntity(name="BillingPolicy", source_chunk_id=source.chunk_id),
                ],
                relationships=[
                    ExtractedRelationship(
                        subject="BillingPolicy",
                        predicate="depends_on",
                        object="AlphaProject",
                        source_chunk_id=source.chunk_id,
                        claim="BillingPolicy depends on AlphaProject",
                        confidence=0.9,
                    )
                ],
                claims=[
                    ExtractedClaim(
                        text="BillingPolicy depends on AlphaProject.",
                        source_chunk_id=source.chunk_id,
                        confidence=0.9,
                    )
                ],
                metadata={"provider": "fixture"},
            )

    graph = rebuild_knowledge_graph(sqlite_session, kb_id, extractor=FixtureExtractor())

    assert graph.trace["extractor_name"] == "fixture-provider"
    assert graph.trace["extractor_version"] == "fixture-v1"
    assert graph.relations[0].predicate == "depends_on"
    assert graph.relations[0].evidence[0].chunk_id
    assert graph.relations[0].evidence[0].document_version_id
    assert graph.claims[0].source_chunk_id

    relationship_only = search_knowledge_base(
        session=sqlite_session,
        knowledge_base_name="kg-fixture",
        query="What depends on something else?",
        top_k=3,
        mode="graph",
    )
    assert relationship_only.graph_context["matched_entities"] == []
    assert relationship_only.graph_context["matched_relationships"][0]["match_type"] == "predicate"


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
    assert report.graph_context["matched_relationships"]
    assert report.graph_context["chunk_scores"]
    assert any(
        path["matched_endpoint_count"] == 2 and path["evidence_score"] >= 0.8
        for path in report.graph_context["relation_paths"]
    )
    assert all(
        relationship["evidence"][0]["chunk_id"]
        and relationship["evidence"][0]["document_id"]
        and relationship["evidence"][0]["document_version_id"]
        for relationship in report.graph_context["matched_relationships"]
    )
    assert report.graph_context["rank_movement"]
    assert all("rank_after" in movement for movement in report.graph_context["rank_movement"])
    assert any(
        stage["stage"] == "graph_expand"
        for result in report.results
        for stage in result.rank_stage_trace.get("stages", [])
    )


def test_graph_retrieval_matches_entity_aliases(sqlite_session: Session, tmp_path: Path) -> None:
    kb_id = _index_fixture_kb(sqlite_session, tmp_path)
    rebuild_knowledge_graph(sqlite_session, kb_id)

    report = search_knowledge_base(
        session=sqlite_session,
        knowledge_base_name="kg-fixture",
        query="How is the billing policy related to alpha project?",
        top_k=3,
        mode="graph",
    )

    matched_names = {
        entity["display_name"] for entity in report.graph_context.get("matched_entities", [])
    }
    assert {"AlphaProject", "BillingPolicy"}.issubset(matched_names)


def test_graph_retrieval_suppresses_incorrect_relation_feedback(
    sqlite_session: Session, tmp_path: Path
) -> None:
    kb_id = _index_fixture_kb(sqlite_session, tmp_path)
    rebuild_knowledge_graph(sqlite_session, kb_id)

    before = search_knowledge_base(
        session=sqlite_session,
        knowledge_base_name="kg-fixture",
        query="BillingPolicy AlphaProject relationship",
        top_k=3,
        mode="graph",
    )
    assert before.graph_context["relation_paths"]

    for relation in sqlite_session.scalars(select(KnowledgeGraphRelation)).all():
        relation.metadata_json = {
            **(relation.metadata_json or {}),
            "feedback_summary": {
                "total": 1,
                "incorrect": 1,
                "correct": 0,
                "needs_review": 0,
            },
        }
    sqlite_session.commit()

    after = search_knowledge_base(
        session=sqlite_session,
        knowledge_base_name="kg-fixture",
        query="BillingPolicy AlphaProject relationship",
        top_k=3,
        mode="graph",
    )

    assert after.graph_context["relation_paths"] == []
    assert after.graph_context["diagnostics"]["relation_feedback_aware"] is True
    assert after.graph_context["diagnostics"]["suppressed_relation_count"] >= 1
    assert before.graph_context["chunk_scores"] != after.graph_context["chunk_scores"]


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
    assert blocked.degraded_reason == "graph_acl_no_evidence"
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


def test_graph_modes_use_stable_no_data_and_stale_degraded_reasons(
    sqlite_session: Session, tmp_path: Path
) -> None:
    kb_id = _index_fixture_kb(sqlite_session, tmp_path)

    no_graph = search_knowledge_base(
        session=sqlite_session,
        knowledge_base_name="kg-fixture",
        query="BillingPolicy AlphaProject relationship",
        top_k=3,
        mode="graph",
    )
    assert no_graph.total_results >= 1
    assert no_graph.degraded_reason == "graph_no_data"

    rebuild_knowledge_graph(sqlite_session, kb_id)
    no_match = search_knowledge_base(
        session=sqlite_session,
        knowledge_base_name="kg-fixture",
        query="zzzz_unrelated_token",
        top_k=3,
        mode="graph",
    )
    assert no_match.total_results >= 1
    assert no_match.degraded_reason == "graph_no_match"

    index_knowledge_base(
        session=sqlite_session,
        knowledge_base_name="kg-fixture",
        chunk_size=1000,
        force_reindex=True,
    )

    stale = search_knowledge_base(
        session=sqlite_session,
        knowledge_base_name="kg-fixture",
        query="BillingPolicy AlphaProject relationship",
        top_k=3,
        mode="graph",
    )
    assert stale.total_results >= 1
    assert stale.degraded_reason == "graph_stale"


def test_index_pipeline_kg_extraction_failure_is_auditable_and_does_not_break_dense(
    sqlite_session: Session, tmp_path: Path
) -> None:
    ingest_local_directory(
        session=sqlite_session,
        knowledge_base_name="kg-failure",
        root_path=_seed_docs(tmp_path),
    )

    class FailingExtractor:
        name = "failing-provider"
        version = "failing-v1"

        def extract(self, _sources):
            raise RuntimeError("provider unavailable")

    report = index_knowledge_base(
        session=sqlite_session,
        knowledge_base_name="kg-failure",
        chunk_size=1000,
        kg_extract=True,
        kg_extractor=FailingExtractor(),
    )
    graph_report = search_knowledge_base(
        session=sqlite_session,
        knowledge_base_name="kg-failure",
        query="BillingPolicy",
        top_k=3,
        mode="graph",
    )

    assert report.kg_extract_status == "failed"
    assert report.kg_extract_trace["degraded_reason"] == "graph_extraction_failed"
    assert graph_report.total_results >= 1
    assert graph_report.degraded_reason == "graph_extraction_failed"
    assert sqlite_session.scalars(
        select(AuditEvent).where(AuditEvent.event_type == "kg_extract")
    ).one()


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
async def test_retrieval_preferences_persist_on_knowledge_base(tmp_path: Path) -> None:
    session_factory = _create_file_session_factory(tmp_path / "kg-api-retrieval-prefs.db")
    with session_factory() as session:
        kb_id = _index_fixture_kb(session, tmp_path, kb_name="kg-api-retrieval-prefs")

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)
    payload = {
        "mode": "hybrid_graph",
        "lexical_weight": 0.25,
        "vector_weight": 0.75,
        "candidate_k": 24,
        "graph_weight": 0.45,
        "graph_depth": 2,
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        saved = await client.put(
            f"/knowledge-bases/{kb_id}/retrieval-preferences",
            json=payload,
        )
        assert saved.status_code == 200
        assert saved.json()["preferences"]["mode"] == "hybrid_graph"

        loaded = await client.get(f"/knowledge-bases/{kb_id}/retrieval-preferences")
        assert loaded.status_code == 200
        preferences = loaded.json()["preferences"]
        assert preferences["mode"] == "hybrid_graph"
        assert preferences["graph_weight"] == 0.45
        assert preferences["graph_depth"] == 2

    with session_factory() as session:
        kb = get_knowledge_base_by_name(session, "kg-api-retrieval-prefs")
        assert kb is not None
        assert kb.metadata_json["retrieval_preferences"]["mode"] == "hybrid_graph"


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
