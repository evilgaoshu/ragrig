from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from ragrig.answer import NoEvidenceError, generate_answer
from ragrig.answer import ProviderUnavailableError as AnswerProviderUnavailableError
from ragrig.answer.faithfulness import FaithfulnessConfig
from ragrig.api.schemas import AnswerRequest, PermissionPreviewRequest, RetrievalSearchRequest
from ragrig.config import Settings, get_settings
from ragrig.db.models import KnowledgeBase
from ragrig.db.session import get_session
from ragrig.deps import AuthContext, get_auth_context
from ragrig.knowledge_base_config import (
    kb_role_model_config,
    kb_stage_model_policy,
    public_role_model_selection,
    public_stage_model_selection,
    role_model_selection,
    stage_model_selection,
)
from ragrig.local_pilot import ModelConfigError
from ragrig.local_pilot.model_config import resolve_env_config
from ragrig.metrics import observe_retrieval_error, observe_retrieval_report
from ragrig.observability.langfuse import emit_langfuse_trace
from ragrig.repositories import get_knowledge_base_by_name
from ragrig.retrieval import (
    EmbeddingProfileMismatchError,
    EmptyQueryError,
    InvalidTopKError,
    KnowledgeBaseNotFoundError,
    RerankerUnavailableError,
    search_knowledge_base,
)
from ragrig.routers.runtime import (
    get_rate_limiter,
    get_workspace_id,
)
from ragrig.services.common import (
    knowledge_base_access_error,
    record_usage_for_request,
    resolve_acl_context,
    resolve_vector_backend,
    serialize_error,
)
from ragrig.services.retrieval_api import answer_sse_stream, safe_chunk_metadata
from ragrig.web_console import build_permission_preview

router = APIRouter(tags=["retrieval"])


def _explicit_stage_values(request: Any, fields: dict[str, str]) -> dict[str, Any]:
    explicit = getattr(request, "model_fields_set", set())
    return {
        target: getattr(request, source) for source, target in fields.items() if source in explicit
    }


def _role_stage_values(role_selection: dict[str, Any], stage: str) -> dict[str, Any]:
    prefix = "answer_" if stage == "answer" else ""
    values = {}
    for field in ("provider", "model", "config"):
        value = role_selection.get(prefix + field)
        if value is not None:
            values[field] = value
    return values


def _missing_selection_credentials(
    selections: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any] | None], str | None, list[str]]:
    resolved: dict[str, dict[str, Any] | None] = {}
    for selection in selections:
        stage = str(selection["stage"])
        config = selection.get("config")
        if config is None:
            resolved[stage] = None
            continue
        resolved_config, missing_env = resolve_env_config(config)
        if missing_env:
            return {}, stage, missing_env
        resolved[stage] = resolved_config
    return resolved, None, []


def _record_retrieval_error(
    settings: Settings,
    *,
    endpoint: str,
    mode: str,
    workspace_id: uuid.UUID,
) -> None:
    if settings.ragrig_metrics_enabled:
        observe_retrieval_error(
            endpoint=endpoint,
            mode=mode,
            workspace_id=workspace_id,
            include_workspace_label=settings.ragrig_metrics_workspace_labels_enabled,
        )


def _record_retrieval_report(
    settings: Settings,
    *,
    endpoint: str,
    mode: str,
    backend: str | None,
    total_results: int,
    degraded: bool = False,
    cost_latency: dict[str, Any] | None = None,
    workspace_id: uuid.UUID,
) -> None:
    if settings.ragrig_metrics_enabled:
        observe_retrieval_report(
            endpoint=endpoint,
            mode=mode,
            backend=backend,
            total_results=total_results,
            degraded=degraded,
            cost_latency=cost_latency,
            workspace_id=workspace_id,
            include_workspace_label=settings.ragrig_metrics_workspace_labels_enabled,
        )


