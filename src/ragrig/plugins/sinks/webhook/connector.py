"""Webhook Sink: push knowledge-base chunks to an arbitrary HTTP endpoint.

Sends chunks as NDJSON (one JSON object per line) or a single JSON array.
Optionally signs each request with HMAC-SHA256 for payload verification.

    POST <endpoint_url>
    Content-Type: application/x-ndjson   (or application/json)
    X-Signature-256: sha256=<hmac_hex>   (if secret configured)
    <custom headers>

    {"chunk_id":"...","document_uri":"...","chunk_index":0,"text":"..."}
    {"chunk_id":"...","document_uri":"...","chunk_index":1,"text":"..."}
    ...
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
class WebhookExportReport:
    endpoint_url: str
    knowledge_base: str
    format: str
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


def _sign_payload(payload_bytes: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()


def export_to_webhook(
    session: Session,
    *,
    knowledge_base_name: str,
    endpoint_url: str,
    env: Mapping[str, str] | None = None,
    hmac_secret: str | None = None,
    workspace_id: UUID | None = None,
    format: str = "ndjson",
    extra_headers: dict[str, str] | None = None,
    batch_size: int = 200,
    timeout_seconds: float = 30.0,
    verify_tls: bool = True,
    dry_run: bool = False,
    _client: httpx.Client | None = None,
) -> WebhookExportReport:
    """Push all chunks from a knowledge base to a webhook URL.

    Args:
        hmac_secret: Optional HMAC-SHA256 signing secret (or ``env:<VAR>``).
        format: ``"ndjson"`` (one JSON object per line) or ``"json"`` (array).
        extra_headers: Additional HTTP headers to include in each request.
        batch_size: Chunks per POST request.
        dry_run: Collect chunks without sending requests.
    """
    if format not in ("ndjson", "json"):
        raise ValueError(f"format must be 'ndjson' or 'json'; got {format!r}")

    _env = dict(env or {})
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
        return WebhookExportReport(
            endpoint_url=endpoint_url,
            knowledge_base=knowledge_base_name,
            format=format,
            dry_run=True,
            chunk_count=len(chunk_rows),
            batch_count=total_batches,
            delivered_batches=0,
            failed_batches=0,
        )

    content_type = "application/x-ndjson" if format == "ndjson" else "application/json"
    base_headers = {"Content-Type": content_type}
    if extra_headers:
        for k, v in extra_headers.items():
            base_headers[k] = _resolve(v, _env) if isinstance(v, str) else v

    delivered = 0
    failed = 0

    own_client = _client is None
    client = _client or httpx.Client(timeout=timeout_seconds, verify=verify_tls)
    try:
        for batch in batches:
            if format == "ndjson":
                payload_bytes = (
                    "\n".join(json.dumps(row, ensure_ascii=False) for row in batch) + "\n"
                ).encode()
            else:
                payload_bytes = json.dumps(batch, ensure_ascii=False).encode()

            req_headers = dict(base_headers)
            if resolved_secret:
                req_headers["X-Signature-256"] = _sign_payload(payload_bytes, resolved_secret)

            try:
                resp = client.post(endpoint_url, content=payload_bytes, headers=req_headers)
                resp.raise_for_status()
                delivered += 1
            except httpx.HTTPError:
                failed += 1
    finally:
        if own_client:
            client.close()

    return WebhookExportReport(
        endpoint_url=endpoint_url,
        knowledge_base=knowledge_base_name,
        format=format,
        dry_run=False,
        chunk_count=len(chunk_rows),
        batch_count=total_batches,
        delivered_batches=delivered,
        failed_batches=failed,
    )
