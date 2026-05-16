"""Conversation and answer-feedback endpoints.

This router exposes:

- ``POST /conversations``                    create a new conversation
- ``GET  /conversations``                    list workspace conversations
- ``GET  /conversations/{id}``               fetch a conversation with all turns
- ``DELETE /conversations/{id}``             delete a conversation
- ``POST /conversations/{id}/answer``        ask the next question in this conversation
- ``POST /answer-feedback``                  record 👍/👎 on a turn

Multi-turn behavior
-------------------
``POST /conversations/{id}/answer`` records each turn in the conversation.
Previous turns are passed to the answer pipeline as background context so that
follow-up questions ("how about the second one?") resolve sensibly. The
underlying answer is still strictly evidence-grounded — historical turns just
help disambiguate the query.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.answer import (
    NoEvidenceError,
    ProviderUnavailableError,
    generate_answer,
)
from ragrig.db.models import (
    AnswerFeedback,
    Conversation,
    ConversationTurn,
    KnowledgeBase,
)
from ragrig.db.session import get_session
from ragrig.deps import AuthContext, get_auth_context, require_write_auth
from ragrig.retrieval import (
    EmbeddingProfileMismatchError,
    EmptyQueryError,
    InvalidTopKError,
    KnowledgeBaseNotFoundError,
    RerankerUnavailableError,
)

router = APIRouter(tags=["conversations"])


# ── Schemas ──────────────────────────────────────────────────────────────────


class CreateConversationRequest(BaseModel):
    knowledge_base: str | None = None
    title: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] | None = None


class ConversationSummary(BaseModel):
    id: uuid.UUID
    title: str | None
    knowledge_base: str | None
    turn_count: int
    created_at: str


class TurnPayload(BaseModel):
    id: uuid.UUID
    turn_index: int
    query: str
    answer: str
    grounding_status: str | None
    citations: list[dict[str, Any]]
    created_at: str


class ConversationDetail(BaseModel):
    id: uuid.UUID
    title: str | None
    knowledge_base: str | None
    turns: list[TurnPayload]


class AnswerInConversationRequest(BaseModel):
    query: str = Field(..., min_length=1)
    knowledge_base: str | None = Field(
        default=None,
        description="Override the conversation's KB. If omitted, the KB set at creation is used.",
    )
    top_k: int = Field(default=5, ge=1, le=50)
    provider: str = "deterministic-local"
    model: str | None = None
    history_window: int = Field(
        default=3,
        ge=0,
        le=20,
        description="How many previous turns to attach as context (0 disables context).",
    )


class FeedbackRequest(BaseModel):
    turn_id: uuid.UUID | None = None
    rating: int = Field(..., description="-1 = thumbs down, 0 = neutral, 1 = thumbs up")
    reason: str | None = Field(default=None, max_length=2000)
    query: str | None = None
    answer_excerpt: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] | None = None


class FeedbackResponse(BaseModel):
    id: uuid.UUID
    rating: int


# ── Helpers ──────────────────────────────────────────────────────────────────


def _resolve_kb_id(
    session: Session, workspace_id: uuid.UUID, kb_name: str | None
) -> tuple[uuid.UUID | None, str | None]:
    if not kb_name:
        return None, None
    kb = session.scalar(
        select(KnowledgeBase)
        .where(KnowledgeBase.workspace_id == workspace_id)
        .where(KnowledgeBase.name == kb_name)
        .limit(1)
    )
    if kb is None:
        return None, kb_name
    return kb.id, kb.name


def _kb_name_from_id(session: Session, kb_id: uuid.UUID | None) -> str | None:
    if kb_id is None:
        return None
    kb = session.get(KnowledgeBase, kb_id)
    return kb.name if kb else None


def _serialize_turn(turn: ConversationTurn) -> TurnPayload:
    return TurnPayload(
        id=turn.id,
        turn_index=turn.turn_index,
        query=turn.query,
        answer=turn.answer,
        grounding_status=turn.grounding_status,
        citations=turn.citations_json or [],
        created_at=turn.created_at.isoformat() if turn.created_at else "",
    )


def _build_contextual_query(history: list[ConversationTurn], query: str, window: int) -> str:
    """Concatenate the last *window* turns as a lightweight context preamble.

    The retrieval embedding receives the original query plus a short summary of
    recent exchanges, which is enough to disambiguate pronouns / follow-up
    references without polluting search recall.
    """
    if window <= 0 or not history:
        return query
    relevant = history[-window:]
    parts: list[str] = []
    for turn in relevant:
        parts.append(f"Q: {turn.query}")
        excerpt = (turn.answer or "")[:240]
        parts.append(f"A: {excerpt}")
    parts.append(f"Q: {query}")
    return "\n".join(parts)


# ── Routes ───────────────────────────────────────────────────────────────────


@router.post("/conversations", response_model=None, status_code=status.HTTP_201_CREATED)
def create_conversation(
    body: CreateConversationRequest,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
) -> dict[str, Any]:
    kb_id, resolved_kb_name = _resolve_kb_id(session, auth.workspace_id, body.knowledge_base)
    if body.knowledge_base and kb_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"knowledge base '{body.knowledge_base}' not found",
        )
    convo = Conversation(
        id=uuid.uuid4(),
        workspace_id=auth.workspace_id,
        user_id=auth.user_id,
        knowledge_base_id=kb_id,
        title=body.title,
        metadata_json=body.metadata or {},
    )
    session.add(convo)
    session.commit()
    return {
        "id": str(convo.id),
        "title": convo.title,
        "knowledge_base": resolved_kb_name,
    }


@router.get("/conversations", response_model=None)
def list_conversations(
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    limit = max(1, min(limit, 200))
    rows = session.scalars(
        select(Conversation)
        .where(Conversation.workspace_id == auth.workspace_id)
        .order_by(Conversation.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return {
        "items": [
            ConversationSummary(
                id=c.id,
                title=c.title,
                knowledge_base=_kb_name_from_id(session, c.knowledge_base_id),
                turn_count=len(c.turns),
                created_at=c.created_at.isoformat() if c.created_at else "",
            ).model_dump(mode="json")
            for c in rows
        ]
    }


@router.get("/conversations/{conversation_id}", response_model=None)
def get_conversation(
    conversation_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
) -> dict[str, Any]:
    convo = session.get(Conversation, conversation_id)
    if convo is None or convo.workspace_id != auth.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
    return ConversationDetail(
        id=convo.id,
        title=convo.title,
        knowledge_base=_kb_name_from_id(session, convo.knowledge_base_id),
        turns=[_serialize_turn(t) for t in convo.turns],
    ).model_dump(mode="json")


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
) -> None:
    convo = session.get(Conversation, conversation_id)
    if convo is None or convo.workspace_id != auth.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")
    session.delete(convo)
    session.commit()


@router.post("/conversations/{conversation_id}/answer", response_model=None)
def conversational_answer(
    conversation_id: uuid.UUID,
    body: AnswerInConversationRequest,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
) -> dict[str, Any]:
    convo = session.get(Conversation, conversation_id)
    if convo is None or convo.workspace_id != auth.workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="conversation not found")

    kb_name = body.knowledge_base or _kb_name_from_id(session, convo.knowledge_base_id)
    if not kb_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="knowledge_base is required (conversation has none configured)",
        )

    history = list(convo.turns)
    expanded_query = _build_contextual_query(history, body.query, body.history_window)

    try:
        report = generate_answer(
            session=session,
            knowledge_base_name=kb_name,
            query=expanded_query,
            top_k=body.top_k,
            provider=body.provider,
            model=body.model,
            answer_provider=body.provider,
            answer_model=body.model,
        )
    except KnowledgeBaseNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (EmptyQueryError, EmbeddingProfileMismatchError, InvalidTopKError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RerankerUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except NoEvidenceError as exc:
        next_index = max((t.turn_index for t in history), default=-1) + 1
        turn = ConversationTurn(
            id=uuid.uuid4(),
            conversation_id=convo.id,
            turn_index=next_index,
            query=body.query,
            answer=(
                "I cannot answer this question because no relevant evidence was found "
                "in the knowledge base."
            ),
            grounding_status="refused",
            citations_json=[],
            metadata_json={"refusal_reason": str(exc)},
        )
        session.add(turn)
        session.commit()
        return {
            "turn": _serialize_turn(turn).model_dump(mode="json"),
            "grounding_status": "refused",
            "answer": turn.answer,
        }
    except ProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    citations = [
        {
            "citation_id": c.citation_id,
            "document_uri": c.document_uri,
            "chunk_id": c.chunk_id,
            "chunk_index": c.chunk_index,
            "text_preview": c.text_preview,
            "score": c.score,
        }
        for c in report.citations
    ]
    next_index = max((t.turn_index for t in history), default=-1) + 1
    turn = ConversationTurn(
        id=uuid.uuid4(),
        conversation_id=convo.id,
        turn_index=next_index,
        query=body.query,
        answer=report.answer,
        grounding_status=report.grounding_status,
        citations_json=citations,
        metadata_json={"retrieval_trace": report.retrieval_trace},
    )
    session.add(turn)
    session.commit()
    return {
        "turn": _serialize_turn(turn).model_dump(mode="json"),
        "grounding_status": report.grounding_status,
        "answer": report.answer,
        "citations": citations,
    }


@router.post("/answer-feedback", response_model=FeedbackResponse)
def submit_feedback(
    body: FeedbackRequest,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(get_auth_context)],
) -> FeedbackResponse:
    if body.rating not in (-1, 0, 1):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="rating must be -1, 0, or 1",
        )
    if body.turn_id is not None:
        turn = session.get(ConversationTurn, body.turn_id)
        if turn is None:
            raise HTTPException(status_code=404, detail="turn not found")
        convo = session.get(Conversation, turn.conversation_id)
        if convo is None or convo.workspace_id != auth.workspace_id:
            raise HTTPException(status_code=404, detail="turn not found")
    feedback = AnswerFeedback(
        id=uuid.uuid4(),
        workspace_id=auth.workspace_id,
        user_id=auth.user_id,
        turn_id=body.turn_id,
        rating=body.rating,
        reason=body.reason,
        query=body.query,
        answer_excerpt=body.answer_excerpt,
        metadata_json=body.metadata or {},
    )
    session.add(feedback)
    session.commit()
    return FeedbackResponse(id=feedback.id, rating=feedback.rating)


@router.get("/answer-feedback", response_model=None)
def list_feedback(
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
    rating: int | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    limit = max(1, min(limit, 500))
    stmt = (
        select(AnswerFeedback)
        .where(AnswerFeedback.workspace_id == auth.workspace_id)
        .order_by(AnswerFeedback.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    if rating is not None:
        stmt = stmt.where(AnswerFeedback.rating == rating)
    rows = session.scalars(stmt).all()
    return {
        "items": [
            {
                "id": str(f.id),
                "rating": f.rating,
                "reason": f.reason,
                "query": f.query,
                "answer_excerpt": f.answer_excerpt,
                "turn_id": str(f.turn_id) if f.turn_id else None,
                "created_at": f.created_at.isoformat() if f.created_at else "",
            }
            for f in rows
        ]
    }
