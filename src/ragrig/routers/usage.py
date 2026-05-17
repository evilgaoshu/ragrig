"""Usage + budget endpoints.

Exposes:

- ``GET  /usage``                   workspace cost/token rollup with optional grouping
- ``GET  /usage/timeseries``        daily cost + token series
- ``GET  /budgets``                 current workspace budget (if any)
- ``PUT  /budgets``                 create or update the workspace monthly budget
- ``DELETE /budgets``               remove the workspace budget
- ``POST /admin/usage/evaluate``    run a budget evaluation immediately
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ragrig.config import Settings, get_settings
from ragrig.db.models import Budget
from ragrig.db.session import get_session
from ragrig.deps import AuthContext, require_admin_auth, require_write_auth
from ragrig.usage import (
    aggregate_usage,
    daily_timeseries,
    evaluate_budget,
)

router = APIRouter(tags=["usage"])


class UsageQuery(BaseModel):
    since: datetime | None = None
    until: datetime | None = None
    group_by: str | None = None


class BudgetPayload(BaseModel):
    limit_usd: float = Field(..., gt=0)
    alert_threshold_pct: int = Field(default=80, ge=1, le=100)
    hard_cap: bool = False


class BudgetResponse(BaseModel):
    workspace_id: uuid.UUID
    period: str
    limit_usd: float
    alert_threshold_pct: int
    hard_cap: bool
    last_alert_at: str | None


def _serialize_budget(budget: Budget) -> BudgetResponse:
    return BudgetResponse(
        workspace_id=budget.workspace_id,
        period=budget.period,
        limit_usd=float(budget.limit_usd),
        alert_threshold_pct=int(budget.alert_threshold_pct),
        hard_cap=bool(budget.hard_cap),
        last_alert_at=budget.last_alert_at.isoformat() if budget.last_alert_at else None,
    )


@router.get("/usage", response_model=None)
def get_usage(
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
    since: datetime | None = None,
    until: datetime | None = None,
    group_by: str | None = None,
) -> dict[str, Any]:
    return aggregate_usage(
        session,
        workspace_id=auth.workspace_id,
        since=since,
        until=until,
        group_by=group_by,
    )


@router.get("/usage/timeseries", response_model=None)
def get_usage_timeseries(
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
    days: int = 30,
) -> dict[str, Any]:
    return {"items": daily_timeseries(session, workspace_id=auth.workspace_id, days=days)}


@router.get("/budgets", response_model=None)
def get_budget(
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_write_auth)],
) -> dict[str, Any]:
    budget = session.scalar(
        select(Budget)
        .where(Budget.workspace_id == auth.workspace_id)
        .where(Budget.period == "monthly")
        .limit(1)
    )
    if budget is None:
        return {"budget": None}
    return {"budget": _serialize_budget(budget).model_dump(mode="json")}


@router.put("/budgets", response_model=None)
def upsert_budget(
    body: BudgetPayload,
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> dict[str, Any]:
    budget = session.scalar(
        select(Budget)
        .where(Budget.workspace_id == auth.workspace_id)
        .where(Budget.period == "monthly")
        .limit(1)
    )
    if budget is None:
        budget = Budget(
            id=uuid.uuid4(),
            workspace_id=auth.workspace_id,
            period="monthly",
            limit_usd=body.limit_usd,
            alert_threshold_pct=body.alert_threshold_pct,
            hard_cap=body.hard_cap,
        )
        session.add(budget)
    else:
        budget.limit_usd = body.limit_usd
        budget.alert_threshold_pct = body.alert_threshold_pct
        budget.hard_cap = body.hard_cap
        # Reset alert latch when admin changes the limit.
        budget.last_alert_at = None
        session.add(budget)
    session.commit()
    return {"budget": _serialize_budget(budget).model_dump(mode="json")}


@router.delete("/budgets", status_code=status.HTTP_204_NO_CONTENT)
def delete_budget(
    session: Annotated[Session, Depends(get_session)],
    auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> None:
    budget = session.scalar(
        select(Budget)
        .where(Budget.workspace_id == auth.workspace_id)
        .where(Budget.period == "monthly")
        .limit(1)
    )
    if budget is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="no budget configured")
    session.delete(budget)
    session.commit()


@router.post("/admin/usage/evaluate", response_model=None)
def evaluate(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    auth: Annotated[AuthContext, Depends(require_admin_auth)],
) -> dict[str, Any]:
    """Run an immediate budget evaluation for the current workspace."""
    result = evaluate_budget(session, workspace_id=auth.workspace_id, settings=settings)
    return {
        "period_spend_usd": result.period_spend_usd,
        "limit_usd": result.limit_usd,
        "threshold_pct": result.threshold_pct,
        "pct_used": result.pct_used,
        "over_threshold": result.over_threshold,
        "over_limit": result.over_limit,
        "alert_fired": result.alert_fired,
        "hard_cap_breached": result.hard_cap_breached,
    }
