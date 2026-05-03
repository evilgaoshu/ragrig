from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ragrig.db.models import Document, DocumentVersion


def get_or_create_document(
    session: Session,
    *,
    knowledge_base_id,
    source_id,
    uri: str,
    content_hash: str,
    mime_type: str,
    metadata_json: dict[str, object],
) -> tuple[Document, bool]:
    document = session.scalar(
        select(Document).where(Document.knowledge_base_id == knowledge_base_id, Document.uri == uri)
    )
    if document is not None:
        document.source_id = source_id
        document.content_hash = content_hash
        document.mime_type = mime_type
        document.metadata_json = metadata_json
        session.flush()
        return document, False

    document = Document(
        knowledge_base_id=knowledge_base_id,
        source_id=source_id,
        uri=uri,
        content_hash=content_hash,
        mime_type=mime_type,
        metadata_json=metadata_json,
    )
    session.add(document)
    session.flush()
    return document, True


def get_document_by_uri(session: Session, *, knowledge_base_id, uri: str) -> Document | None:
    return session.scalar(
        select(Document).where(Document.knowledge_base_id == knowledge_base_id, Document.uri == uri)
    )


def get_next_version_number(session: Session, *, document_id) -> int:
    current = session.scalar(
        select(func.max(DocumentVersion.version_number)).where(
            DocumentVersion.document_id == document_id
        )
    )
    return (current or 0) + 1


def list_latest_document_versions(session: Session, *, knowledge_base_id) -> list[DocumentVersion]:
    latest_version_numbers = (
        select(
            DocumentVersion.document_id,
            func.max(DocumentVersion.version_number).label("version_number"),
        )
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.knowledge_base_id == knowledge_base_id)
        .group_by(DocumentVersion.document_id)
        .subquery()
    )
    statement = (
        select(DocumentVersion)
        .join(Document, Document.id == DocumentVersion.document_id)
        .join(
            latest_version_numbers,
            (latest_version_numbers.c.document_id == DocumentVersion.document_id)
            & (latest_version_numbers.c.version_number == DocumentVersion.version_number),
        )
        .order_by(Document.uri)
    )
    return list(session.scalars(statement))
