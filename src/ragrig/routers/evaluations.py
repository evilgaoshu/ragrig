from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ragrig.api.schemas import EvaluationRunRequest
from ragrig.config import Settings, get_settings
from ragrig.db.session import get_session
from ragrig.deps import AuthContext, require_admin_auth
from ragrig.evaluation import (
    build_evaluation_list_report,
    build_evaluation_run_report,
    list_runs_from_store,
    load_run_from_store,
    run_evaluation,
)
from ragrig.evaluation.baseline import list_baselines
from ragrig.services.common import resolve_evaluation_path

router = APIRouter(tags=["evaluations"])


@router.post("/evaluations/runs", response_model=None)
def evaluation_run(
    request: EvaluationRunRequest,
    session: Annotated[Session, Depends(get_session)],
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, Any] | JSONResponse:
    golden_path, path_error = resolve_evaluation_path(
        request.golden_path,
        default_path=Path("evaluation_runs"),
        allowed_roots=(Path("evaluation_runs"), Path("evaluation_baselines"), Path("tests")),
        settings=settings,
    )
    if path_error is not None:
        return path_error
    assert golden_path is not None
    if not golden_path.exists():
        return JSONResponse(
            status_code=404,
            content={"error": f"Golden question file not found: {golden_path}"},
        )

    baseline_path: Path | None = None
    if request.baseline_path:
        baseline_path, path_error = resolve_evaluation_path(
            request.baseline_path,
            default_path=Path("evaluation_baselines"),
            allowed_roots=(Path("evaluation_baselines"), Path("evaluation_runs")),
            settings=settings,
        )
        if path_error is not None:
            return path_error
    try:
        run = run_evaluation(
            session=session,
            golden_path=golden_path,
            knowledge_base=request.knowledge_base,
            top_k=request.top_k,
            provider=request.provider,
            model=request.model,
            dimensions=request.dimensions,
            baseline_path=baseline_path,
            mode=request.mode,
            lexical_weight=request.lexical_weight,
            vector_weight=request.vector_weight,
            candidate_k=request.candidate_k,
            reranker_provider=request.reranker_provider,
            reranker_model=request.reranker_model,
            graph_weight=request.graph_weight,
            graph_depth=request.graph_depth,
            ragas_enabled=request.ragas_enabled,
            ragas_metrics=request.ragas_metrics,
            langfuse_settings=settings,
            store_dir=Path("evaluation_runs"),
        )
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": f"Evaluation failed: {exc}"},
        )
    return build_evaluation_run_report(run, include_items=True)


@router.get("/evaluations/runs/{run_id}", response_model=None)
def evaluation_run_detail(
    run_id: str,
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
    settings: Annotated[Settings, Depends(get_settings)],
    store_dir: str | None = None,
) -> dict[str, Any] | JSONResponse:
    store_path, path_error = resolve_evaluation_path(
        store_dir,
        default_path=Path("evaluation_runs"),
        allowed_roots=(Path("evaluation_runs"),),
        settings=settings,
    )
    if path_error is not None:
        return path_error
    assert store_path is not None
    run = load_run_from_store(run_id, store_dir=store_path)
    if run is None:
        return JSONResponse(
            status_code=404,
            content={"error": "evaluation_run_not_found"},
        )
    return build_evaluation_run_report(run, include_items=True)


@router.get("/evaluations", response_model=None)
def evaluation_runs_list(
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
    settings: Annotated[Settings, Depends(get_settings)],
    store_dir: str | None = None,
) -> dict[str, Any] | JSONResponse:
    store_path, path_error = resolve_evaluation_path(
        store_dir,
        default_path=Path("evaluation_runs"),
        allowed_roots=(Path("evaluation_runs"),),
        settings=settings,
    )
    if path_error is not None:
        return path_error
    assert store_path is not None
    runs = list_runs_from_store(store_dir=store_path)
    return build_evaluation_list_report(runs)


@router.get("/evaluations/baselines", response_model=None)
def evaluation_baselines_list(
    _auth: Annotated[AuthContext, Depends(require_admin_auth)],
    settings: Annotated[Settings, Depends(get_settings)],
    baseline_dir: str | None = None,
) -> dict[str, Any] | JSONResponse:
    path, path_error = resolve_evaluation_path(
        baseline_dir,
        default_path=Path("evaluation_baselines"),
        allowed_roots=(Path("evaluation_baselines"),),
        settings=settings,
    )
    if path_error is not None:
        return path_error
    assert path is not None
    try:
        return list_baselines(baseline_dir=path)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": f"Failed to list baselines: {exc}"},
        )
