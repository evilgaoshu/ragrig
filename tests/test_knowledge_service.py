from __future__ import annotations

import uuid

import pytest
from conftest import _create_session

from ragrig.auth import DEFAULT_WORKSPACE_ID
from ragrig.services import knowledge as knowledge_service
from ragrig.services.common import ServiceError

pytestmark = pytest.mark.unit


def test_create_knowledge_base_returns_created_then_existing_status() -> None:
    with _create_session() as session:
        created, created_status = knowledge_service.create_knowledge_base(
            session,
            name="service-kb",
            workspace_id=DEFAULT_WORKSPACE_ID,
        )
        existing, existing_status = knowledge_service.create_knowledge_base(
            session,
            name="service-kb",
            workspace_id=DEFAULT_WORKSPACE_ID,
        )

    assert created_status == 201
    assert existing_status == 200
    assert created["id"] == existing["id"]
    assert created["created"] is True
    assert existing["created"] is False


def test_create_knowledge_base_rejects_blank_name() -> None:
    with _create_session() as session:
        with pytest.raises(ServiceError) as exc_info:
            knowledge_service.create_knowledge_base(
                session,
                name="   ",
                workspace_id=DEFAULT_WORKSPACE_ID,
            )

    assert exc_info.value.status_code == 400
    assert exc_info.value.content == {"error": "knowledge base name is required"}


def test_list_permissions_missing_knowledge_base_raises_service_error() -> None:
    with _create_session() as session:
        with pytest.raises(ServiceError) as exc_info:
            knowledge_service.list_permissions(
                session,
                kb_name="missing",
                workspace_id=DEFAULT_WORKSPACE_ID,
            )

    assert exc_info.value.status_code == 404
    assert exc_info.value.content == {"error": "knowledge base 'missing' not found"}


def test_get_document_understanding_allow_missing_preserves_200_payload() -> None:
    with _create_session() as session:
        payload = knowledge_service.get_document_understanding(
            session,
            document_version_id=str(uuid.uuid4()),
            allow_missing=True,
        )

    assert payload["error"] == "understanding_not_found"
    assert "No understanding result" in payload["message"]


def test_get_document_understanding_missing_raises_service_error() -> None:
    with _create_session() as session:
        with pytest.raises(ServiceError) as exc_info:
            knowledge_service.get_document_understanding(
                session,
                document_version_id=str(uuid.uuid4()),
                allow_missing=False,
            )

    assert exc_info.value.status_code == 404
    assert exc_info.value.content["error"] == "understanding_not_found"
