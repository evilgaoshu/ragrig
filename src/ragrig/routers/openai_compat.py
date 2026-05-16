"""OpenAI-compatible chat completions endpoint.

Exposes ``POST /v1/chat/completions`` mapping the OpenAI ChatCompletion request
shape onto RAGRig's grounded answer pipeline.

Model selector
--------------
The ``model`` field selects the knowledge base (and optionally the answer
provider/model). Accepted forms:

    <kb_name>                              # uses default deterministic provider
    ragrig/<kb_name>                       # explicit ragrig/ prefix
    ragrig/<kb_name>@<provider>            # use an LLM provider
    ragrig/<kb_name>@<provider>:<model>    # provider + specific model

The last ``user`` message becomes the query. ``system`` messages are recorded
in the trace but do not bypass evidence grounding — the provider always sees
the canonical grounding prompt.

Streaming
---------
When ``stream`` is true the endpoint emits OpenAI-style ``text/event-stream``
chunks. RAGRig answer providers are not natively streaming, so the final answer
text is chunked into small SSE deltas to provide the perception of streaming.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid as uuid_module
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ragrig.answer import (
    NoEvidenceError,
    ProviderUnavailableError,
    generate_answer,
)
from ragrig.db.session import get_session
from ragrig.deps import AuthContext, get_auth_context
from ragrig.retrieval import (
    EmbeddingProfileMismatchError,
    EmptyQueryError,
    InvalidTopKError,
    KnowledgeBaseNotFoundError,
    RerankerUnavailableError,
)

router = APIRouter(tags=["openai-compat"])


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    name: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str = Field(..., description="ragrig/<kb_name>[@<provider>[:<model>]]")
    messages: list[ChatMessage] = Field(..., min_length=1)
    stream: bool = False
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    user: str | None = None
    # RAGRig extensions
    top_k: int | None = Field(default=None, ge=1, le=50)
    enforce_acl: bool = True


def _parse_model(model: str) -> tuple[str, str, str | None]:
    """Return (kb_name, provider, model_name).

    Accepts ``<kb>``, ``ragrig/<kb>``, ``ragrig/<kb>@<provider>``,
    ``ragrig/<kb>@<provider>:<model>``.
    """
    spec = model.removeprefix("ragrig/")
    if "@" in spec:
        kb, rest = spec.split("@", 1)
        if ":" in rest:
            provider, mdl = rest.split(":", 1)
            return kb, provider or "deterministic-local", mdl or None
        return kb, rest or "deterministic-local", None
    return spec, "deterministic-local", None


def _last_user_query(messages: list[ChatMessage]) -> str:
    for msg in reversed(messages):
        if msg.role == "user" and msg.content:
            return msg.content
    raise ValueError("no user message with content found")


def _completion_id() -> str:
    return f"chatcmpl-{uuid_module.uuid4().hex[:24]}"


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _format_completion(
    *,
    completion_id: str,
    created: int,
    model: str,
    answer_text: str,
    citations: list[dict[str, Any]],
    grounding_status: str,
    prompt_tokens: int,
) -> dict[str, Any]:
    completion_tokens = _estimate_tokens(answer_text)
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer_text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "ragrig": {
            "grounding_status": grounding_status,
            "citations": citations,
        },
    }


def _chunk_text(text: str, *, size: int = 12) -> list[str]:
    if not text:
        return []
    return [text[i : i + size] for i in range(0, len(text), size)]


async def _sse_stream(
    *,
    completion_id: str,
    created: int,
    model: str,
    answer_text: str,
    citations: list[dict[str, Any]],
    grounding_status: str,
):
    base = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
    }
    first = {
        **base,
        "choices": [
            {
                "index": 0,
                "delta": {"role": "assistant"},
                "finish_reason": None,
            }
        ],
    }
    yield f"data: {json.dumps(first)}\n\n"

    for piece in _chunk_text(answer_text):
        chunk = {
            **base,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": piece},
                    "finish_reason": None,
                }
            ],
        }
        yield f"data: {json.dumps(chunk)}\n\n"
        await asyncio.sleep(0)

    final = {
        **base,
        "choices": [
            {
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }
        ],
        "ragrig": {
            "grounding_status": grounding_status,
            "citations": citations,
        },
    }
    yield f"data: {json.dumps(final)}\n\n"
    yield "data: [DONE]\n\n"


def _citation_dicts(citations: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in citations:
        out.append(
            {
                "citation_id": c.citation_id,
                "document_uri": c.document_uri,
                "chunk_id": c.chunk_id,
                "chunk_index": c.chunk_index,
                "text_preview": c.text_preview,
                "score": c.score,
            }
        )
    return out


@router.post("/v1/chat/completions", response_model=None)
def chat_completions(
    request: ChatCompletionRequest,
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> Any:
    try:
        query = _last_user_query(request.messages)
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "message": "messages must include at least one user message with content",
                    "type": "invalid_request_error",
                    "code": "missing_user_message",
                }
            },
        )

    kb_name, provider, model_name = _parse_model(request.model)
    top_k = request.top_k or 5

    try:
        report = generate_answer(
            session=session,
            knowledge_base_name=kb_name,
            query=query,
            top_k=top_k,
            provider=provider,
            model=model_name,
            answer_provider=provider,
            answer_model=model_name,
            enforce_acl=request.enforce_acl,
        )
    except NoEvidenceError as exc:
        empty = (
            "I cannot answer this question because no relevant evidence was found "
            "in the knowledge base."
        )
        completion_id = _completion_id()
        created = int(time.time())
        if request.stream:
            return StreamingResponse(
                _sse_stream(
                    completion_id=completion_id,
                    created=created,
                    model=request.model,
                    answer_text=empty,
                    citations=[],
                    grounding_status="refused",
                ),
                media_type="text/event-stream",
            )
        return _format_completion(
            completion_id=completion_id,
            created=created,
            model=request.model,
            answer_text=empty,
            citations=[],
            grounding_status="refused",
            prompt_tokens=_estimate_tokens(query),
        ) | {"ragrig": {"refusal_reason": str(exc), "grounding_status": "refused"}}
    except KnowledgeBaseNotFoundError:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "message": f"knowledge base '{kb_name}' not found",
                    "type": "not_found",
                    "code": "knowledge_base_not_found",
                }
            },
        )
    except (EmptyQueryError, EmbeddingProfileMismatchError, InvalidTopKError) as exc:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "message": str(exc),
                    "type": "invalid_request_error",
                    "code": exc.code,
                }
            },
        )
    except RerankerUnavailableError as exc:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "message": str(exc),
                    "type": "service_unavailable",
                    "code": exc.code,
                }
            },
        )
    except ProviderUnavailableError as exc:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "message": str(exc),
                    "type": "service_unavailable",
                    "code": exc.code,
                }
            },
        )

    completion_id = _completion_id()
    created = int(time.time())
    citations = _citation_dicts(report.citations)
    prompt_tokens = _estimate_tokens(query) + sum(
        _estimate_tokens(c.get("text_preview", "")) for c in citations
    )

    if request.stream:
        return StreamingResponse(
            _sse_stream(
                completion_id=completion_id,
                created=created,
                model=request.model,
                answer_text=report.answer,
                citations=citations,
                grounding_status=report.grounding_status,
            ),
            media_type="text/event-stream",
        )

    return _format_completion(
        completion_id=completion_id,
        created=created,
        model=request.model,
        answer_text=report.answer,
        citations=citations,
        grounding_status=report.grounding_status,
        prompt_tokens=prompt_tokens,
    )


@router.get("/v1/models", response_model=None)
def list_models(
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> dict[str, Any]:
    """List knowledge bases as OpenAI-style models."""
    from sqlalchemy import select

    from ragrig.db.models import KnowledgeBase

    kbs = session.scalars(
        select(KnowledgeBase).where(KnowledgeBase.workspace_id == _auth.workspace_id)
    ).all()
    return {
        "object": "list",
        "data": [
            {
                "id": f"ragrig/{kb.name}",
                "object": "model",
                "created": int(kb.created_at.timestamp()) if kb.created_at else 0,
                "owned_by": "ragrig",
            }
            for kb in kbs
        ],
    }
