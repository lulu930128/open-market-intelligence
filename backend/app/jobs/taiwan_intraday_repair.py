"""Frozen completed-session ingestion and residual recovery on one obligation ledger.

Acquisition/persistence remain exclusively with the canonical materialization job.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json
import hashlib
import logging
from threading import Lock

from sqlalchemy import case, func, or_, update
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db.models import JobRun, StockMaster, TaiwanIntradayRepairItem, TaiwanIntradaySchedulerState
from app.jobs.taiwan_intraday_demand import JOB_TYPE, PREFIX, materialization_request, completed_lane_backoff
from app.market.trading_calendar import TAIWAN_TZ, latest_completed_taiwan_session_date, previous_taiwan_trading_day, taiwan_market_session_phase
from app.market.tw_instrument import resolve_taiwan_instrument
from app.market.tw_intraday_platform import completed_taiwan_intraday_repair_eligibility
from app.market_data.contracts import InstrumentType

logger = logging.getLogger(__name__)
AUDIT_PREFIX = "tw-coverage-audit:"
SLICE_SIZE = 32
_pass_lock = Lock()


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def checkpoint(db, key: str, *, initial: dict | None = None):
    row = db.get(TaiwanIntradaySchedulerState, key)
    if row is None:
        row = TaiwanIntradaySchedulerState(key=key, state_json=json.dumps(initial or {}))
        db.add(row)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            row = db.get(TaiwanIntradaySchedulerState, key)
            if row is None:
                raise
    return row, json.loads(row.state_json)


def save_checkpoint(db, row, state, now):
    row.state_json = json.dumps(state)
    row.revision += 1
    row.updated_at = now
    db.commit()


def _eligible(db, symbol: str) -> bool:
    master = db.query(StockMaster).filter(StockMaster.stock_id == symbol).first()
    if master is None or not master.is_active:
        return False
    try:
        instrument = resolve_taiwan_instrument(db, symbol)
    except ValueError:
        return False
    return instrument.instrument_type in {InstrumentType.STOCK, InstrumentType.ETF}


def _cycle_budget(db, now):
    seconds = settings.scheduler_taiwan_intraday_repair_window_seconds
    start = datetime.fromtimestamp(int(now.timestamp()) // seconds * seconds, tz=TAIWAN_TZ)
    end = start + timedelta(seconds=seconds)
    key = f"tw-repair-window:{start.isoformat()}"
    row = db.get(TaiwanIntradaySchedulerState, key)
    if row is not None:
        return row, json.loads(row.state_json)
    # A new window replenishes throughput, not obligations. Seed any admission
    # already committed in this execution window, regardless of target date.
    episodes = db.query(JobRun).filter(JobRun.job_type == JOB_TYPE,
        JobRun.target.like(PREFIX + "%"), JobRun.created_at >= start.astimezone(timezone.utc),
        JobRun.created_at < end.astimezone(timezone.utc)).all()
    used = sum((materialization_request(job) or {}).get("consumer") == "completed_session_repair"
               for job in episodes)
    return checkpoint(db, key, initial={"window_start": start.isoformat(),
        "window_end": end.isoformat(), "reserved": used})


def _reserve(db, now) -> bool:
    """Conservative, durable admission reservation, including crash uncertainty."""
    for _ in range(4):
        row, state = _cycle_budget(db, now)
        if state.get("reserved", 0) >= settings.scheduler_taiwan_intraday_repair_max_symbols_per_window:
            return False
        revision = row.revision
        state["reserved"] = int(state.get("reserved", 0)) + 1
        changed = db.execute(update(TaiwanIntradaySchedulerState).where(
            TaiwanIntradaySchedulerState.key == row.key,
            TaiwanIntradaySchedulerState.revision == revision,
        ).values(state_json=json.dumps(state), revision=revision + 1, updated_at=now),
            execution_options={"synchronize_session": False}).rowcount
        db.commit()
        if changed:
            return True
        db.expire_all()
    return False


def _observe(db, item, now, reread, frozen=None) -> bool:
    """Every resolution, including horizon expiry, first checks canonical truth."""
    # Canonical reads may be expensive. Never flush an attached new item or
    # dirty status before reading: that would retain SQLite's writer lock across
    # the read and block unrelated market writers.
    error = None
    coverage = None
    with db.no_autoflush:
        eligible = _eligible(db, item.stock_id)
        identity_changed = False
        expected = (frozen or {}).get(item.stock_id)
        if eligible and expected:
            instrument = resolve_taiwan_instrument(db, item.stock_id)
            identity_changed = (instrument.venue != expected["venue"]
                                or instrument.instrument_type.value != expected["instrument_type"])
            eligible = not identity_changed
        if eligible:
            try:
                coverage = reread(db, {"stock_id": item.stock_id, "trade_date": item.trade_date.isoformat(),
                                       "realtime_policy": "prefer_live"}, now)
            except (ValueError, RuntimeError) as exc:
                error = type(exc).__name__
    item.updated_at = now
    item.scanned_at = now
    item.next_check_at = now + timedelta(minutes=5)
    if not eligible:
        item.status = "not_applicable"
        item.last_reason = "FROZEN_INSTRUMENT_CHANGED" if identity_changed else "INSTRUMENT_NOT_ELIGIBLE"
        return False
    if error is not None:
        reachable = completed_taiwan_intraday_repair_eligibility(item.trade_date.isoformat(), now=now)["eligible"]
        item.status = "pending" if reachable else "unfillable"
        item.last_reason = (f"CANONICAL_REREAD_FAILED:{error}" if reachable
                            else "OUT_OF_REPAIR_HORIZON_WITH_READ_FAILURE")
        logger.warning("TW repair reread failed %s %s: %s", item.stock_id, item.trade_date, error)
        return False
    item.coverage_json = json.dumps(coverage)
    if coverage.get("reread_ready") and coverage.get("reread_trade_date") == item.trade_date.isoformat():
        item.status = "complete"
        item.last_reason = "CANONICAL_COVERAGE_READY"
        return False
    reach = completed_taiwan_intraday_repair_eligibility(item.trade_date.isoformat(), now=now)
    if not reach["eligible"]:
        item.status = "unfillable"
        item.last_reason = "OUT_OF_REPAIR_HORIZON"
        return False
    item.status = "pending"
    item.last_reason = "CANONICAL_COVERAGE_INCOMPLETE"
    return True


def _freeze(db, row, state, target, now):
    """Atomic, metadata-only snapshot; no provider IO or canonical bar writes."""
    if "universe_revision" in state:
        return
    universe = []
    with db.no_autoflush:
        for (symbol,) in db.query(StockMaster.stock_id).order_by(StockMaster.stock_id).all():
            if not _eligible(db, symbol):
                continue
            instrument = resolve_taiwan_instrument(db, symbol)
            universe.append({"stock_id": symbol, "venue": instrument.venue,
                             "instrument_type": instrument.instrument_type.value})
            item = db.get(TaiwanIntradayRepairItem, (target, symbol))
            if item is None:
                item = TaiwanIntradayRepairItem(trade_date=target, stock_id=symbol,
                    acquisition_lane="normal", status="pending")
                db.add(item)
            elif (item.attempt_count == 0 and item.last_job_id is None
                  and item.last_reason in {None, "CANONICAL_COVERAGE_INCOMPLETE", "CANONICAL_COVERAGE_READY"}):
                # Prior versions discovered the entire universe as repair work.
                # Only untouched rows move to normal; preserve tried recovery.
                item.acquisition_lane = "normal"
                item.status = "pending"
            if item.acquisition_lane == "normal":
                item.scanned_at = None
    if not universe:
        state.update(universe_unavailable=True, eligible_count=0, coverage_scan_complete=False,
                     lifecycle_complete=False)
        save_checkpoint(db, row, state, now)
        return
    state.pop("universe_unavailable", None)
    material = json.dumps(universe, sort_keys=True, separators=(",", ":"))
    state.update(universe=universe, universe_revision=hashlib.sha256(material.encode()).hexdigest(),
        frozen_at=now.isoformat(), started_at=now.isoformat(), trade_date=target.isoformat(),
        eligible_count=len(universe), coverage_scan_complete=False, lifecycle_complete=False)
    save_checkpoint(db, row, state, now)


def _handoff(item, now, reason, job=None):
    item.acquisition_lane = "repair"
    item.status = "pending"
    item.last_reason = reason
    item.next_check_at = now + timedelta(minutes=5)
    if job is not None:
        item.last_job_id = job.id
        retry = json.loads(job.result_json or "{}").get("retry_not_before_at")
        if retry:
            item.next_check_at = max(item.next_check_at, _aware(datetime.fromisoformat(retry)))


def _normal_slots(db):
    active = db.query(JobRun).filter(JobRun.job_type == JOB_TYPE,
        JobRun.target.like(PREFIX + "%"), JobRun.status.in_(("queued", "running"))).all()
    used = sum((materialization_request(job) or {}).get("consumer") == "completed_session" for job in active)
    return max(0, settings.taiwan_completed_materialization_concurrency - used)


def _normal_materialization(db, target, now, reread, enqueuer, frozen):
    batch = settings.scheduler_taiwan_completed_materialization_batch_size
    query = db.query(TaiwanIntradayRepairItem).filter(TaiwanIntradayRepairItem.trade_date == target,
        TaiwanIntradayRepairItem.stock_id.in_(list(frozen)))
    # Scan every frozen member, including legacy recovery rows, in bounded pages.
    for item in query.filter(TaiwanIntradayRepairItem.acquisition_lane == "normal",
            TaiwanIntradayRepairItem.scanned_at.is_(None)).order_by(
            TaiwanIntradayRepairItem.stock_id).limit(batch).all():
        if item.acquisition_lane == "normal":
            _observe(db, item, now, reread, frozen)
            item.next_check_at = now
        item.scanned_at = now
        db.commit()
    # Reconcile before admitting more; never infer coverage from Job success.
    for item in query.filter(TaiwanIntradayRepairItem.acquisition_lane == "normal",
            TaiwanIntradayRepairItem.normal_attempted_at.is_not(None),
            TaiwanIntradayRepairItem.status.in_(("pending", "active"))).order_by(
                TaiwanIntradayRepairItem.stock_id).limit(batch).all():
        job = _latest_job(db, item)
        if job is not None and job.status in {"queued", "running"}:
            item.status = "active"
            item.last_job_id = job.id
        else:
            _observe(db, item, now, reread, frozen)
            if item.status == "pending":
                _handoff(item, now, "NORMAL_MATERIALIZATION_INCOMPLETE", job)
        db.commit()
    slots = _normal_slots(db)
    backoff = completed_lane_backoff(db)
    if slots <= 0 or (backoff and now < backoff) or taiwan_market_session_phase(now) in {"regular", "closing_auction"}:
        return
    items = query.filter(TaiwanIntradayRepairItem.acquisition_lane == "normal",
        TaiwanIntradayRepairItem.status == "pending", TaiwanIntradayRepairItem.scanned_at.is_not(None),
        TaiwanIntradayRepairItem.normal_attempted_at.is_(None)).order_by(
            TaiwanIntradayRepairItem.stock_id).limit(min(slots, batch)).all()
    for item in items:
        if item.scanned_at.replace(tzinfo=None) != now.replace(tzinfo=None) and not _observe(db, item, now, reread, frozen):
            db.commit()
            continue
        job = _latest_job(db, item)
        if job is not None:
            # Dedupe includes admissions committed before a coordinator crash.
            result = json.loads(job.result_json or "{}")
            retry = result.get("retry_not_before_at")
            if job.status not in {"queued", "running"} and retry and _aware(datetime.fromisoformat(retry)) > now:
                _handoff(item, now, "EXISTING_PROVIDER_BACKOFF", job)
                db.commit()
                continue
        item.normal_attempted_at = now
        item.status = "active"
        db.commit()  # Crash uncertainty hands off; normal never retries blindly.
        try:
            job, _ = enqueuer(db, stock_id=item.stock_id, trade_date=target.isoformat(),
                requested_at=now, consumer="completed_session", timeout_seconds=120,
                max_external_calls=2)
            if job is not None:
                item.last_job_id = job.id
            if job is None or job.status not in {"queued", "running"}:
                _observe(db, item, now, reread, frozen)
                if item.status == "pending":
                    _handoff(item, now, "NORMAL_MATERIALIZATION_INCOMPLETE", job)
        except (ValueError, RuntimeError) as exc:
            db.rollback()
            _handoff(item, now, f"NORMAL_ADMISSION_FAILED:{type(exc).__name__}")
            logger.warning("TW normal admission failed %s %s: %s", item.stock_id, target, type(exc).__name__)
        db.commit()


def _latest_job(db, item):
    # Recover admission that committed before the backlog could store its id.
    candidates = db.query(JobRun).filter(JobRun.job_type == JOB_TYPE,
        JobRun.target.like(f"{PREFIX}TW:%:{item.stock_id}:{item.trade_date}:tw.intraday.1m:1m")
    ).order_by(JobRun.id.desc()).limit(1).all()
    return next((job for job in candidates if materialization_request(job)), None)


def _process_backlog(db, target, now, reread, enqueuer, background_slots, frozen=None):
    items = db.query(TaiwanIntradayRepairItem).filter(
        TaiwanIntradayRepairItem.trade_date == target,
        TaiwanIntradayRepairItem.acquisition_lane == "repair",
        TaiwanIntradayRepairItem.status.in_(("pending", "active")),
        or_(TaiwanIntradayRepairItem.next_check_at.is_(None), TaiwanIntradayRepairItem.next_check_at <= now),
    ).order_by(case((TaiwanIntradayRepairItem.status == "active", 0), else_=1),
               TaiwanIntradayRepairItem.attempt_count, TaiwanIntradayRepairItem.updated_at,
               TaiwanIntradayRepairItem.stock_id).limit(SLICE_SIZE).all()
    slots = background_slots(db)
    for item in items:
        was_active = item.status == "active"
        repairable = _observe(db, item, now, reread, frozen)
        job = _latest_job(db, item) if item.status not in {"complete", "not_applicable"} else None
        if job is not None:
            item.last_job_id = job.id
            # Expiration belongs to the canonical dispatcher, including queued
            # jobs beyond its current bounded slice. Never admit an overlapping
            # episode or close an obligation while that owner still has it.
            if job.status in {"queued", "running"}:
                item.status = "active"
                db.commit()
                continue
            result = json.loads(job.result_json or "{}")
            retry_after = result.get("retry_not_before_at")
            if retry_after and _aware(datetime.fromisoformat(retry_after)) > now:
                item.next_check_at = _aware(datetime.fromisoformat(retry_after)).astimezone(TAIWAN_TZ)
                db.commit()
                continue
        db.commit()
        # A terminal job releases its active obligation to the pending
        # fairness order. Never renew it from the active-priority slice.
        if was_active:
            continue
        backoff = completed_lane_backoff(db)
        if not repairable or slots <= 0 or (backoff and now < backoff) or not _reserve(db, now):
            continue
        # Save attempted admission before invoking the independently committing
        # Job owner. A crash never loses the coverage obligation or its budget.
        item.attempt_count += 1
        db.commit()
        try:
            job, created = enqueuer(db, stock_id=item.stock_id, trade_date=target.isoformat(),
                requested_at=now, consumer="completed_session_repair", timeout_seconds=120,
                max_external_calls=2)
            if job is not None:
                item.last_job_id = job.id
                item.status = "active" if job.status in {"queued", "running"} else "pending"
                if item.status == "active":
                    slots -= 1
                # Even a terminal success must pass an exact-date reread.
                elif job.status == "success":
                    _observe(db, item, now, reread, frozen)
        except (ValueError, RuntimeError) as exc:
            db.rollback()
            item.last_reason = f"ADMISSION_FAILED:{type(exc).__name__}"
            item.status = "pending"
            logger.warning("TW repair admission failed %s %s: %s", item.stock_id, target, type(exc).__name__)
        db.commit()


def _summary(db, row, state, target, now):
    members = [item["stock_id"] for item in state.get("universe", [])]
    query = db.query(TaiwanIntradayRepairItem).filter(
        TaiwanIntradayRepairItem.trade_date == target)
    if "universe_revision" in state:
        query = query.filter(TaiwanIntradayRepairItem.stock_id.in_(members))
    items = query.all()
    counts = {}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1
    pending = counts.get("pending", 0)
    active = counts.get("active", 0)
    unfillable = counts.get("unfillable", 0)
    scanned = sum(item.scanned_at is not None for item in items)
    if "universe_revision" in state:
        state["coverage_scan_complete"] = scanned == len(members)
    closed = bool(state.get("coverage_scan_complete") and pending + active == 0)
    _, budget = _cycle_budget(db, now)
    # Old daily-budget diagnostics are not the active admission policy.
    state.pop("daily_admissions_reserved", None)
    state.pop("budget_execution_date", None)
    repair_items = [item for item in items if item.acquisition_lane == "repair"]
    queued = 0
    for item in items:
        if item.status == "active" and item.last_job_id:
            job = db.get(JobRun, item.last_job_id)
            queued += bool(job and job.status == "queued")
    complete = counts.get("complete", 0)
    terminal = unfillable + counts.get("not_applicable", 0)
    results = [json.loads(result or "{}") for (result,) in db.query(JobRun.result_json).filter(
        JobRun.job_type == JOB_TYPE, JobRun.target.like(PREFIX + "%"),
        func.json_extract(JobRun.request_json, "$.trade_date") == target.isoformat(),
        func.json_extract(JobRun.request_json, "$.consumer").in_(("completed_session", "completed_session_repair")),
    ).all()]
    if complete and not state.get("first_completion_at"):
        state["first_completion_at"] = now.isoformat()
    if closed and not state.get("lifecycle_completed_at"):
        state["lifecycle_completed_at"] = now.isoformat()
    end = datetime.fromisoformat(state["lifecycle_completed_at"]) if closed and state.get("lifecycle_completed_at") else now
    duration = max(0, (end - datetime.fromisoformat(state.get("started_at", now.isoformat()))).total_seconds())
    state.update(trade_date=target.isoformat(), audited_count=scanned,
        scanned_count=scanned, complete_count=complete, pending_count=pending,
        queued_count=queued, active_count=active - queued,
        failed_retryable_count=sum(item.status in {"pending", "active"} for item in repair_items),
        terminal_count=terminal, remaining_count=pending + active,
        normal_submitted_count=sum(item.normal_attempted_at is not None for item in items),
        normal_succeeded_count=sum(item.normal_attempted_at is not None and item.acquisition_lane == "normal" and item.status == "complete" for item in items),
        normal_failed_count=sum(item.normal_attempted_at is not None for item in repair_items),
        repair_retry_count=sum(item.attempt_count for item in repair_items),
        provider_failure_count=sum(result.get("provider_failure_count", 0) for result in results),
        provider_backoff_count=sum(result.get("provider_backoff_count", 0) for result in results),
        provider_retry_count=sum(max(0, result.get("attempt_count", 0) - 1) for result in results),
        provider_metrics_unknown_jobs=sum("provider_failure_count" not in result for result in results),
        completion_ratio=complete / len(items) if items else 0,
        terminal_ratio=terminal / len(items) if items else 0,
        duration_seconds=duration, throughput_symbols_per_minute=complete * 60 / duration if duration else 0,
        pending_repair_count=sum(item.status == "pending" for item in repair_items),
        active_repair_count=sum(item.status == "active" for item in repair_items),
        completed_repair_count=sum(item.status == "complete" for item in repair_items), unfillable_count=unfillable,
        not_applicable_count=counts.get("not_applicable", 0),
        repair_backlog_empty=all(item.status not in {"pending", "active"} for item in repair_items), lifecycle_complete=closed,
        repair_complete=closed and unfillable == 0, data_complete=closed and unfillable == 0,
        admission_window_start=budget["window_start"], admission_window_end=budget["window_end"],
        admissions_reserved=budget.get("reserved", 0),
        admission_limit=settings.scheduler_taiwan_intraday_repair_max_symbols_per_window,
        repair_budget_exhausted=budget.get("reserved", 0) >= settings.scheduler_taiwan_intraday_repair_max_symbols_per_window)
    save_checkpoint(db, row, state, now)
    return state


def audit_completed_sessions(db, *, now, reread, enqueuer, background_slots):
    if not _pass_lock.acquire(blocking=False):
        return {"status": "skipped", "reason": "coverage_audit_in_flight"}
    try:
        latest = latest_completed_taiwan_session_date(now)
        if latest == now.date() and now.time().replace(tzinfo=None) < time(13, 35):
            latest = previous_taiwan_trading_day(latest, include_value=False)
        checkpoint(db, f"{AUDIT_PREFIX}{latest}", initial={"trade_date": latest.isoformat()})
        states = db.query(TaiwanIntradaySchedulerState).filter(
            TaiwanIntradaySchedulerState.key.like(AUDIT_PREFIX + "%")
        ).order_by(TaiwanIntradaySchedulerState.key).all()
        unresolved = [row for row in states if (not json.loads(row.state_json).get("lifecycle_complete")
                      or "universe_revision" not in json.loads(row.state_json))
                      and date.fromisoformat(row.key[len(AUDIT_PREFIX):]) <= latest]
        # Latest normal ingestion takes the current-date provider opportunity;
        # the oldest unresolved session still advances toward terminalization.
        newest = next(row for row in states if row.key == f"{AUDIT_PREFIX}{latest}")
        selected = [newest] + [row for row in unresolved[:1] if row is not newest]
        summaries = []
        for row in selected:
            state = json.loads(row.state_json)
            target = date.fromisoformat(row.key[len(AUDIT_PREFIX):])
            _freeze(db, row, state, target, now)
            frozen = {item["stock_id"]: item for item in state.get("universe", [])}
            _normal_materialization(db, target, now, reread, enqueuer, frozen)
            due = state.get("next_repair_cycle_at")
            if due is None or now >= datetime.fromisoformat(due):
                _process_backlog(db, target, now, reread, enqueuer, background_slots, frozen)
                state["next_repair_cycle_at"] = (now + timedelta(
                    seconds=settings.scheduler_taiwan_intraday_repair_interval_seconds)).isoformat()
            summaries.append(_summary(db, row, state, target, now))
        return {**summaries[0], "sessions": summaries}
    finally:
        _pass_lock.release()
