import pytest
from sqlalchemy import MetaData

from ragrig.db.models import Base

pytestmark = pytest.mark.unit


def test_phase_1a_metadata_defines_core_tables() -> None:
    metadata: MetaData = Base.metadata

    assert {
        "knowledge_bases",
        "audit_events",
        "sources",
        "documents",
        "document_versions",
        "chunks",
        "embeddings",
        "pipeline_runs",
        "pipeline_run_items",
    }.issubset(metadata.tables.keys())

    documents = metadata.tables["documents"]
    document_versions = metadata.tables["document_versions"]
    embeddings = metadata.tables["embeddings"]
    pipeline_runs = metadata.tables["pipeline_runs"]
    audit_events = metadata.tables["audit_events"]

    assert documents.c.id.primary_key
    assert document_versions.c.document_id.references(documents.c.id)
    assert embeddings.c.chunk_id.references(metadata.tables["chunks"].c.id)
    assert embeddings.c.dimensions.nullable is False
    assert str(embeddings.c.embedding.type) == "VECTOR"
    assert audit_events.c.event_type.nullable is False
    assert audit_events.c.payload_json.nullable is False

    document_fk_targets = {
        element.target_fullname
        for fk in documents.foreign_key_constraints
        for element in fk.elements
    }
    pipeline_run_fk_targets = {
        element.target_fullname
        for fk in pipeline_runs.foreign_key_constraints
        for element in fk.elements
    }

    assert {"sources.knowledge_base_id", "sources.id"}.issubset(document_fk_targets)
    assert {"sources.knowledge_base_id", "sources.id"}.issubset(pipeline_run_fk_targets)


def test_chunks_and_embeddings_support_one_to_many_embeddings() -> None:
    embeddings = Base.metadata.tables["embeddings"]

    fk_targets = {
        element.target_fullname
        for fk in embeddings.foreign_key_constraints
        for element in fk.elements
    }

    assert fk_targets == {"chunks.id"}


def test_sources_expose_composite_key_for_same_knowledge_base_references() -> None:
    sources = Base.metadata.tables["sources"]

    composite_uniques = [
        tuple(column.name for column in constraint.columns)
        for constraint in sources.constraints
        if getattr(constraint, "__visit_name__", None) == "unique_constraint"
    ]

    assert ("knowledge_base_id", "id") in composite_uniques


def test_workspace_auth_phase_1_tables_match_design_contract() -> None:
    metadata: MetaData = Base.metadata

    assert {
        "workspaces",
        "users",
        "workspace_memberships",
        "api_keys",
        "user_sessions",
    }.issubset(metadata.tables.keys())

    workspaces = metadata.tables["workspaces"]
    users = metadata.tables["users"]
    memberships = metadata.tables["workspace_memberships"]
    api_keys = metadata.tables["api_keys"]
    user_sessions = metadata.tables["user_sessions"]

    assert workspaces.c.slug.unique
    assert workspaces.c.display_name.nullable is False
    assert users.c.email.unique
    assert memberships.c.workspace_id.references(workspaces.c.id)
    assert memberships.c.user_id.references(users.c.id)
    assert api_keys.c.workspace_id.references(workspaces.c.id)
    assert api_keys.c.created_by_user_id.references(users.c.id)
    assert api_keys.c.prefix.unique
    assert "secret" not in api_keys.c
    assert "secret_hash" in api_keys.c
    assert user_sessions.c.token_hash.unique
    assert "token" not in user_sessions.c
    assert user_sessions.c.expires_at.nullable is False
