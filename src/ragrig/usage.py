"""Usage accounting and budget enforcement.

Provides two responsibilities:

1. **Recording**: ``record_usage_events`` persists a flat list of model-call
   summaries (the ``cost_latency["operations"]`` payload produced by
   ``ragrig.observability``) as ``UsageEvent`` rows. Cheap, no model load.

2. **Aggregation + budgets**: ``aggregate_usage`` rolls up rows for a workspace
   and ``evaluate_budget`` checks the current period spend against the
   workspace's ``Budget``. When threshold is crossed an alert fires through
   the existing email + webhook channels.

This module is intentionally synchronous and self-contained — it can be called
from any request handler that already produced a ``cost_latency`` payload
(``/retrieval/search``, ``/retrieval/answer``, ``/v1/chat/completions``).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ragrig.config import Settings
from ragrig.db.models import Budget, UsageEvent

logger = logging.getLogger(__name__)


# ── Recording ────────────────────────────────────────────────────────────────


def record_usage_events(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID | None,
    operations: list[dict[str, Any]],
    request_metadata: dict[str, Any] | None = None,
) -> int:
    """Persist one row per operation in *operations*.

    ``operations`` is the list returned by
    ``ragrig.observability.cost_latency.observe_model_call`` (the same one
    embedded under ``cost_latency.operations`` on retrieval / answer reports).
    Returns the number of rows written.
    """
    if not operations:
        return 0
    rows = []
    for op in operations:
        if not isinstance(op, dict):
            continue
        rows.append(
            UsageEvent(
                id=uuid.uuid4(),
                workspace_id=workspace_id,
                user_id=user_id,
                operation=str(op.get("operation") or "unknown"),
                provider=str(op.get("provider") or "unknown"),
                model=str(op.get("model") or ""),
                input_tokens=int(op.get("input_tokens_estimated") or 0),
                output_tokens=int(op.get("output_tokens_estimated") or 0),
                cost_usd=float(op.get("total_cost_usd_estimated") or 0.0),
                latency_ms=float(op.get("latency_ms") or 0.0),
                metadata_json=request_metadata or {},
            )
        )
    if not rows:
        return 0
    session.add_all(rows)
    session.commit()
    return len(rows)


# ── Aggregation ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UsageWindow:
    start: datetime
    end: datetime


def current_month_window(now: datetime | None = None) -> UsageWindow:
    """Return the [start, end) of the current calendar month in UTC."""
    moment = now or datetime.now(UTC)
    start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return UsageWindow(start=start, end=end)


def aggregate_usage(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    since: datetime | None = None,
    until: datetime | None = None,
    group_by: str | None = None,
) -> dict[str, Any]:
    """Return totals for the window, optionally grouped.

    ``group_by`` is one of ``"operation"``, ``"model"``, ``"user"`` (any other
    value returns only the global totals).
    """
    stmt_filters = [UsageEvent.workspace_id == workspace_id]
    if since is not None:
        stmt_filters.append(UsageEvent.created_at >= since)
    if until is not None:
        stmt_filters.append(UsageEvent.created_at < until)

    totals_row = session.execute(
        select(
            func.count(UsageEvent.id).label("event_count"),
            func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("input_tokens"),
            func.coalesce(func.sum(UsageEvent.output_tokens), 0).label("output_tokens"),
            func.coalesce(func.sum(UsageEvent.cost_usd), 0).label("cost_usd"),
            func.coalesce(func.avg(UsageEvent.latency_ms), 0).label("avg_latency_ms"),
        ).where(*stmt_filters)
    ).one()

    response: dict[str, Any] = {
        "event_count": int(totals_row.event_count),
        "input_tokens": int(totals_row.input_tokens or 0),
        "output_tokens": int(totals_row.output_tokens or 0),
        "total_tokens": int((totals_row.input_tokens or 0) + (totals_row.output_tokens or 0)),
        "cost_usd": round(float(totals_row.cost_usd or 0.0), 8),
        "avg_latency_ms": round(float(totals_row.avg_latency_ms or 0.0), 3),
    }

    if group_by in ("operation", "model", "user"):
        column = {
            "operation": UsageEvent.operation,
            "model": UsageEvent.model,
            "user": UsageEvent.user_id,
        }[group_by]
        grouped_rows = session.execute(
            select(
                column.label("key"),
                func.count(UsageEvent.id).label("count"),
                func.coalesce(func.sum(UsageEvent.cost_usd), 0).label("cost_usd"),
                func.coalesce(func.sum(UsageEvent.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(UsageEvent.output_tokens), 0).label("output_tokens"),
            )
            .where(*stmt_filters)
            .group_by(column)
            .order_by(func.sum(UsageEvent.cost_usd).desc())
        ).all()
        response["groups"] = [
            {
                "key": str(row.key) if row.key is not None else None,
                "count": int(row.count),
                "cost_usd": round(float(row.cost_usd or 0.0), 8),
                "input_tokens": int(row.input_tokens or 0),
                "output_tokens": int(row.output_tokens or 0),
            }
            for row in grouped_rows
        ]
    return response


def daily_timeseries(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Return per-day cost + token totals for the last *days* days."""
    days = max(1, min(days, 365))
    end = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    start = end - timedelta(days=days)
    bucket = func.date(UsageEvent.created_at)
    rows = session.execute(
        select(
            bucket.label("day"),
            func.count(UsageEvent.id).label("count"),
            func.coalesce(func.sum(UsageEvent.cost_usd), 0).label("cost_usd"),
            func.coalesce(func.sum(UsageEvent.input_tokens + UsageEvent.output_tokens), 0).label(
                "tokens"
            ),
        )
        .where(UsageEvent.workspace_id == workspace_id)
        .where(UsageEvent.created_at >= start)
        .where(UsageEvent.created_at < end)
        .group_by(bucket)
        .order_by(bucket.asc())
    ).all()
    return [
        {
            "day": str(row.day),
            "count": int(row.count or 0),
            "cost_usd": round(float(row.cost_usd or 0.0), 8),
            "tokens": int(row.tokens or 0),
        }
        for row in rows
    ]