@router.post("/retrieval/search", response_model=None)
def retrieval_search(
    request: RetrievalSearchRequest,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[Any, Depends(get_rate_limiter)],
) -> dict[str, Any] | JSONResponse:
    rate_limiter.check_search(str(workspace_id))
    if settings.ragrig_auth_enabled:
        if not request.query.strip():
            _record_retrieval_error(
                settings, endpoint="retrieval.search", mode=request.mode, workspace_id=workspace_id
            )
            return JSONResponse(
                status_code=400,
                content=serialize_error(
                    EmptyQueryError("Query must not be empty", details={"query": request.query})
                ),
            )
        kb = get_knowledge_base_by_name(
            session,
            request.knowledge_base,
            workspace_id=workspace_id,
        )
        if kb is None:
            _record_retrieval_error(
                settings, endpoint="retrieval.search", mode=request.mode, workspace_id=workspace_id
            )
            return JSONResponse(
                status_code=404,
                content=serialize_error(
                    KnowledgeBaseNotFoundError(
                        f"Knowledge base '{request.knowledge_base}' was not found",
                        details={"knowledge_base": request.knowledge_base},
                    )
                ),
            )
        access_error = knowledge_base_access_error(
            settings=settings,
            session=session,
            auth=auth,
            knowledge_base_id=kb.id,
            minimum="viewer",
            allow_anonymous_reader=True,
        )
        if access_error is not None:
            _record_retrieval_error(
                settings, endpoint="retrieval.search", mode=request.mode, workspace_id=workspace_id
            )
            return access_error
    principal_ids, enforce_acl = resolve_acl_context(
        settings=settings,
        auth=auth,
        requested_principal_ids=request.principal_ids,
        requested_enforce_acl=request.enforce_acl,
    )
    try:
        report = search_knowledge_base(
            session=session,
            knowledge_base_name=request.knowledge_base,
            query=request.query,
            top_k=request.top_k,
            provider=request.provider,
            model=request.model,
            dimensions=request.dimensions,
            vector_backend=resolve_vector_backend(settings),
            principal_ids=principal_ids,
            enforce_acl=enforce_acl,
            workspace_id=workspace_id,
            mode=request.mode,
            lexical_weight=request.lexical_weight,
            vector_weight=request.vector_weight,
            candidate_k=request.candidate_k,
            reranker_provider=request.reranker_provider,
            reranker_model=request.reranker_model,
            graph_weight=request.graph_weight,
            graph_depth=request.graph_depth,
        )
    except KnowledgeBaseNotFoundError as exc:
        _record_retrieval_error(
            settings, endpoint="retrieval.search", mode=request.mode, workspace_id=workspace_id
        )
        return JSONResponse(status_code=404, content=serialize_error(exc))
    except (EmptyQueryError, EmbeddingProfileMismatchError, InvalidTopKError) as exc:
        _record_retrieval_error(
            settings, endpoint="retrieval.search", mode=request.mode, workspace_id=workspace_id
        )
        return JSONResponse(status_code=400, content=serialize_error(exc))
    except RerankerUnavailableError as exc:
        _record_retrieval_error(
            settings, endpoint="retrieval.search", mode=request.mode, workspace_id=workspace_id
        )
        return JSONResponse(status_code=503, content=serialize_error(exc))

    response: dict[str, Any] = {
        "knowledge_base": report.knowledge_base,
        "query": report.query,
        "top_k": report.top_k,
        "provider": report.provider,
        "model": report.model,
        "dimensions": report.dimensions,
        "distance_metric": report.distance_metric,
        "backend": report.backend,
        "backend_metadata": report.backend_metadata,
        "cost_latency": report.cost_latency,
        "total_results": report.total_results,
        "acl_explain": report.acl_explain,
        "graph_context": getattr(report, "graph_context", {}),
        "rerank_trace": getattr(report, "rerank_trace", {}),
        "results": [
            {
                "document_id": str(result.document_id),
                "document_version_id": str(result.document_version_id),
                "chunk_id": str(result.chunk_id),
                "chunk_index": result.chunk_index,
                "document_uri": result.document_uri,
                "source_uri": result.source_uri,
                "text": result.text,
                "text_preview": result.text_preview,
                "distance": result.distance,
                "score": result.score,
                "chunk_metadata": safe_chunk_metadata(result.chunk_metadata),
                "rank_stage_trace": result.rank_stage_trace,
                "acl_explain": {
                    "chunk_id": result.acl_explain.chunk_id,
                    "visibility": result.acl_explain.visibility,
                    "permitted": result.acl_explain.permitted,
                    "reason": result.acl_explain.reason,
                }
                if result.acl_explain is not None
                else None,
            }
            for result in report.results
        ],
    }
    if report.results:
        reasons: dict[str, int] = {}
        for result in report.results:
            if result.acl_explain is not None:
                reasons[result.acl_explain.reason] = reasons.get(result.acl_explain.reason, 0) + 1
        response["acl_explain_summary"] = {
            "total_chunks": len(report.results),
            "reasons": reasons,
        }
    if report.degraded:
        response["degraded"] = True
        response["degraded_reason"] = report.degraded_reason
    record_usage_for_request(
        session,
        workspace_id,
        None,
        report.cost_latency,
        request_metadata={
            "endpoint": "retrieval.search",
            "role": request.role,
            "mode": request.mode,
        },
        settings=settings,
    )
    _record_retrieval_report(
        settings,
        endpoint="retrieval.search",
        mode=request.mode,
        backend=report.backend,
        total_results=report.total_results,
        degraded=report.degraded,
        cost_latency=report.cost_latency,
        workspace_id=workspace_id,
    )
    emit_langfuse_trace(
        settings,
        name="retrieval.search",
        metadata={
            "knowledge_base": request.knowledge_base,
            "top_k": request.top_k,
            "mode": request.mode,
            "provider": report.provider,
            "model": report.model,
            "backend": report.backend,
            "degraded": report.degraded,
        },
        output_metadata={
            "total_results": report.total_results,
        },
    )
    return response


