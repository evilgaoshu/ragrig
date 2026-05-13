from __future__ import annotations

import pytest
from sqlalchemy import select

from ragrig.acl import AclMetadata
from ragrig.db.models import AuditEvent, Chunk, DocumentVersion, PipelineRun, PipelineRunItem
from ragrig.repositories import (
    create_pipeline_run,
    create_pipeline_run_item,
    get_document_by_uri,
    get_knowledge_base_by_name,
    get_next_version_number,
    get_or_create_document,
    get_or_create_knowledge_base,
    get_or_create_source,
    list_latest_document_versions,
    set_chunk_acl,
    set_document_acl,
)

pytestmark = pytest.mark.integration


def test_repository_helpers_create_and_update_entities(sqlite_session) -> None:
    knowledge_base = get_or_create_knowledge_base(sqlite_session, "default")
    source = get_or_create_source(
        sqlite_session,
        knowledge_base_id=knowledge_base.id,
        uri="/tmp/docs",
        config_json={"include_patterns": ["*.md"]},
    )
    document, created = get_or_create_document(
        sqlite_session,
        knowledge_base_id=knowledge_base.id,
        source_id=source.id,
        uri="/tmp/docs/guide.md",
        content_hash="hash-v1",
        mime_type="text/markdown",
        metadata_json={"version": 1},
    )

    updated_source = get_or_create_source(
        sqlite_session,
        knowledge_base_id=knowledge_base.id,
        uri="/tmp/docs",
        config_json={"include_patterns": ["*.txt"]},
    )
    updated_document, was_created = get_or_create_document(
        sqlite_session,
        knowledge_base_id=knowledge_base.id,
        source_id=source.id,
        uri=document.uri,
        content_hash="hash-v2",
        mime_type="text/plain",
        metadata_json={"version": 2},
    )

    assert created is True
    assert updated_source.id == source.id
    assert updated_source.config_json == {"include_patterns": ["*.txt"]}
    assert was_created is False
    assert updated_document.id == document.id
    assert updated_document.content_hash == "hash-v2"
    assert updated_document.mime_type == "text/plain"
    assert updated_document.metadata_json == {"version": 2}
    assert get_knowledge_base_by_name(sqlite_session, "default") == knowledge_base
    assert (
        get_document_by_uri(
            sqlite_session,
            knowledge_base_id=knowledge_base.id,
            uri=document.uri,
        )
        == document
    )


def test_document_version_helpers_and_pipeline_run_helpers(sqlite_session) -> None:
    knowledge_base = get_or_create_knowledge_base(sqlite_session, "default")
    source = get_or_create_source(
        sqlite_session,
        knowledge_base_id=knowledge_base.id,
        uri="/tmp/docs",
        config_json={},
    )
    alpha, _ = get_or_create_document(
        sqlite_session,
        knowledge_base_id=knowledge_base.id,
        source_id=source.id,
        uri="/tmp/docs/a.md",
        content_hash="alpha",
        mime_type="text/markdown",
        metadata_json={},
    )
    beta, _ = get_or_create_document(
        sqlite_session,
        knowledge_base_id=knowledge_base.id,
        source_id=source.id,
        uri="/tmp/docs/b.md",
        content_hash="beta",
        mime_type="text/markdown",
        metadata_json={},
    )

    sqlite_session.add_all(
        [
            DocumentVersion(
                document_id=alpha.id,
                version_number=1,
                content_hash="alpha-v1",
                parser_name="markdown",
                parser_config_json={},
                extracted_text="alpha v1",
                metadata_json={},
            ),
            DocumentVersion(
                document_id=alpha.id,
                version_number=2,
                content_hash="alpha-v2",
                parser_name="markdown",
                parser_config_json={},
                extracted_text="alpha v2",
                metadata_json={},
            ),
            DocumentVersion(
                document_id=beta.id,
                version_number=1,
                content_hash="beta-v1",
                parser_name="markdown",
                parser_config_json={},
                extracted_text="beta v1",
                metadata_json={},
            ),
        ]
    )
    sqlite_session.flush()

    run = create_pipeline_run(
        sqlite_session,
        knowledge_base_id=knowledge_base.id,
        source_id=source.id,
        config_snapshot_json={"root_path": "/tmp/docs"},
    )
    item = create_pipeline_run_item(
        sqlite_session,
        pipeline_run_id=run.id,
        document_id=alpha.id,
        status="success",
        metadata_json={"file_name": "a.md"},
    )

    latest_versions = list_latest_document_versions(
        sqlite_session,
        knowledge_base_id=knowledge_base.id,
    )

    assert get_next_version_number(sqlite_session, document_id=alpha.id) == 3
    assert [version.extracted_text for version in latest_versions] == ["alpha v2", "beta v1"]
    assert sqlite_session.scalar(select(PipelineRun).where(PipelineRun.id == run.id)) == run
    assert (
        sqlite_session.scalar(select(PipelineRunItem).where(PipelineRunItem.id == item.id)) == item
    )
    assert item.error_message is None
    assert item.finished_at is not None


def test_acl_crud_writes_safe_audit_events(sqlite_session) -> None:
    knowledge_base = get_or_create_knowledge_base(sqlite_session, "acl-kb")
    source = get_or_create_source(
        sqlite_session,
        knowledge_base_id=knowledge_base.id,
        uri="/tmp/acl",
        config_json={},
    )
    document, _ = get_or_create_document(
        sqlite_session,
        knowledge_base_id=knowledge_base.id,
        source_id=source.id,
        uri="/tmp/acl/private.md",
        content_hash="hash",
        mime_type="text/markdown",
        metadata_json={},
    )
    version = DocumentVersion(
        document_id=document.id,
        version_number=1,
        content_hash="hash",
        parser_name="markdown",
        parser_config_json={},
        extracted_text="restricted body",
        metadata_json={},
    )
    sqlite_session.add(version)
    sqlite_session.flush()
    chunk = Chunk(
        document_version_id=version.id,
        chunk_index=0,
        text="restricted body",
        metadata_json={},
    )
    sqlite_session.add(chunk)
    sqlite_session.flush()

    acl = AclMetadata(
        visibility="protected",
        allowed_principals=["user:alice", "group:engineering"],
        acl_source="test",
        acl_source_hash="hash",
    )
    set_document_acl(sqlite_session, document_id=document.id, acl=acl, actor="test")
    set_chunk_acl(sqlite_session, chunk_id=chunk.id, acl=acl, actor="test")

    events = sqlite_session.scalars(select(AuditEvent).order_by(AuditEvent.occurred_at)).all()
    assert [event.event_type for event in events] == ["acl_write", "acl_write"]
    assert events[0].payload_json["allowed_count"] == 2
    assert "user:alice" not in str(events[0].payload_json)
    assert "restricted body" not in str(events[1].payload_json)
