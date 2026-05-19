"""Elasticsearch sink: export knowledge-base chunks + embeddings to an ES/OpenSearch index.

The connector attempts to use the ``elasticsearch-py`` SDK when available and
falls back to raw ``httpx`` requests so that the core ragrig package has no
hard dependency on the ES SDK.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.db.models import Chunk, Document
from ragrig.plugins.sinks.elasticsearch.config import ElasticsearchSinkConfig
from ragrig.plugins.sinks.elasticsearch.errors import (
    ElasticsearchAuthError,
    ElasticsearchConfigError,
    ElasticsearchSinkError,
)
from ragrig.repositories import (
    get_knowledge_base_by_name,
    list_latest_document_versions,
)

# Optional SDK probe — used to prefer the official client when installed.
try:
    from elasticsearch import (
        Elasticsearch,  # type: ignore[import-untyped]
        helpers,  # type: ignore[import-untyped]
    )

    _es_ready = True
except ImportError:
    _es_ready = False


@dataclass(frozen=True)
class ElasticsearchExportReport:
    pipeline_run_id: str
    planned_count: int
    indexed_count: int
    failed_count: int
    dry_run: bool


# ---------------------------------------------------------------------------
# Secret resolution
# ---------------------------------------------------------------------------


def _resolve_secret(value: str, *, env: Mapping[str, str], field_name: str) -> str:
    """Return the plaintext secret for an ``env:VAR`` reference.

    Empty strings pass through unchanged (the field is optional).
    """
    if not value:
        return value
    if not value.startswith("env:"):
        raise ElasticsearchConfigError(
            f"ElasticsearchSinkConfig.{field_name} must use an 'env:VAR' secret reference; "
            f"got: {value!r}"
        )
    var_name = value.removeprefix("env:")
    resolved = env.get(var_name)
    if resolved is None:
        raise ElasticsearchConfigError(
            f"Environment variable '{var_name}' referenced by '{field_name}' is not set."
        )
    return resolved


# ---------------------------------------------------------------------------
# SDK-based bulk export
# ---------------------------------------------------------------------------


def _bulk_via_sdk(
    *,
    es_client: Any,
    index: str,
    pipeline_name: str,
    actions: list[dict[str, Any]],
    batch_size: int,
) -> tuple[int, int]:
    """Send *actions* to ES using the SDK ``helpers.bulk`` helper."""
    indexed = 0
    failed = 0
    for start in range(0, len(actions), batch_size):
        batch = actions[start : start + batch_size]
        try:
            ok, errors = helpers.bulk(es_client, batch, raise_on_error=False)
            indexed += ok
            failed += len(errors)
        except Exception as exc:
            raise ElasticsearchSinkError(f"Bulk index error: {exc}") from exc
    return indexed, failed


# ---------------------------------------------------------------------------
# httpx-based bulk export (fallback)
# ---------------------------------------------------------------------------


def _bulk_ndjson(actions: list[dict[str, Any]]) -> bytes:
    """Encode ES bulk actions as NDJSON bytes."""
    lines: list[str] = []
    for action in actions:
        meta = {"index": {"_index": action["_index"], "_id": action.get("_id")}}
        if action.get("pipeline"):
            meta["index"]["pipeline"] = action["pipeline"]
        source = action["_source"]
        lines.append(json.dumps(meta))
        lines.append(json.dumps(source))
    return ("\n".join(lines) + "\n").encode("utf-8")


def _bulk_via_httpx(
    *,
    url: str,
    headers: dict[str, str],
    ca_cert_path: str,
    index: str,
    pipeline_name: str,
    actions: list[dict[str, Any]],
    batch_size: int,
) -> tuple[int, int]:
    """Send *actions* to ES using raw httpx requests."""
    try:
        import httpx
    except ImportError as exc:
        raise ElasticsearchSinkError(
            "Neither elasticsearch-py nor httpx is available. "
            "Install at least one: pip install elasticsearch  or  pip install httpx"
        ) from exc

    indexed = 0
    failed = 0
    bulk_url = url.rstrip("/") + "/_bulk"
    if pipeline_name:
        bulk_url += f"?pipeline={pipeline_name}"

    verify: bool | str = True
    if ca_cert_path:
        verify = ca_cert_path

    for start in range(0, len(actions), batch_size):
        batch = actions[start : start + batch_size]
        body = _bulk_ndjson(batch)
        try:
            response = httpx.post(
                bulk_url,
                content=body,
                headers={**headers, "Content-Type": "application/x-ndjson"},
                verify=verify,
                timeout=60.0,
            )
        except httpx.HTTPError as exc:
            raise ElasticsearchSinkError(f"HTTP error during bulk index: {exc}") from exc

        if response.status_code in (401, 403):
            raise ElasticsearchAuthError(
                f"Elasticsearch returned HTTP {response.status_code}: authentication failed."
            )
        if not response.is_success:
            raise ElasticsearchSinkError(
                f"Elasticsearch bulk endpoint returned HTTP {response.status_code}: {response.text}"
            )

        try:
            result = response.json()
        except Exception as exc:
            raise ElasticsearchSinkError(
                f"Could not parse Elasticsearch bulk response: {exc}"
            ) from exc

        if result.get("errors"):
            for item in result.get("items", []):
                op = item.get("index", {})
                if op.get("error"):
                    failed += 1
                else:
                    indexed += 1
        else:
            indexed += len(batch)

    return indexed, failed


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def export_to_elasticsearch(
    session: Session,
    *,
    knowledge_base_name: str,
    config: ElasticsearchSinkConfig,
    env: Mapping[str, str] | None = None,
) -> ElasticsearchExportReport:
    """Export all chunks for *knowledge_base_name* to an Elasticsearch index.

    Args:
        session: Active SQLAlchemy session.
        knowledge_base_name: Name of the knowledge base to export.
        config: Validated :class:`ElasticsearchSinkConfig` instance.
        env: Environment mapping used to resolve ``env:VAR`` secret references.
            Defaults to :data:`os.environ`.

    Returns:
        An :class:`ElasticsearchExportReport` dataclass.
    """
    effective_env: Mapping[str, str] = env if env is not None else os.environ

    # Resolve secrets
    api_key = _resolve_secret(config.api_key, env=effective_env, field_name="api_key")
    password = _resolve_secret(config.password, env=effective_env, field_name="password")

    # Validate auth — cannot use both api_key and basic auth
    if api_key and config.username:
        raise ElasticsearchConfigError(
            "Specify either 'api_key' or 'username'/'password', not both."
        )

    # Locate knowledge base
    knowledge_base = get_knowledge_base_by_name(session, knowledge_base_name)
    if knowledge_base is None:
        raise ValueError(f"Knowledge base '{knowledge_base_name}' was not found")

    # Collect chunks
    versions = list_latest_document_versions(session, knowledge_base_id=knowledge_base.id)

    actions: list[dict[str, Any]] = []
    for dv in versions:
        doc: Document = dv.document
        chunks_q = (
            select(Chunk).where(Chunk.document_version_id == dv.id).order_by(Chunk.chunk_index)
        )
        chunks = list(session.scalars(chunks_q))

        for chunk in chunks:
            embedding_vector: list[float] | None = None
            if chunk.embeddings:
                raw = chunk.embeddings[0].embedding
                if raw is not None:
                    embedding_vector = list(raw) if not isinstance(raw, list) else raw

            source: dict[str, Any] = {
                "chunk_id": str(chunk.id),
                "knowledge_base": knowledge_base_name,
                "document_uri": doc.uri,
                "text": chunk.text,
                "metadata": chunk.metadata_json or {},
            }
            if embedding_vector is not None:
                source["embedding"] = embedding_vector

            action: dict[str, Any] = {
                "_index": config.index,
                "_id": str(chunk.id),
                "_source": source,
            }
            if config.pipeline_name:
                action["pipeline"] = config.pipeline_name

            actions.append(action)

    planned_count = len(actions)

    # Use a stable run-id derived from KB name (no DB pipeline_run needed)
    pipeline_run_id = f"es-export-{knowledge_base_name}"

    if config.dry_run:
        return ElasticsearchExportReport(
            pipeline_run_id=pipeline_run_id,
            planned_count=planned_count,
            indexed_count=0,
            failed_count=0,
            dry_run=True,
        )

    if not actions:
        return ElasticsearchExportReport(
            pipeline_run_id=pipeline_run_id,
            planned_count=0,
            indexed_count=0,
            failed_count=0,
            dry_run=False,
        )

    if _es_ready:
        # Build the SDK client
        es_kwargs: dict[str, Any] = {"hosts": [config.url]}
        if api_key:
            es_kwargs["api_key"] = api_key
        elif config.username:
            es_kwargs["basic_auth"] = (config.username, password)
        if config.ca_cert_path:
            es_kwargs["ca_certs"] = config.ca_cert_path

        try:
            es = Elasticsearch(**es_kwargs)
        except Exception as exc:
            raise ElasticsearchSinkError(f"Failed to create Elasticsearch client: {exc}") from exc

        indexed, failed = _bulk_via_sdk(
            es_client=es,
            index=config.index,
            pipeline_name=config.pipeline_name,
            actions=actions,
            batch_size=config.batch_size,
        )
    else:
        # httpx fallback
        http_headers: dict[str, str] = {}
        if api_key:
            http_headers["Authorization"] = f"ApiKey {api_key}"
        elif config.username:
            import base64

            creds = base64.b64encode(f"{config.username}:{password}".encode()).decode()
            http_headers["Authorization"] = f"Basic {creds}"

        indexed, failed = _bulk_via_httpx(
            url=config.url,
            headers=http_headers,
            ca_cert_path=config.ca_cert_path,
            index=config.index,
            pipeline_name=config.pipeline_name,
            actions=actions,
            batch_size=config.batch_size,
        )

    return ElasticsearchExportReport(
        pipeline_run_id=pipeline_run_id,
        planned_count=planned_count,
        indexed_count=indexed,
        failed_count=failed,
        dry_run=False,
    )


__all__ = [
    "ElasticsearchExportReport",
    "export_to_elasticsearch",
]
