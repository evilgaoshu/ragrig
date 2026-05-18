"""Repository helpers for per-KB RBAC permission overrides."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from ragrig.db.models import KnowledgeBasePermission

_VALID_ROLES = frozenset({"admin", "editor", "viewer", "none"})


def get_kb_permission(
    session: Session,
    *,
    knowledge_base_id: uuid.UUID,
    user_id: uuid.UUID,
) -> str | None:
    """Return the per-KB role for *user_id*, or ``None`` if no override exists."""
    perm = session.get(KnowledgeBasePermission, (knowledge_base_id, user_id))
    return perm.role if perm else None


def set_kb_permission(
    session: Session,
    *,
    knowledge_base_id: uuid.UUID,
    user_id: uuid.UUID,
    role: str,
) -> None:
    """Upsert a per-KB permission.

    *role* must be one of ``'admin'``, ``'editor'``, ``'viewer'``, or
    ``'none'``.  A role of ``'none'`` explicitly denies access to the KB even
    if the user has a workspace role that would normally grant it.
    """
    if role not in _VALID_ROLES:
        raise ValueError(f"invalid KB role {role!r}; must be one of {sorted(_VALID_ROLES)}")

    perm = session.get(KnowledgeBasePermission, (knowledge_base_id, user_id))
    if perm is None:
        perm = KnowledgeBasePermission(
            knowledge_base_id=knowledge_base_id,
            user_id=user_id,
            role=role,
        )
        session.add(perm)
    else:
        perm.role = role


def delete_kb_permission(
    session: Session,
    *,
    knowledge_base_id: uuid.UUID,
    user_id: uuid.UUID,
) -> bool:
    """Remove the per-KB permission for *user_id*.

    Returns ``True`` if a row existed and was deleted, ``False`` otherwise.
    """
    perm = session.get(KnowledgeBasePermission, (knowledge_base_id, user_id))
    if perm:
        session.delete(perm)
        return True
    return False


def list_kb_permissions(
    session: Session,
    *,
    knowledge_base_id: uuid.UUID,
) -> list[dict[str, str]]:
    """Return all per-KB permission overrides for *knowledge_base_id*.

    Each entry is a dict with ``"user_id"`` and ``"role"`` string keys.
    """
    perms = (
        session.query(KnowledgeBasePermission).filter_by(knowledge_base_id=knowledge_base_id).all()
    )
    return [{"user_id": str(p.user_id), "role": p.role} for p in perms]


def resolve_effective_kb_role(
    session: Session,
    *,
    user_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
    workspace_role: str,
) -> str:
    """Return the effective role for a user on a specific knowledge base.

    Checks for a per-KB override first.  If one exists it is returned
    (including ``'none'`` which means denied).  Otherwise the caller's
    *workspace_role* is returned as the fallback.
    """
    kb_role = get_kb_permission(session, knowledge_base_id=knowledge_base_id, user_id=user_id)
    if kb_role is not None:
        return kb_role
    return workspace_role
