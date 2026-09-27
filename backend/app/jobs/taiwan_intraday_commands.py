"""Bounded command adapters over the single Taiwan materialization owner."""

from datetime import datetime, timedelta
from time import monotonic, sleep

from sqlalchemy.orm import Session

from app.db.models import JobRun
from app.jobs.taiwan_intraday_demand import enqueue_intraday_materialization_demand
from app.market.intraday import get_market_intraday_history
from app.market.trading_calendar import TAIWAN_TZ, is_taiwan_trading_day, taiwan_presentation_session
from app.market.tw_intraday_capabilities import TW_INTRADAY_DESCRIPTORS
from app.market.tw_intraday_platform import intraday_history_config


def refresh_intraday_history_command(
    db: Session, *, stock_id: str, interval: str, range_value: str,
    policy: str, requested_at: datetime | None = None, wait_seconds: float = 8,
) -> dict:
    """Preserve chart projection/range while bounding repair to six calls total.

    The public range describes the read window. Repair covers at most three
    reachable sessions per command; older/unattempted coverage stays explicit.
    """
    now = requested_at or datetime.now(TAIWAN_TZ)
    config = intraday_history_config(interval, range_value)
    presentation_date = taiwan_presentation_session(now)["trade_date"]
    days = int(config["days"])
    first = presentation_date if range_value == "1d" else (now - timedelta(days=days)).date()
    dates = [presentation_date - timedelta(days=i)
             for i in range((presentation_date - first).days + 1)
             if is_taiwan_trading_day(presentation_date - timedelta(days=i))]
    lookback = max((item.max_lookback_days or 0 for item in TW_INTRADAY_DESCRIPTORS
                    if item.supports_dated_queries), default=0)
    reachable = [day for day in dates if (now.date() - day).days <= lookback]
    # require_live applies to the acquisition demand, never to a historical repair.
    if policy == "require_live":
        reachable = reachable[:1]
    jobs: list[JobRun] = []
    attempted_dates: list[str] = []
    for day in reachable[:3]:
        job, _ = enqueue_intraday_materialization_demand(
            db, stock_id=stock_id, consumer="front", requested_at=now,
            trade_date=day.isoformat(), policy=policy, timeout_seconds=60,
            max_external_calls=2,
        )
        attempted_dates.append(day.isoformat())
        if job is not None:
            jobs.append(job)
    deadline = monotonic() + max(0, min(wait_seconds, 8))
    while jobs and any(job.status in {"queued", "running"} for job in jobs) and monotonic() < deadline:
        # End the read transaction between polls so other connections' commits
        # (including canonical writes) are visible to the synchronous reread.
        db.rollback()
        sleep(min(0.1, max(0, deadline - monotonic())))
        for job in jobs:
            db.refresh(job)
    db.rollback()
    payload = get_market_intraday_history(db=db, stock_id=stock_id,
        interval=interval, range_value=range_value, refresh=False,
        requested_at=requested_at, bypass_snapshot_cache=True)
    pending = any(job.status in {"queued", "running"} for job in jobs)
    complete = (bool(jobs) and len(attempted_dates) == len(dates)
                and all(job.status == "success" for job in jobs))
    payload["acquisition_status"] = "pending" if pending else "success" if complete else "partial"
    payload["materialization_jobs"] = [
        {"job_id": job.id, "status": job.status, "poll_url": f"/api/ai/refresh-status/{job.id}"}
        for job in jobs]
    payload["repair_scope"] = {"requested_trade_dates": [day.isoformat() for day in dates],
        "attempted_trade_dates": attempted_dates, "max_external_calls": 6,
        "unattempted_trade_dates": [day.isoformat() for day in dates if day.isoformat() not in attempted_dates]}
    limitations = list(payload.get("limitations") or [])
    if pending:
        limitations.append("TW_INTRADAY_MATERIALIZATION_PENDING")
    if len(attempted_dates) < len(dates):
        limitations.append("TW_INTRADAY_REPAIR_WINDOW_BOUNDED")
    if not complete and not pending:
        limitations.append("TW_INTRADAY_MATERIALIZATION_INCOMPLETE")
    payload["limitations"] = list(dict.fromkeys(limitations))
    return payload