# ── Budget enforcement ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class BudgetEvaluation:
    """Result of evaluating a workspace's spend vs. its monthly budget.

    ``alert_fired`` is True the *first* time the spend crosses
    ``alert_threshold_pct`` in a period; subsequent calls within the same
    month return False to avoid notification spam.
    """

    budget: Budget | None
    period_spend_usd: float
    limit_usd: float
    threshold_pct: int
    pct_used: float
    over_threshold: bool
    over_limit: bool
    alert_fired: bool
    hard_cap_breached: bool


def evaluate_budget(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    settings: Settings | None = None,
    fire_alert: bool = True,
) -> BudgetEvaluation:
    """Check the current month spend against the workspace budget.

    On the first crossing of ``alert_threshold_pct`` within the period, sends a
    notification through ``ragrig.email`` (if SMTP is configured) and
    ``ragrig.webhooks`` (if a webhook URL is configured). ``last_alert_at`` is
    updated atomically to prevent duplicate alerts in the same month.
    """
    budget = session.scalar(
        select(Budget)
        .where(Budget.workspace_id == workspace_id)
        .where(Budget.period == "monthly")
        .limit(1)
    )
    window = current_month_window()
    spend = session.scalar(
        select(func.coalesce(func.sum(UsageEvent.cost_usd), 0))
        .where(UsageEvent.workspace_id == workspace_id)
        .where(UsageEvent.created_at >= window.start)
        .where(UsageEvent.created_at < window.end)
    )
    period_spend = float(spend or 0.0)

    if budget is None:
        return BudgetEvaluation(
            budget=None,
            period_spend_usd=round(period_spend, 8),
            limit_usd=0.0,
            threshold_pct=0,
            pct_used=0.0,
            over_threshold=False,
            over_limit=False,
            alert_fired=False,
            hard_cap_breached=False,
        )

    limit = float(budget.limit_usd or 0.0)
    pct_used = (period_spend / limit * 100.0) if limit > 0 else 0.0
    over_threshold = pct_used >= float(budget.alert_threshold_pct)
    over_limit = limit > 0 and period_spend >= limit
    hard_cap = bool(budget.hard_cap) and over_limit

    alert_fired = False
    if fire_alert and over_threshold:
        last_alert = budget.last_alert_at
        if last_alert is None or last_alert < window.start:
            _send_budget_alert(
                settings=settings,
                workspace_id=workspace_id,
                period_spend=period_spend,
                limit=limit,
                pct_used=pct_used,
                window=window,
            )
            budget.last_alert_at = datetime.now(UTC)
            session.add(budget)
            session.commit()
            alert_fired = True

    return BudgetEvaluation(
        budget=budget,
        period_spend_usd=round(period_spend, 8),
        limit_usd=round(limit, 4),
        threshold_pct=int(budget.alert_threshold_pct),
        pct_used=round(pct_used, 2),
        over_threshold=over_threshold,
        over_limit=over_limit,
        alert_fired=alert_fired,
        hard_cap_breached=hard_cap,
    )


def _send_budget_alert(
    *,
    settings: Settings | None,
    workspace_id: uuid.UUID,
    period_spend: float,
    limit: float,
    pct_used: float,
    window: UsageWindow,
) -> None:
    if settings is None:
        return
    subject = f"[RAGRig] Workspace {workspace_id} reached {pct_used:.1f}% of monthly budget"
    body = (
        f"Workspace {workspace_id} has spent ${period_spend:.4f} of ${limit:.4f} "
        f"({pct_used:.1f}%) for the period {window.start.date()} – {window.end.date()}."
    )
    payload = {
        "event": "budget.threshold",
        "workspace_id": str(workspace_id),
        "period_start": window.start.isoformat(),
        "period_end": window.end.isoformat(),
        "period_spend_usd": round(period_spend, 8),
        "limit_usd": round(limit, 4),
        "pct_used": round(pct_used, 2),
    }
    try:
        from ragrig.webhooks import deliver_webhook

        deliver_webhook(settings, payload=payload)
    except Exception:  # pragma: no cover - webhook delivery is fire-and-forget
        logger.exception("budget webhook delivery failed")

    if settings.ragrig_smtp_enabled and settings.ragrig_smtp_from:
        try:
            from ragrig.email import send_plain_email

            send_plain_email(
                settings,
                to_email=settings.ragrig_smtp_from,
                subject=subject,
                body=body,
            )
        except Exception:  # pragma: no cover
            logger.exception("budget email send failed")
