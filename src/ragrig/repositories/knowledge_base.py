from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.auth import DEFAULT_WORKSPACE_ID
from ragrig.db.models import KnowledgeBase


def get_knowledge_base_by_name(
    session: Session,
    name: str,
    *,
    workspace_id: uuid.UUID = DEFAULT_WORKSPACE_ID,
) -> KnowledgeBase | None:
    return session.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.workspace_id == workspace_id,
            KnowledgeBase.name == name,
        )
    )


def get_or_create_knowledge_base(
    session: Session,
    name: str,
    *,
    workspace_id: uuid.UUID = DEFAULT_WORKSPACE_ID,
) -> KnowledgeBase:
    knowledge_base = get_knowledge_base_by_name(session, name, workspace_id=workspace_id)
    if knowledge_base is not None:
        return knowledge_base

    knowledge_base = KnowledgeBase(
        workspace_id=workspace_id,
        name=name,
        metadata_json={},
    )
    session.add(knowledge_base)
    session.flush()
    return knowledge_base
