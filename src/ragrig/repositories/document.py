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
