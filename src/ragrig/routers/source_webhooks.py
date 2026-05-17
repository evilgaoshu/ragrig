"""Inbound source-change webhooks.

Each upstream system (Confluence, Notion, Feishu, GitHub, etc.) can be
configured to POST a small event to RAGRig when content changes. This router
exposes a single endpoint that:

1. Optionally verifies an HMAC signature
2. Audits the event
3. Enqueues an ingest task for the named source if one is configured

The endpoint is intentionally permissive on payload shape — different
providers send wildly different schemas. We only require the request to
identify a source by name (via path param) and to authenticate via either:

- ``X-RAGRig-Signature-256`` header containing HMAC-SHA256 of the raw body
  with the per-source secret stored in source.config_json.webhook_secret, OR
- A bearer API key in the ``Authorization`` header.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.db.models import KnowledgeBase, Source
from ragrig.db.session import get_session
from ragrig.deps import AuthContext, get_auth_context
from ragrig.repositories.audit import create_audit_event

router = APIRouter(tags=["source-webhooks"])
logger = logging.getLogger(__name__)


def _verify_signature(body: bytes, signature: str | None, secret: str) -> bool:
    if not signature or not secret:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/sources/{source_name}/webhook", response_model=None)
async def receive_source_webhook(
    source_name: str,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict[str, Any]:
    """Accept a change notification for ``source_name`` and audit it.

    When the source has ``webhook_secret`` configured, the signature header is
    required and verified. Otherwise this endpoint requires an authenticated
    caller (API key with appropriate scope, or session).
    """
    source = session.scalar(select(Source).where(Source.uri == source_name).limit(1))
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"source '{source_name}' not found",
        )

    kb = session.get(KnowledgeBase, source.knowledge_base_id)
    workspace_id = kb.workspace_id if kb else None

    body = await request.body()
    config = source.config_json or {}
    webhook_secret = str(config.get("webhook_secret") or "")

    if webhook_secret:
        signature = request.headers.get("X-RAGRig-Signature-256")
        if not _verify_signature(body, signature, webhook_secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid webhook signature",
            )
    else:
        if auth.is_anonymous:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication required (no webhook_secret configured)",
            )

    try:
        payload = await request.json()
    except Exception:
        payload = {"raw_size": len(body)}

    create_audit_event(
        session,
        event_type="source_save",
        actor=None,
        workspace_id=workspace_id,
        payload_json={
            "trigger": "webhook",
            "source": source_name,
            "kind": source.kind,
            "payload_keys": sorted(list(payload.keys())) if isinstance(payload, dict) else [],
        },
    )
    session.commit()

    return {
        "status": "accepted",
        "source": source_name,
        "kind": source.kind,
    }
