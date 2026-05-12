from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ragrig.acl import AclMetadata
from ragrig.db.models import Chunk, Document
from ragrig.repositories.audit import create_audit_event


def set_document_acl(
    session: Session,
    *,
    document_id,
    acl: AclMetadata,
    actor: str | None = None,
) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise ValueError(f"Document '{document_id}' was not found")
    document.metadata_json = {**(document.metadata_json or {}), "acl": acl.to_dict()}
    create_audit_event(
        session,
        event_type="acl_write",
        actor=actor,
        knowledge_base_id=document.knowledge_base_id,
        document_id=document.id,
        payload_json={
            "scope": "document",
            "visibility": acl.visibility,
            "inheritance": acl.inheritance,
            "allowed_count": len(acl.allowed_principals),
            "denied_count": len(acl.denied_principals),
            "acl_source": acl.acl_source,
            "acl_source_hash": acl.acl_source_hash,
        },
    )
    session.flush()
    return document


def set_chunk_acl(
    session: Session,
    *,
    chunk_id,
    acl: AclMetadata,
    actor: str | None = None,
) -> Chunk:
    chunk = session.get(Chunk, chunk_id)
    if chunk is None:
        raise ValueError(f"Chunk '{chunk_id}' was not found")
    chunk.metadata_json = {**(chunk.metadata_json or {}), "acl": acl.to_dict()}
    document = chunk.document_version.document
    create_audit_event(
        session,
        event_type="acl_write",
        actor=actor,
        knowledge_base_id=document.knowledge_base_id,
        document_id=document.id,
        chunk_id=chunk.id,
        payload_json={
            "scope": "chunk",
            "visibility": acl.visibility,
            "inheritance": acl.inheritance,
            "allowed_count": len(acl.allowed_principals),
            "denied_count": len(acl.denied_principals),
            "acl_source": acl.acl_source,
            "acl_source_hash": acl.acl_source_hash,
        },
    )
    session.flush()
    return chunk


def get_document_acl(document: Document) -> AclMetadata:
    return AclMetadata.from_metadata(document.metadata_json)


def get_chunk_acl(chunk: Chunk) -> AclMetadata:
    return AclMetadata.from_metadata(chunk.metadata_json)


def acl_to_safe_schema(acl: AclMetadata) -> dict[str, Any]:
    summary = acl.summary()
    summary["allowed_count"] = len(acl.allowed_principals)
    summary["denied_count"] = len(acl.denied_principals)
    return summary


__all__ = [
    "acl_to_safe_schema",
    "get_chunk_acl",
    "get_document_acl",
    "set_chunk_acl",
    "set_document_acl",
]
