"""Data retention — automatic purge of old documents and audit events.

purge_old_document_versions:
    Deletes document versions (and their cascaded chunks/embeddings) older
    than `days` days for a given knowledge base.  Only non-current versions
    are candidates (the highest version_number per document is preserved).

purge_old_audit_events:
    Deletes audit_events older than `days` days (workspace-scoped or global).

run_retention_for_knowledge_base:
    High-level driver: reads `retention_days` from the KB record, runs purge
    if a policy is set, returns a summary dict.

run_all_retention:
    Iterates every KB with a retention policy and every workspace; also
    applies the global audit-event retention from settings.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ragrig.config import Settings
from ragrig.db.models import (
    AuditEvent,
    DocumentVersion,
    KnowledgeBase,
)

logger = logging.getLogger(__name__)


def purge_old_document_versions(
    session: Session,
    *,
    knowledge_base_id: "Any",
    days: int,
) -> int:
    """Delete non-current document versions older than `days` days.

    Returns the count of deleted rows.
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Find all versions older than cutoff that are NOT the current (max) version.
    from sqlalchemy import func

    from ragrig.db.models import Document

    max_version_sq = (
        select(
            DocumentVersion.document_id,
            func.max(DocumentVersion.version_number).label("max_ver"),
        )
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.knowledge_base_id == knowledge_base_id)
        .group_by(DocumentVersion.document_id)
        .subquery()
    )

    old_versions = session.scalars(
        select(DocumentVersion.id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .join(
            max_version_sq,
            (max_version_sq.c.document_id == DocumentVersion.document_id)
            & (max_version_sq.c.max_ver != DocumentVersion.version_number),
        )
        .where(Document.knowledge_base_id == knowledge_base_id)
        .where(DocumentVersion.created_at < cutoff)
    ).all()

    if not old_versions:
        return 0

    result = session.execute(delete(DocumentVersion).where(DocumentVersion.id.in_(old_versions)))
    deleted = result.rowcount
    logger.info(
        "retention: purged %d document versions older than %d days from KB %s",
        deleted,
        days,
        knowledge_base_id,
    )
    return deleted


def purge_old_audit_events(
    session: Session,
    *,
    days: int,
    workspace_id: "Any | None" = None,
) -> int:
    """Delete audit events older than `days` days.

    If `workspace_id` is given, restricts to that workspace only.
    Returns deleted row count.
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)
    stmt = delete(AuditEvent).where(AuditEvent.occurred_at < cutoff)
    if workspace_id is not None:
        stmt = stmt.where(AuditEvent.workspace_id == workspace_id)
    result = session.execute(stmt)
    deleted = result.rowcount
    if deleted:
        logger.info(
            "retention: purged %d audit events older than %d days (workspace=%s)",
            deleted,
            days,
            workspace_id,
        )
    return deleted


def run_retention_for_knowledge_base(
    session: Session,
    *,
    knowledge_base_id: "Any",
    knowledge_base_name: str,
) -> dict[str, Any]:
    """Run document-version retention for one KB if it has a policy set."""
    kb = session.get(KnowledgeBase, knowledge_base_id)
    if kb is None or kb.retention_days is None:
        return {"knowledge_base": knowledge_base_name, "skipped": True, "deleted_versions": 0}

    deleted = purge_old_document_versions(
        session,
        knowledge_base_id=knowledge_base_id,
        days=kb.retention_days,
    )
    session.commit()
    return {
        "knowledge_base": knowledge_base_name,
        "skipped": False,
        "retention_days": kb.retention_days,
        "deleted_versions": deleted,
    }


def run_all_retention(session: Session, settings: Settings) -> dict[str, Any]:
    """Run retention across all KBs and apply global audit-event TTL."""
    kb_results = []
    kbs = session.scalars(
        select(KnowledgeBase).where(KnowledgeBase.retention_days.isnot(None))
    ).all()
    for kb in kbs:
        result = run_retention_for_knowledge_base(
            session,
            knowledge_base_id=kb.id,
            knowledge_base_name=kb.name,
        )
        kb_results.append(result)

    audit_deleted = 0
    if settings.ragrig_audit_retention_days > 0:
        audit_deleted = purge_old_audit_events(session, days=settings.ragrig_audit_retention_days)
        session.commit()

    return {
        "knowledge_bases": kb_results,
        "audit_events_deleted": audit_deleted,
    }
