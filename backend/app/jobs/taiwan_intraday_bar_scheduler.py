"""Selection and cadence only; canonical JobRun owns every fetch/repair."""
from __future__ import annotations

from datetime import datetime, time, timedelta
import logging
from typing import Any, Callable

from app.config import settings
from app.db.models import JobRun
from app.db.session import SessionLocal
from app.jobs.taiwan_intraday_demand import (
    JOB_TYPE, PREFIX, _reread, dispatch_due_materializations,
    enqueue_intraday_materialization_demand, materialization_request,
)
from app.market.trading_calendar import TAIWAN_TZ, is_taiwan_trading_day, taiwan_market_session_phase
from app.market.tw_intraday_universe import resolve_taiwan_intraday_target_universe, resolve_taiwan_tier_a_target_plan
from app.jobs.taiwan_intraday_repair import audit_completed_sessions, checkpoint, save_checkpoint

logger = logging.getLogger(__name__)
TAIWAN_INTRADAY_CLOSE_TAIL_RETRY_MINUTES = (25, 30, 33)
TAIWAN_INTRADAY_CLOSE_TAIL_TRIGGER_SECOND = 5
TAIWAN_INTRADAY_CLOSE_TAIL_COOLDOWN_SECONDS = 120
BACKGROUND_ORIGINS = {"scheduler", "close_tail", "completed_session_repair"}


def _background_slots(db) -> int:
    active = db.query(JobRun).filter(JobRun.job_type == JOB_TYPE,
        JobRun.target.like(PREFIX + "%"), JobRun.status.in_(("queued", "running"))).all()
    count = sum((materialization_request(job) or {}).get("consumer") in BACKGROUND_ORIGINS for job in active)
    return max(0, min(2, max(1, settings.job_worker_max_concurrency - 1)) - count)


def _checkpoint(db, target):
    return checkpoint(db, target)


def _submit_batch(db, symbols, *, now, origin, enqueuer):
    results = []
    slots = _background_slots(db)
    row, state = _checkpoint(db, f"tw-cadence:{origin}:{now.date()}")
    cursor = int(state.get("cursor", 0)) % max(len(symbols), 1)
    for symbol in symbols[cursor:] + symbols[:cursor]:
        if slots <= 0:
            break
        try:
            job, created = enqueuer(db, stock_id=symbol, requested_at=now,
                trade_date=now.date().isoformat(), consumer=origin,
                timeout_seconds=120, max_external_calls=2)
            if job is not None:
                results.append({"stock_id": symbol, "job_id": job.id, "status": job.status, "created": created})
                if job.status in {"queued", "running"}:
                    slots -= 1
        except (ValueError, RuntimeError) as exc:
            db.rollback()
            logger.warning("Taiwan admission failed %s: %s", symbol, type(exc).__name__)
            results.append({"stock_id": symbol, "status": "failed", "reason": str(exc)})
        cursor += 1
    state["cursor"] = cursor % max(len(symbols), 1)
    save_checkpoint(db, row, state, now)
    return results


def collect_taiwan_intraday_bars(*, now: datetime | None = None,
    session_factory: Callable = SessionLocal,
    universe_resolver: Callable = resolve_taiwan_intraday_target_universe,
    enqueuer: Callable = enqueue_intraday_materialization_demand) -> dict:
    local = (now or datetime.now(TAIWAN_TZ)).astimezone(TAIWAN_TZ)
    phase = taiwan_market_session_phase(local)
    if not is_taiwan_trading_day(local.date()) or phase not in {"regular", "closing_auction"}:
        return {"status": "skipped", "reason": "outside_taiwan_intraday_acquisition_window",
                "phase": phase, "requested_count": 0, "refreshed_count": 0, "results": []}
    with session_factory() as db:
        dispatch_due_materializations(db, requested_at=local)
        universe = universe_resolver(db)
        symbols = list(dict.fromkeys(universe.get("symbols") or []))[:settings.scheduler_taiwan_intraday_bar_max_symbols]
        results = _submit_batch(db, symbols, now=local, origin="scheduler", enqueuer=enqueuer)
        return {"status": "pending" if results else "skipped", "phase": phase,
                "requested_count": len(symbols), "submitted_count": len(results),
                "refreshed_count": 0, "universe": universe, "results": results}


