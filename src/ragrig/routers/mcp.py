"""Model Context Protocol (MCP) server endpoint.

Exposes ``POST /mcp`` speaking JSON-RPC 2.0. This lets MCP-aware clients
(Claude Code, Cursor, etc.) connect to a RAGRig deployment and use its
knowledge bases as tools.

Implements the minimal MCP surface that is useful for retrieval:

- ``initialize``                 — handshake / capabilities
- ``tools/list``                 — list available tools
- ``tools/call``                 — invoke a tool
- ``resources/list``             — list knowledge bases as resources
- ``ping``                       — liveness

Tools
-----

``search_knowledge_base``
    Hybrid retrieval against a KB. Arguments: ``knowledge_base``, ``query``,
    optional ``top_k`` (default 5).

``answer_question``
    Grounded answer with citations. Arguments: ``knowledge_base``, ``query``,
    optional ``top_k`` (default 5), optional ``provider`` /
    ``model``.

The endpoint is HTTP-based (one request → one response). It does not implement
the full bidirectional streaming transport from the MCP spec — that is unusual
for SaaS deployments anyway. For long-lived sessions point an HTTP-MCP shim
(e.g. ``mcp-cli`` HTTP mode) at this URL.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.answer import (
    NoEvidenceError,
    ProviderUnavailableError,
    generate_answer,
)
from ragrig.db.models import KnowledgeBase
from ragrig.db.session import get_session
from ragrig.deps import AuthContext, get_auth_context
from ragrig.retrieval import (
    EmbeddingProfileMismatchError,
    EmptyQueryError,
    InvalidTopKError,
    KnowledgeBaseNotFoundError,
    RerankerUnavailableError,
    search_knowledge_base,
)

router = APIRouter(tags=["mcp"])

PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "ragrig"


_TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_knowledge_base",
        "description": (
            "Run a hybrid retrieval query against a RAGRig knowledge base and "
            "return ranked evidence chunks with document URIs and scores."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "knowledge_base": {
                    "type": "string",
                    "description": "Name of the knowledge base to search.",
                },
                "query": {"type": "string", "description": "The user query."},
                "top_k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 5,
                },
            },
            "required": ["knowledge_base", "query"],
        },
    },
    {
        "name": "answer_question",
        "description": (
            "Generate a grounded answer with citations from a RAGRig knowledge base. "
            "Returns the answer text plus a citation list referencing evidence chunks."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "knowledge_base": {"type": "string"},
                "query": {"type": "string"},
                "top_k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 50,
                    "default": 5,
                },
                "provider": {
                    "type": "string",
                    "description": (
                        "Answer provider (default 'deterministic-local'). "
                        "Use an LLM provider name for natural-language answers."
                    ),
                },
                "model": {"type": "string"},
            },
            "required": ["knowledge_base", "query"],
        },
    },
]


def _ok(rpc_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _err(rpc_id: Any, code: int, message: str, data: Any | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        body["data"] = data
    return {"jsonrpc": "2.0", "id": rpc_id, "error": body}


def _tool_search(
    session: Session, auth: AuthContext, args: dict[str, Any]
) -> dict[str, Any] | None:
    kb_name = args.get("knowledge_base")
    query = args.get("query")
    top_k = int(args.get("top_k") or 5)
    if not kb_name or not query:
        return {"isError": True, "content": [{"type": "text", "text": "missing arguments"}]}
    try:
        report = search_knowledge_base(
            session=session,
            knowledge_base_name=str(kb_name),
            query=str(query),
            top_k=top_k,
        )
    except KnowledgeBaseNotFoundError as exc:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"knowledge base not found: {exc}"}],
        }
    except (EmptyQueryError, EmbeddingProfileMismatchError, InvalidTopKError) as exc:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"invalid query: {exc}"}],
        }
    except RerankerUnavailableError as exc:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"reranker unavailable: {exc}"}],
        }

    lines = [f"Found {len(report.results)} chunk(s) in '{kb_name}':"]
    for i, r in enumerate(report.results, 1):
        snippet = r.text[:200].replace("\n", " ")
        lines.append(f"[{i}] {r.document_uri} (score={r.score:.3f})\n    {snippet}")
    text = "\n".join(lines)
    return {
        "content": [{"type": "text", "text": text}],
        "isError": False,
        "_meta": {
            "knowledge_base": kb_name,
            "total_results": report.total_results,
            "results": [
                {
                    "document_uri": r.document_uri,
                    "chunk_id": str(r.chunk_id),
                    "chunk_index": r.chunk_index,
                    "score": r.score,
                    "text_preview": r.text[:200],
                }
                for r in report.results
            ],
        },
    }


def _tool_answer(
    session: Session, auth: AuthContext, args: dict[str, Any]
) -> dict[str, Any] | None:
    kb_name = args.get("knowledge_base")
    query = args.get("query")
    top_k = int(args.get("top_k") or 5)
    provider = str(args.get("provider") or "deterministic-local")
    model = args.get("model")
    if not kb_name or not query:
        return {"isError": True, "content": [{"type": "text", "text": "missing arguments"}]}
    try:
        report = generate_answer(
            session=session,
            knowledge_base_name=str(kb_name),
            query=str(query),
            top_k=top_k,
            provider=provider,
            model=str(model) if model else None,
            answer_provider=provider,
            answer_model=str(model) if model else None,
        )
    except NoEvidenceError as exc:
        return {
            "content": [{"type": "text", "text": str(exc)}],
            "isError": False,
            "_meta": {"grounding_status": "refused"},
        }
    except KnowledgeBaseNotFoundError as exc:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"knowledge base not found: {exc}"}],
        }
    except (EmptyQueryError, EmbeddingProfileMismatchError, InvalidTopKError) as exc:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"invalid query: {exc}"}],
        }
    except RerankerUnavailableError as exc:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"reranker unavailable: {exc}"}],
        }
    except ProviderUnavailableError as exc:
        return {
            "isError": True,
            "content": [{"type": "text", "text": f"provider unavailable: {exc}"}],
        }

    citations = [
        {
            "citation_id": c.citation_id,
            "document_uri": c.document_uri,
            "score": c.score,
            "preview": c.text_preview,
        }
        for c in report.citations
    ]
    return {
        "content": [{"type": "text", "text": report.answer}],
        "isError": False,
        "_meta": {
            "grounding_status": report.grounding_status,
            "citations": citations,
        },
    }


def _list_resources(session: Session, auth: AuthContext) -> dict[str, Any]:
    kbs = session.scalars(
        select(KnowledgeBase).where(KnowledgeBase.workspace_id == auth.workspace_id)
    ).all()
    return {
        "resources": [
            {
                "uri": f"ragrig://kb/{kb.name}",
                "name": kb.name,
                "description": kb.description or f"RAGRig knowledge base '{kb.name}'",
                "mimeType": "application/x-ragrig-kb",
            }
            for kb in kbs
        ]
    }


def _dispatch(session: Session, auth: AuthContext, payload: dict[str, Any]) -> dict[str, Any]:
    rpc_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}

    if method == "initialize":
        return _ok(
            rpc_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "serverInfo": {"name": SERVER_NAME, "version": "1"},
                "capabilities": {
                    "tools": {},
                    "resources": {"subscribe": False, "listChanged": False},
                },
            },
        )
    if method == "ping":
        return _ok(rpc_id, {})
    if method == "tools/list":
        return _ok(rpc_id, {"tools": _TOOLS})
    if method == "resources/list":
        return _ok(rpc_id, _list_resources(session, auth))
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "search_knowledge_base":
            result = _tool_search(session, auth, args)
        elif name == "answer_question":
            result = _tool_answer(session, auth, args)
        else:
            return _err(rpc_id, -32601, f"unknown tool: {name}")
        return _ok(rpc_id, result)

    return _err(rpc_id, -32601, f"method not found: {method}")


@router.post("/mcp", response_model=None)
async def mcp_endpoint(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> Any:
    """JSON-RPC 2.0 entry point.

    Accepts a single request object or a batch (JSON array of requests).
    """
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content=_err(None, -32700, "parse error: invalid JSON"),
        )
    if isinstance(payload, list):
        return [_dispatch(session, auth, item) for item in payload]
    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=400,
            content=_err(None, -32700, "parse error: expected JSON object or array"),
        )
    return _dispatch(session, auth, payload)
