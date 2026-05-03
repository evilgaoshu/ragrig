from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.db.models import KnowledgeBase


def get_knowledge_base_by_name(session: Session, name: str) -> KnowledgeBase | None:
    return session.scalar(select(KnowledgeBase).where(KnowledgeBase.name == name))


def get_or_create_knowledge_base(session: Session, name: str) -> KnowledgeBase:
    knowledge_base = get_knowledge_base_by_name(session, name)
    if knowledge_base is not None:
        return knowledge_base

    knowledge_base = KnowledgeBase(name=name, metadata_json={})
    session.add(knowledge_base)
    session.flush()
    return knowledge_base