def reconcile_taiwan_intraday_close_tails(*, now: datetime | None = None,
    session_factory: Callable = SessionLocal, universe_resolver: Callable | None = None,
    enqueuer: Callable = enqueue_intraday_materialization_demand) -> dict:
    local = (now or datetime.now(TAIWAN_TZ)).astimezone(TAIWAN_TZ)
    if not is_taiwan_trading_day(local.date()) or not time(13, 25) <= local.time().replace(tzinfo=None) < time(13, 35):
        return {"status": "skipped", "reason": "outside_taiwan_intraday_close_tail_window", "results": []}
    with session_factory() as db:
        dispatch_due_materializations(db, requested_at=local)
        resolver = universe_resolver or resolve_taiwan_tier_a_target_plan
        universe = resolver(db, max_symbols=settings.scheduler_taiwan_intraday_close_tail_max_symbols,
            **({"operation_profile": "production_session_close"} if universe_resolver is None else {}))
        symbols = list(dict.fromkeys(universe.get("symbols") or []))[:settings.scheduler_taiwan_intraday_close_tail_max_symbols]
        results = _submit_batch(db, symbols, now=local, origin="close_tail", enqueuer=enqueuer)
        return {"status": "pending" if results else "skipped", "trade_date": local.date().isoformat(),
                "requested_count": len(symbols), "submitted_count": len(results), "results": results}


def audit_completed_taiwan_intraday_coverage(*, now: datetime | None = None,
    session_factory: Callable = SessionLocal,
    enqueuer: Callable = enqueue_intraday_materialization_demand) -> dict:
    """Freeze/audit normal ingestion, then resume only residual recovery."""
    local = (now or datetime.now(TAIWAN_TZ)).astimezone(TAIWAN_TZ)
    with session_factory() as db:
        dispatch_due_materializations(db, requested_at=local)
        return audit_completed_sessions(db, now=local, reread=_reread,
            enqueuer=enqueuer, background_slots=_background_slots)


def resume_taiwan_materializations() -> None:
    with SessionLocal() as db:
        dispatch_due_materializations(db, requested_at=datetime.now(TAIWAN_TZ))


def add_taiwan_intraday_bar_jobs(scheduler: Any) -> bool:
    if not settings.enable_taiwan_intraday_bar_scheduler:
        return False
    interval = max(int(settings.scheduler_taiwan_intraday_bar_interval_seconds), 60)
    for function, job_id, seconds in (
        (collect_taiwan_intraday_bars, "taiwan_intraday_bar_materialization", interval),
        (audit_completed_taiwan_intraday_coverage, "taiwan_intraday_completed_coverage",
         settings.scheduler_taiwan_completed_materialization_interval_seconds),
        (resume_taiwan_materializations, "taiwan_intraday_materialization_retry", 15),
    ):
        scheduler.add_job(function, trigger="interval", seconds=seconds, id=job_id,
            replace_existing=True, coalesce=True, max_instances=1,
            next_run_time=datetime.now(TAIWAN_TZ) + timedelta(seconds=10))
    for minute in TAIWAN_INTRADAY_CLOSE_TAIL_RETRY_MINUTES:
        scheduler.add_job(reconcile_taiwan_intraday_close_tails, trigger="cron", day_of_week="mon-fri",
            hour=13, minute=minute, second=TAIWAN_INTRADAY_CLOSE_TAIL_TRIGGER_SECOND,
            id=f"taiwan_intraday_close_tail_13{minute:02d}", replace_existing=True, coalesce=True, max_instances=1)
    return True
