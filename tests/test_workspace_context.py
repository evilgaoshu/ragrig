"""Workspace context threading tests for EVI-137.

Covers three required paths:
1. Write path: creating a knowledge base carries workspace_id.
2. Read path: querying by name is scoped to workspace_id.
3. No-auth default workspace: operations without credentials fall back to
   DEFAULT_WORKSPACE_ID and remain compatible with existing single-tenant usage.
"""

from __future__ import annotations

import uuid

import pytest

from ragrig.auth import DEFAULT_WORKSPACE_ID, ensure_default_workspace, resolve_workspace_id
from ragrig.db.models import KnowledgeBase, Workspace
from ragrig.repositories import get_knowledge_base_by_name, get_or_create_knowledge_base

pytestmark = pytest.mark.unit


@pytest.fixture
def ws_session(sqlite_session):
    """Session with default workspace pre-created."""
    ensure_default_workspace(sqlite_session)
    sqlite_session.commit()
    return sqlite_session


def _make_workspace(session, slug: str) -> Workspace:
    ws = Workspace(
        id=uuid.uuid4(),
        slug=slug,
        display_name=slug,
        status="active",
        metadata_json={},
    )
    session.add(ws)
    session.flush()
    return ws


def test_write_path_knowledge_base_carries_workspace_id(ws_session) -> None:
    ws = _make_workspace(ws_session, "team-alpha")
    kb = get_or_create_knowledge_base(ws_session, "docs", workspace_id=ws.id)
    ws_session.flush()

    assert kb.workspace_id == ws.id
    assert kb.name == "docs"


def test_read_path_scoped_to_workspace_id(ws_session) -> None:
    ws_a = _make_workspace(ws_session, "team-a")
    ws_b = _make_workspace(ws_session, "team-b")

    get_or_create_knowledge_base(ws_session, "shared-name", workspace_id=ws_a.id)
    ws_session.flush()

    # Same name in a different workspace should not be found.
    result = get_knowledge_base_by_name(ws_session, "shared-name", workspace_id=ws_b.id)
    assert result is None

    # Correct workspace returns the KB.
    result = get_knowledge_base_by_name(ws_session, "shared-name", workspace_id=ws_a.id)
    assert result is not None
    assert result.workspace_id == ws_a.id


def test_no_auth_falls_back_to_default_workspace(ws_session) -> None:
    workspace_id = resolve_workspace_id(ws_session, authorization=None)
    assert workspace_id == DEFAULT_WORKSPACE_ID


def test_no_auth_kb_create_uses_default_workspace(ws_session) -> None:
    kb = get_or_create_knowledge_base(ws_session, "default-kb")
    ws_session.flush()

    assert kb.workspace_id == DEFAULT_WORKSPACE_ID


def test_two_workspaces_can_have_same_kb_name(ws_session) -> None:
    ws_x = _make_workspace(ws_session, "org-x")
    ws_y = _make_workspace(ws_session, "org-y")

    kb_x = get_or_create_knowledge_base(ws_session, "research", workspace_id=ws_x.id)
    kb_y = get_or_create_knowledge_base(ws_session, "research", workspace_id=ws_y.id)
    ws_session.flush()

    assert kb_x.id != kb_y.id
    assert kb_x.workspace_id == ws_x.id
    assert kb_y.workspace_id == ws_y.id


def test_knowledge_base_model_has_workspace_id_column() -> None:
    from ragrig.db.models.base import Base

    table = Base.metadata.tables["knowledge_bases"]
    assert "workspace_id" in table.c
    assert not table.c["workspace_id"].nullable