@router.post("/permissions/preview", response_model=None)
def permission_preview(
    request: PermissionPreviewRequest,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
) -> dict[str, Any]:
    return build_permission_preview(
        session,
        principal_ids=request.principal_ids,
        workspace_id=workspace_id,
    )


@router.post("/retrieval/answer", response_model=None)
def retrieval_answer(
    request: AnswerRequest,
    session: Annotated[Session, Depends(get_session)],
    workspace_id: Annotated[uuid.UUID, Depends(get_workspace_id)],
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)],
    rate_limiter: Annotated[Any, Depends(get_rate_limiter)],
) -> dict[str, Any] | JSONResponse:
    rate_limiter.check_search(str(workspace_id))
    answer_kb: KnowledgeBase | None = None
    if settings.ragrig_auth_enabled:
        if not request.query.strip():
            _record_retrieval_error(
                settings, endpoint="retrieval.answer", mode=request.mode, workspace_id=workspace_id
            )
            return JSONResponse(
                status_code=400,
                content=serialize_error(
                    EmptyQueryError("Query must not be empty", details={"query": request.query})
                ),
            )
        kb = get_knowledge_base_by_name(
            session,
            request.knowledge_base,
            workspace_id=workspace_id,
        )
        if kb is None:
            _record_retrieval_error(
                settings, endpoint="retrieval.answer", mode=request.mode, workspace_id=workspace_id
            )
            return JSONResponse(
                status_code=404,
                content=serialize_error(
                    KnowledgeBaseNotFoundError(
                        f"Knowledge base '{request.knowledge_base}' was not found",
                        details={"knowledge_base": request.knowledge_base},
                    )
                ),
            )
        access_error = knowledge_base_access_error(
            settings=settings,
            session=session,
            auth=auth,
            knowledge_base_id=kb.id,
            minimum="viewer",
            allow_anonymous_reader=True,
        )
        if access_error is not None:
            _record_retrieval_error(
                settings, endpoint="retrieval.answer", mode=request.mode, workspace_id=workspace_id
            )
            return access_error
        answer_kb = kb
    principal_ids, enforce_acl = resolve_acl_context(
        settings=settings,
        auth=auth,
        requested_principal_ids=request.principal_ids,
        requested_enforce_acl=request.enforce_acl,
    )
    if answer_kb is None:
        answer_kb = get_knowledge_base_by_name(
            session,
            request.knowledge_base,
            workspace_id=workspace_id,
        )
    persisted_role_config = kb_role_model_config(answer_kb)
    persisted_stage_policy = kb_stage_model_policy(answer_kb)
    effective_role_config = (
        request.role_model_config
        if request.role_model_config is not None
        else persisted_role_config
    )
    role_selection, role_error = role_model_selection(request.role, effective_role_config)
    if role_error is not None:
        _record_retrieval_error(
            settings, endpoint="retrieval.answer", mode=request.mode, workspace_id=workspace_id
        )
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "invalid_role_model_config",
                    "message": role_error,
                    "details": {"role": request.role},
                }
            },
        )
    if role_selection and "source" not in role_selection:
        role_selection["source"] = (
            "request" if request.role_model_config is not None else "knowledge_base"
        )
    query_selection = stage_model_selection(
        "query",
        persisted_stage_policy,
        request_values=_explicit_stage_values(
            request,
            {"provider": "provider", "model": "model", "config": "config"},
        ),
        role_values=_role_stage_values(role_selection, "query"),
        defaults={"provider": request.provider, "model": request.model, "config": request.config},
    )
    answer_selection = stage_model_selection(
        "answer",
        persisted_stage_policy,
        request_values=_explicit_stage_values(
            request,
            {
                "answer_provider": "provider",
                "answer_model": "model",
                "answer_config": "config",
            },
        ),
        role_values=_role_stage_values(role_selection, "answer"),
        defaults={
            "provider": query_selection.get("provider"),
            "model": query_selection.get("model"),
        },
    )
    rerank_selection = stage_model_selection(
        "rerank",
        persisted_stage_policy,
        request_values=_explicit_stage_values(
            request,
            {
                "reranker_provider": "provider",
                "reranker_model": "model",
                "reranker_config": "config",
            },
        ),
        defaults={
            "provider": request.reranker_provider,
            "model": request.reranker_model,
            "config": request.reranker_config,
        },
    )
    judge_selection = stage_model_selection(
        "judge",
        persisted_stage_policy,
        request_values=_explicit_stage_values(
            request,
            {
                "judge_provider": "provider",
                "judge_model": "model",
                "judge_config": "config",
                "judge_enabled": "enabled",
            },
        ),
        defaults={"enabled": False},
    )
    stage_selections = [
        public_stage_model_selection(selection)
        for selection in (query_selection, rerank_selection, answer_selection, judge_selection)
    ]
    try:
        resolved_configs, missing_stage, missing_env = _missing_selection_credentials(
            [query_selection, rerank_selection, answer_selection, judge_selection]
        )
        if missing_env:
            _record_retrieval_error(
                settings,
                endpoint="retrieval.answer",
                mode=request.mode,
                workspace_id=workspace_id,
            )
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "code": "missing_model_credentials",
                        "message": "Missing environment variable(s): " + ", ".join(missing_env),
                        "details": {
                            "stage": missing_stage,
                            "missing_credentials": missing_env,
                        },
                    }
                },
            )
        faithfulness_config = None
        if judge_selection.get("enabled") is not False and judge_selection.get("provider"):
            faithfulness_config = FaithfulnessConfig(
                provider_name=str(judge_selection["provider"]),
                model_name=judge_selection.get("model"),
                provider_config=resolved_configs.get("judge"),
                max_context_chars=int(judge_selection.get("max_tokens") or 1500) * 4,
            )
        report = generate_answer(
            session=session,
            knowledge_base_name=request.knowledge_base,
            query=request.query,
            top_k=request.top_k,
            provider=str(query_selection.get("provider") or "deterministic-local"),
            model=query_selection.get("model"),
            provider_config=resolved_configs.get("query"),
            answer_provider=answer_selection.get("provider"),
            answer_model=answer_selection.get("model"),
            answer_provider_config=resolved_configs.get("answer"),
            dimensions=request.dimensions,
            vector_backend=resolve_vector_backend(settings),
            principal_ids=principal_ids,
            enforce_acl=enforce_acl,
            mode=request.mode,
            lexical_weight=request.lexical_weight,
            vector_weight=request.vector_weight,
            candidate_k=request.candidate_k,
            reranker_provider=(
                rerank_selection.get("provider")
                if rerank_selection.get("enabled") is not False
                else None
            ),
            reranker_model=(
                rerank_selection.get("model")
                if rerank_selection.get("enabled") is not False
                else None
            ),
            reranker_config=resolved_configs.get("rerank"),
            faithfulness_config=faithfulness_config,
            graph_weight=request.graph_weight,
            graph_depth=request.graph_depth,
            workspace_id=workspace_id,
        )
    except ModelConfigError as exc:
        _record_retrieval_error(
            settings, endpoint="retrieval.answer", mode=request.mode, workspace_id=workspace_id
        )
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                    "details": {"field": exc.field},
                }
            },
        )
    except NoEvidenceError as exc:
        _record_retrieval_report(
            settings,
            endpoint="retrieval.answer",
            mode=request.mode,
            backend=None,
            total_results=0,
            workspace_id=workspace_id,
        )
        return JSONResponse(
            status_code=200,
            content={
                "answer": "",
                "citations": [],
                "evidence_chunks": [],
                "model": exc.details.get("model", ""),
                "provider": exc.details.get("provider", ""),
                "retrieval_trace": exc.details,
                "stage_model_selection": stage_selections,
                "grounding_status": "refused",
                "refusal_reason": str(exc),
            },
        )
    except KnowledgeBaseNotFoundError as exc:
        _record_retrieval_error(
            settings, endpoint="retrieval.answer", mode=request.mode, workspace_id=workspace_id
        )
        return JSONResponse(status_code=404, content=serialize_error(exc))
    except (EmptyQueryError, EmbeddingProfileMismatchError, InvalidTopKError) as exc:
        _record_retrieval_error(
            settings, endpoint="retrieval.answer", mode=request.mode, workspace_id=workspace_id
        )
        return JSONResponse(status_code=400, content=serialize_error(exc))
    except RerankerUnavailableError as exc:
        _record_retrieval_error(
            settings, endpoint="retrieval.answer", mode=request.mode, workspace_id=workspace_id
        )
        return JSONResponse(status_code=503, content=serialize_error(exc))
    except AnswerProviderUnavailableError as exc:
        _record_retrieval_error(
            settings, endpoint="retrieval.answer", mode=request.mode, workspace_id=workspace_id
        )
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": exc.code,
                    "message": str(exc),
                    "details": exc.details,
                }
            },
        )

    public_role_selection = public_role_model_selection(role_selection)
    record_usage_for_request(
        session,
        workspace_id,
        None,
        report.cost_latency,
        request_metadata={
            "endpoint": "retrieval.answer",
            "role": request.role,
            "mode": request.mode,
            "role_model_selection": public_role_selection,
            "stage_model_selection": stage_selections,
        },
        settings=settings,
    )
    retrieval_trace = {**report.retrieval_trace, "stage_model_selection": stage_selections}
    _record_retrieval_report(
        settings,
        endpoint="retrieval.answer",
        mode=request.mode,
        backend=str(retrieval_trace.get("backend") or "unknown"),
        total_results=int(retrieval_trace.get("total_results") or 0),
        degraded=report.grounding_status == "degraded",
        cost_latency=report.cost_latency,
        workspace_id=workspace_id,
    )
    payload = {
        "answer": report.answer,
        "citations": [
            {
                "citation_id": citation.citation_id,
                "document_uri": citation.document_uri,
                "chunk_id": citation.chunk_id,
                "chunk_index": citation.chunk_index,
                "text_preview": citation.text_preview,
                "score": citation.score,
                "char_start": citation.char_start,
                "char_end": citation.char_end,
                "page_number": citation.page_number,
                "metadata_summary": citation.metadata_summary,
            }
            for citation in report.citations
        ],
        "evidence_chunks": [
            {
                "citation_id": chunk.citation_id,
                "document_uri": chunk.document_uri,
                "chunk_id": chunk.chunk_id,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "score": chunk.score,
                "distance": chunk.distance,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
                "page_number": chunk.page_number,
            }
            for chunk in report.evidence_chunks
        ],
        "model": report.model,
        "provider": report.provider,
        "role": request.role,
        "role_model_selection": public_role_selection,
        "stage_model_selection": stage_selections,
        "retrieval_trace": retrieval_trace,
        "grounding_status": report.grounding_status,
        "refusal_reason": report.refusal_reason,
    }
    emit_langfuse_trace(
        settings,
        name="retrieval.answer",
        metadata={
            "knowledge_base": request.knowledge_base,
            "top_k": request.top_k,
            "mode": request.mode,
            "provider": report.provider,
            "model": report.model,
            "grounding_status": report.grounding_status,
            "citations_count": len(report.citations),
        },
        output_metadata={
            "evidence_chunks_count": len(report.evidence_chunks),
            "total_results": int(retrieval_trace.get("total_results") or 0),
        },
    )
    if request.stream:
        return StreamingResponse(
            answer_sse_stream(payload),
            media_type="text/event-stream",
        )
    return payload
