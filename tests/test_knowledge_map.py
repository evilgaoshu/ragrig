from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ragrig.auth import DEFAULT_WORKSPACE_ID
from ragrig.db.models import Base, Document, DocumentVersion, KnowledgeBase, Source
from ragrig.main import create_app
from ragrig.understanding import build_knowledge_map
from ragrig.understanding.service import understand_all_versions

pytestmark = [pytest.mark.integration]


def _seed_kb_with_versions(session: Session, *, texts: list[str]) -> tuple[list[str], str]:
    kb = KnowledgeBase(
        id=uuid.uuid4(),
        name=f"knowledge-map-{uuid.uuid4().hex[:8]}",
        workspace_id=DEFAULT_WORKSPACE_ID,
        metadata_json={},
    )
    session.add(kb)
    source = Source(
        id=uuid.uuid4(),
        knowledge_base_id=kb.id,
        kind="local_directory",
        uri=f"file:///tmp/knowledge-map-{uuid.uuid4().hex[:8]}",
        config_json={},
    )
    session.add(source)

    version_ids: list[str] = []
    for idx, text in enumerate(texts):
        document = Document(
            id=uuid.uuid4(),
            knowledge_base_id=kb.id,
            source_id=source.id,
            uri=f"doc-{idx}.md",
            content_hash=f"doc-hash-{idx}",
            metadata_json={},
        )
        session.add(document)
        session.flush()
        version = DocumentVersion(
            id=uuid.uuid4(),
            document_id=document.id,
            version_number=1,
            content_hash=f"version-hash-{idx}",
            parser_name="markdown",
            parser_config_json={},
            extracted_text=text,
            metadata_json={},
        )
        session.add(version)
        session.flush()
        version_ids.append(str(version.id))

    session.commit()
    return version_ids, str(kb.id)


def _knowledge_map_texts() -> list[str]:
    return [
        (
            "# RAGRig Architecture\n\n"
            "RAGRig uses PostgreSQL and Qdrant for retrieval. "
            "Architecture owners review RAGRig boundaries."
        ),
        (
            "# PostgreSQL Operations\n\n"
            "PostgreSQL backs RAGRig audit events and retrieval metadata. "
            "Operations teams review RAGRig status."
        ),
        (
            "# Evaluation Workflow\n\n"
            "Evaluation compares RAGRig retrieval quality after reindex. "
            "Workflow owners track RAGRig citations."
        ),
    ]


def test_build_knowledge_map_detects_cross_document_relationships(
    sqlite_session: Session,
) -> None:
    _version_ids, kb_id = _seed_kb_with_versions(sqlite_session, texts=_knowledge_map_texts())
    batch = understand_all_versions(
        sqlite_session,
        knowledge_base_id=kb_id,
        provider="deterministic-local",
        profile_id="*.understand.default",
    )
    assert batch.failed == 0

    result = build_knowledge_map(sqlite_session, kb_id)

    assert result is not None
    assert result.status == "ready"
    assert result.stats.included_documents == 3
    assert result.stats.document_nodes == 3
    assert result.stats.cross_document_entity_count >= 1
    assert result.stats.document_relationship_edges >= 2
    assert any(topic.topic == "RAGRig" for topic in result.topic_coverage)
    relationships = [edge for edge in result.edges if edge.relationship == "shares_entities"]
    assert relationships
    assert any("RAGRig" in edge.shared_entities for edge in relationships)


def test_build_knowledge_map_excludes_stale_understanding(
    sqlite_session: Session,
) -> None:
    version_ids, kb_id = _seed_kb_with_versions(
        sqlite_session,
        texts=_knowledge_map_texts()[:2],
    )
    understand_all_versions(
        sqlite_session,
        knowledge_base_id=kb_id,
        provider="deterministic-local",
        profile_id="*.understand.default",
    )
    stale_version = sqlite_session.get(DocumentVersion, uuid.UUID(version_ids[0]))
    assert stale_version is not None
    stale_version.extracted_text += "\n\nFresh text makes the old understanding stale."
    sqlite_session.commit()

    result = build_knowledge_map(sqlite_session, kb_id)

    assert result is not None
    assert result.stats.stale == 1
    assert result.stats.included_documents == 1
    assert any("stale" in limitation for limitation in result.limitations)


def _create_file_session_factory(database_path: Path) -> Callable[[], Session]:
    engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
    Base.metadata.create_all(engine)

    def _factory() -> Session:
        return Session(engine, expire_on_commit=False)

    return _factory


@pytest.mark.anyio
async def test_knowledge_map_endpoint_returns_graph(tmp_path: Path) -> None:
    session_factory = _create_file_session_factory(tmp_path / "knowledge-map-api.db")
    with session_factory() as session:
        _version_ids, kb_id = _seed_kb_with_versions(session, texts=_knowledge_map_texts())
        understand_all_versions(
            session,
            knowledge_base_id=kb_id,
            provider="deterministic-local",
            profile_id="*.understand.default",
        )

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(f"/knowledge-bases/{kb_id}/knowledge-map")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "ready"
        assert payload["stats"]["document_relationship_edges"] >= 2
        assert any(edge["relationship"] == "shares_entities" for edge in payload["edges"])

        missing = await client.get(f"/knowledge-bases/{uuid.uuid4()}/knowledge-map")
        assert missing.status_code == 404
        assert missing.json()["error"] == "knowledge_base_not_found"


def test_knowledge_map_check_cli_writes_pass_artifact(tmp_path: Path) -> None:
    from scripts.knowledge_map_check import main

    output = tmp_path / "knowledge-map-check.json"
    exit_code = main(["--output", str(output), "--pretty"])

    assert exit_code == 0
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["status"] == "pass"
    assert data["knowledge_map"]["stats"]["document_relationship_edges"] >= 2
    assert all(check["status"] == "pass" for check in data["checks"])


def test_makefile_exposes_knowledge_map_check_target() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    assert "knowledge-map-check:" in makefile
    assert "scripts.knowledge_map_check" in makefile
