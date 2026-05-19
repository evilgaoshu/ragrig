"""Agent Access Sink: push knowledge-base chunks to an MCP-compatible endpoint.

Sends chunks as a JSON payload with optional HMAC-SHA256 signature.
The endpoint receives POST requests in the format:

    POST <endpoint_url>
    Authorization: Bearer <api_key>
    X-Signature-256: sha256=<hmac_hex>   (if secret configured)
    Content-Type: application/json

    {
      "knowledge_base": "<name>",
      "batch_index": 0,
      "total_batches": 3,
      "chunks": [
        {"chunk_id": "...", "document_uri": "...", "chunk_index": 0, "text": "..."}
      ]
    }
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Mapping
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.db.models import Chunk, Document
from ragrig.repositories import (
    get_knowledge_base_by_name,
    list_latest_document_versions,
)


@dataclass(frozen=True)
class AgentAccessExportReport:
    endpoint_url: str
    knowledge_base: str
    dry_run: bool
    chunk_count: int
    batch_count: int
    delivered_batches: int
    failed_batches: int


def _resolve(value: str, env: Mapping[str, str]) -> str:
    if value.startswith("env:"):
        key = value.removeprefix("env:")
        v = env.get(key)
        if v is None:
            raise ValueError(f"Missing required env var: {key}")
        return v
    return value


def _sign(payload_bytes: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


def export_to_agent_endpoint(
    session: Session,
    *,
    knowledge_base_name: str,
    endpoint_url: str,
    api_key: str,
    workspace_id: UUID | None = None,
    env: Mapping[str, str] | None = None,
    hmac_secret: str | None = None,
    batch_size: int = 100,
    timeout_seconds: float = 30.0,
    verify_tls: bool = True,
    dry_run: bool = False,
    _client: httpx.Client | None = None,
) -> AgentAccessExportReport:
    """Push all chunks from a knowledge base to an HTTP endpoint.

    Args:
        api_key: Bearer token value (or ``env:<VAR>`` reference).
        hmac_secret: Optional HMAC-SHA256 signing secret (or ``env:<VAR>``).
        batch_size: Number of chunks per POST request.
        dry_run: Collect chunks without sending any requests.
    """
    _env = dict(env or {})
    resolved_key = _resolve(api_key, _env)
    resolved_secret = _resolve(hmac_secret, _env) if hmac_secret else None

    kb = get_knowledge_base_by_name(
        session,
        knowledge_base_name,
        workspace_id=workspace_id,
    )
    if kb is None:
        raise ValueError(f"Knowledge base '{knowledge_base_name}' not found")

    versions = list_latest_document_versions(session, knowledge_base_id=kb.id)

    chunk_rows: list[dict[str, Any]] = []
    for dv in versions:
        doc: Document = dv.document
        chunks_q = (
            select(Chunk).where(Chunk.document_version_id == dv.id).order_by(Chunk.chunk_index)
        )
        for chunk in session.scalars(chunks_q):
            chunk_rows.append(
                {
                    "chunk_id": str(chunk.id),
                    "document_id": str(doc.id),
                    "document_uri": doc.uri,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "metadata": chunk.metadata_json or {},
                }
            )

    batches = [chunk_rows[i : i + batch_size] for i in range(0, len(chunk_rows), batch_size)]
    total_batches = len(batches)

    if dry_run:
        return AgentAccessExportReport(
            endpoint_url=endpoint_url,
            knowledge_base=knowledge_base_name,
            dry_run=True,
            chunk_count=len(chunk_rows),
            batch_count=total_batches,
            delivered_batches=0,
            failed_batches=0,
        )

    headers = {
        "Authorization": f"Bearer {resolved_key}",
        "Content-Type": "application/json",
    }

    delivered = 0
    failed = 0

    own_client = _client is None
    client = _client or httpx.Client(
        timeout=timeout_seconds,
        verify=verify_tls,
    )
    try:
        for idx, batch in enumerate(batches):
            payload = json.dumps(
                {
                    "knowledge_base": knowledge_base_name,
                    "batch_index": idx,
                    "total_batches": total_batches,
                    "chunks": batch,
                },
                ensure_ascii=False,
            ).encode()

            batch_headers = dict(headers)
            if resolved_secret:
                batch_headers["X-Signature-256"] = _sign(payload, resolved_secret)

            try:
                resp = client.post(endpoint_url, content=payload, headers=batch_headers)
                resp.raise_for_status()
                delivered += 1
            except httpx.HTTPError:
                failed += 1
    finally:
        if own_client:
            client.close()

    return AgentAccessExportReport(
        endpoint_url=endpoint_url,
        knowledge_base=knowledge_base_name,
        dry_run=False,
        chunk_count=len(chunk_rows),
        batch_count=total_batches,
        delivered_batches=delivered,
        failed_batches=failed,
    )
