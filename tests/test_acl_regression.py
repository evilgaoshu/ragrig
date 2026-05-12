"""Parameterized ACL policy matrix regression tests.

Covers every combination from the ACL policy matrix in
docs/specs/EVI-104-phase3-acl-regression-spec.md.
Each test case asserts visible chunk IDs and deny reason.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from ragrig.db.models import Base, Chunk
from ragrig.indexing.pipeline import index_knowledge_base
from ragrig.ingestion.pipeline import ingest_local_directory
from ragrig.main import create_app
from ragrig.retrieval import search_knowledge_base

pytestmark = [pytest.mark.integration, pytest.mark.slow]


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


@compiles(Vector, "sqlite")
def _compile_vector_for_sqlite(_type, compiler, **kwargs) -> str:
    return compiler.process(JSON(), **kwargs)


def _create_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine, expire_on_commit=False)


def _create_file_session_factory(database_path) -> Callable[[], Session]:
    engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
    Base.metadata.create_all(engine)

    def _factory() -> Session:
        return Session(engine, expire_on_commit=False)

    return _factory


def _seed_documents(tmp_path, files: dict[str, str]):
    docs = tmp_path / "docs"
    docs.mkdir()
    for name, content in files.items():
        (docs / name).write_text(content, encoding="utf-8")
    return docs


def _set_chunk_acl(session: Session, text_contains: str, acl: dict[str, Any]) -> list[str]:
    chunks = session.scalars(select(Chunk)).all()
    chunk_ids: list[str] = []
    for chunk in chunks:
        if text_contains in chunk.text:
            chunk.metadata_json = {
                **chunk.metadata_json,
                "acl": acl,
            }
            chunk_ids.append(str(chunk.id))
    session.commit()
    return chunk_ids


# ── ACL Policy Matrix Test Cases ──────────────────────────────────────

ACL_MATRIX_CASES = [
    # (name, doc_acl, principal_ids, expected_visible, expected_reason)
    pytest.param(
        "public_no_principal",
        {"visibility": "public", "allowed_principals": [], "denied_principals": []},
        None,
        True,
        "public",
        id="1-public-no-principal",
    ),
    pytest.param(
        "public_any_principal",
        {"visibility": "public", "allowed_principals": ["alice"], "denied_principals": []},
        None,
        True,
        "public",
        id="2-public-any-principal",
    ),
    pytest.param(
        "protected_alice_allowed",
        {"visibility": "protected", "allowed_principals": ["alice"], "denied_principals": []},
        ["alice"],
        True,
        "allowed_principal",
        id="3-protected-alice-allowed",
    ),
    pytest.param(
        "protected_group_allowed",
        {"visibility": "protected", "allowed_principals": ["group:eng"], "denied_principals": []},
        ["group:eng"],
        True,
        "allowed_principal",
        id="4-protected-group-allowed",
    ),
    pytest.param(
        "protected_bob_denied",
        {
            "visibility": "protected",
            "allowed_principals": ["alice", "bob"],
            "denied_principals": ["bob"],
        },
        ["bob"],
        False,
        "denied_principal",
        id="5-protected-bob-denied",
    ),
    pytest.param(
        "protected_alice_denied_takes_precedence",
        {"visibility": "protected", "allowed_principals": ["alice"], "denied_principals": ["bob"]},
        ["alice", "bob"],
        False,
        "denied_principal",
        id="6-protected-alice-bob-denied-takes-precedence",
    ),
    pytest.param(
        "protected_wrong_principal",
        {"visibility": "protected", "allowed_principals": ["alice"], "denied_principals": []},
        ["bob"],
        False,
        "no_matching_principal",
        id="7-protected-wrong-principal",
    ),
    pytest.param(
        "protected_no_principal",
        {"visibility": "protected", "allowed_principals": ["alice"], "denied_principals": []},
        None,
        True,
        "no_principal",
        id="8-protected-no-principal",
    ),
    pytest.param(
        "protected_empty_principal",
        {"visibility": "protected", "allowed_principals": ["alice"], "denied_principals": []},
        [],
        False,
        "no_principal",
        id="8b-protected-empty-principal",
    ),
    pytest.param(
        "protected_unknown_principal",
        {"visibility": "protected", "allowed_principals": ["alice"], "denied_principals": []},
        ["unknown"],
        False,
        "no_matching_principal",
        id="9-protected-unknown-principal",
    ),
    pytest.param(
        "unknown_visibility",
        {"visibility": "unknown", "allowed_principals": ["alice"], "denied_principals": []},
        ["alice"],
        False,
        "unknown_visibility",
        id="10-unknown-visibility",
    ),
    pytest.param(
        "protected_alice_in_both_lists",
        {
            "visibility": "protected",
            "allowed_principals": ["alice"],
            "denied_principals": ["alice"],
        },
        ["alice"],
        False,
        "denied_principal",
        id="11-protected-alice-in-both-denied-wins",
    ),
    pytest.param(
        "no_acl_key_default_public",
        None,
        None,
        True,
        "public",
        id="12-no-acl-key-default-public",
    ),
]


@pytest.mark.parametrize(
    ("name", "doc_acl", "principal_ids", "expected_visible", "expected_reason"),
    ACL_MATRIX_CASES,
)
def test_acl_policy_matrix(
    tmp_path,
    name: str,
    doc_acl: dict[str, Any] | None,
    principal_ids: list[str] | None,
    expected_visible: bool,
    expected_reason: str,
) -> None:
    """Parameterized ACL policy matrix: each case asserts visible chunk & reason."""
    docs = _seed_documents(tmp_path, {"target.txt": f"acl matrix test {name}"})

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        if doc_acl is not None:
            _set_chunk_acl(session, f"acl matrix test {name}", doc_acl)

        report = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query=f"acl matrix test {name}",
            principal_ids=principal_ids,
            enforce_acl=True,
        )

    if expected_visible:
        assert report.total_results == 1, f"{name}: expected visible, got no results"
        r = report.results[0]
        assert r.acl_explain is not None, f"{name}: acl_explain should not be None"
        assert r.acl_explain.reason == expected_reason, (
            f"{name}: expected reason={expected_reason}, got {r.acl_explain.reason}"
        )
        if principal_ids is not None:
            assert r.acl_explain.permitted is True, f"{name}: expected permitted=True"
    else:
        assert report.total_results == 0, (
            f"{name}: expected denied, got {report.total_results} results"
        )


# ── Chunk Override Document ACL ──────────────────────────────────────


def test_chunk_override_document_acl(tmp_path) -> None:
    """Chunk-level ACL overrides document-level ACL."""
    docs = _seed_documents(tmp_path, {"doc.txt": "chunk override acl test"})

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        chunks = session.scalars(select(Chunk)).all()
        for chunk in chunks:
            if "chunk override acl test" in chunk.text:
                chunk.metadata_json = {
                    **chunk.metadata_json,
                    "acl": {
                        "visibility": "protected",
                        "allowed_principals": ["alice"],
                        "denied_principals": [],
                        "acl_source": "test",
                        "acl_source_hash": "abc",
                        "inheritance": "document",
                    },
                }
        session.commit()

        # alice should see it
        report_alice = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="chunk override acl test",
            principal_ids=["alice"],
            enforce_acl=True,
        )
        assert report_alice.total_results == 1
        assert report_alice.results[0].acl_explain is not None
        assert report_alice.results[0].acl_explain.permitted is True

        # bob should not see it
        report_bob = search_knowledge_base(
            session=session,
            knowledge_base_name="fixture-local",
            query="chunk override acl test",
            principal_ids=["bob"],
            enforce_acl=True,
        )
        assert report_bob.total_results == 0


# ── Cross-KB / Tenant Isolation ─────────────────────────────────────


def test_cross_kb_tenant_isolation(tmp_path) -> None:
    """Documents in different KBs are isolated by KB name."""
    (tmp_path / "kb_a").mkdir()
    (tmp_path / "kb_b").mkdir()
    docs_a = _seed_documents(tmp_path / "kb_a", {"secret.txt": "zzz secret data only in kb alpha"})
    docs_b = _seed_documents(
        tmp_path / "kb_b", {"public.txt": "aaa public data in kb beta unrelated"}
    )

    with _create_session() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="kb-a",
            root_path=docs_a,
        )
        ingest_local_directory(
            session=session,
            knowledge_base_name="kb-b",
            root_path=docs_b,
        )
        index_knowledge_base(session=session, knowledge_base_name="kb-a")
        index_knowledge_base(session=session, knowledge_base_name="kb-b")

        # Make kb-a docs protected
        chunks_all = session.scalars(select(Chunk)).all()
        for chunk in chunks_all:
            if "zzz secret data" in chunk.text:
                chunk.metadata_json = {
                    **chunk.metadata_json,
                    "acl": {
                        "visibility": "protected",
                        "allowed_principals": ["alice"],
                        "denied_principals": [],
                        "acl_source": "test",
                        "acl_source_hash": "abc",
                        "inheritance": "document",
                    },
                }
        session.commit()

        # Search KB-A as alice → should find it
        report_a = search_knowledge_base(
            session=session,
            knowledge_base_name="kb-a",
            query="zzz secret data only in kb alpha",
            principal_ids=["alice"],
            enforce_acl=True,
        )
        assert report_a.total_results == 1
        assert "zzz secret data" in report_a.results[0].text

        # Search KB-B as alice → should NOT return the secret doc from KB-A
        report_b = search_knowledge_base(
            session=session,
            knowledge_base_name="kb-b",
            query="zzz secret data only in kb alpha",
            principal_ids=["alice"],
            enforce_acl=True,
        )
        # KB-B may return its own public doc, but must NOT return KB-A's secret
        for r in report_b.results:
            assert "zzz secret data" not in r.text, "KB-A secret leaked into KB-B results"


# ── API-level ACL explain consistency ────────────────────────────────


@pytest.mark.anyio
async def test_acl_explain_in_api_response(tmp_path) -> None:
    """The /retrieval/search response includes acl_explain per chunk."""
    database_path = tmp_path / "acl-explain-api.db"
    session_factory = _create_file_session_factory(database_path)

    docs = _seed_documents(tmp_path, {"guide.txt": "acl explain api test"})
    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/retrieval/search",
            json={
                "knowledge_base": "fixture-local",
                "query": "acl explain api test",
                "top_k": 5,
                "principal_ids": ["alice"],
                "enforce_acl": True,
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["total_results"] >= 1
    for result in data["results"]:
        assert "acl_explain" in result
        explain = result["acl_explain"]
        assert explain is not None
        assert "chunk_id" in explain
        assert "visibility" in explain
        assert "permitted" in explain
        assert "reason" in explain
        assert explain["reason"] in (
            "public",
            "allowed_principal",
            "denied_principal",
            "no_matching_principal",
            "no_principal",
            "unknown_visibility",
        )
    assert "acl_explain_summary" in data
    assert "total_chunks" in data["acl_explain_summary"]
    assert "reasons" in data["acl_explain_summary"]


@pytest.mark.anyio
async def test_acl_explain_no_raw_secrets_or_lists(tmp_path) -> None:
    """acl_explain must not contain raw principal lists or secrets."""
    database_path = tmp_path / "acl-explain-safety.db"
    session_factory = _create_file_session_factory(database_path)

    docs = _seed_documents(tmp_path, {"secret.md": "sensitive acl explain test"})
    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        # Set protected ACL with multiple principals
        from ragrig.db.models import Chunk

        chunks = session.scalars(select(Chunk)).all()
        for chunk in chunks:
            if "sensitive acl explain test" in chunk.text:
                chunk.metadata_json = {
                    **chunk.metadata_json,
                    "acl": {
                        "visibility": "protected",
                        "allowed_principals": [
                            "alice-admin",
                            "bob-user",
                            "charlie-viewer",
                        ],
                        "denied_principals": ["eve-blocked"],
                        "acl_source": "test",
                        "acl_source_hash": "abc",
                        "inheritance": "document",
                    },
                }
        session.commit()

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/retrieval/search",
            json={
                "knowledge_base": "fixture-local",
                "query": "sensitive acl explain test",
                "top_k": 5,
                "principal_ids": ["alice-admin"],
                "enforce_acl": True,
            },
        )

    assert response.status_code == 200
    data = response.json()

    for result in data["results"]:
        explain = result["acl_explain"]
        assert isinstance(explain["permitted"], bool)
        assert explain["reason"] in (
            "public",
            "allowed_principal",
            "denied_principal",
            "no_matching_principal",
            "no_principal",
            "unknown_visibility",
        )
        explain_str = str(explain)
        # Must not contain raw principal identities in acl_explain
        assert "alice-admin" not in explain_str, "alice-admin leaked in acl_explain"
        assert "bob-user" not in explain_str, "bob-user leaked in acl_explain"
        assert "charlie-viewer" not in explain_str, "charlie-viewer leaked in acl_explain"
        assert "eve-blocked" not in explain_str, "eve-blocked leaked in acl_explain"
        # Must not expose raw principal lists
        assert "allowed_principals" not in explain_str
        assert "denied_principals" not in explain_str


# ── Case-insensitive principal matching via API ──────────────────────


@pytest.mark.anyio
async def test_acl_case_insensitive_matching(tmp_path) -> None:
    """Principal matching is case-insensitive via the API."""
    database_path = tmp_path / "acl-case-insensitive.db"
    session_factory = _create_file_session_factory(database_path)

    docs = _seed_documents(tmp_path, {"target.md": "case insensitive acl test"})
    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

        from ragrig.db.models import Chunk

        chunks = session.scalars(select(Chunk)).all()
        for chunk in chunks:
            if "case insensitive acl test" in chunk.text:
                chunk.metadata_json = {
                    **chunk.metadata_json,
                    "acl": {
                        "visibility": "protected",
                        "allowed_principals": ["Alice"],
                        "denied_principals": ["Bob"],
                        "acl_source": "test",
                        "acl_source_hash": "abc",
                        "inheritance": "document",
                    },
                }
        session.commit()

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp_alice = await client.post(
            "/retrieval/search",
            json={
                "knowledge_base": "fixture-local",
                "query": "case insensitive acl test",
                "principal_ids": ["alice"],
                "enforce_acl": True,
            },
        )
        resp_bob = await client.post(
            "/retrieval/search",
            json={
                "knowledge_base": "fixture-local",
                "query": "case insensitive acl test",
                "principal_ids": ["bob"],
                "enforce_acl": True,
            },
        )

    assert resp_alice.status_code == 200
    assert resp_alice.json()["total_results"] == 1
    assert resp_bob.status_code == 200
    assert resp_bob.json()["total_results"] == 0


# ── Default public compatibility (Phase 2 semantics) ────────────────


@pytest.mark.anyio
async def test_default_public_compatibility(tmp_path) -> None:
    """Documents without ACL metadata are public (Phase 2 compat)."""
    database_path = tmp_path / "default-public-compat.db"
    session_factory = _create_file_session_factory(database_path)

    docs = _seed_documents(tmp_path, {"note.md": "default public compat test"})
    with session_factory() as session:
        ingest_local_directory(
            session=session,
            knowledge_base_name="fixture-local",
            root_path=docs,
        )
        index_knowledge_base(session=session, knowledge_base_name="fixture-local")

    app = create_app(check_database=lambda: None, session_factory=session_factory)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp_with_principal = await client.post(
            "/retrieval/search",
            json={
                "knowledge_base": "fixture-local",
                "query": "default public compat test",
                "principal_ids": ["anyone"],
                "enforce_acl": True,
            },
        )
        resp_without = await client.post(
            "/retrieval/search",
            json={
                "knowledge_base": "fixture-local",
                "query": "default public compat test",
                "enforce_acl": True,
            },
        )

    assert resp_with_principal.status_code == 200
    assert resp_with_principal.json()["total_results"] == 1
    assert resp_without.status_code == 200
    assert resp_without.json()["total_results"] == 1
