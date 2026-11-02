"""Single-stock history repair, admitted only by the existing Price Map producer.

JobRun is the only durable ledger. Each dispatch makes at most one stock/month
official call; the next normal producer visit continues the SAME JobRun. There
is no polling task, market scan, executor or provider implementation here.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from collections import Counter
from hashlib import sha256
import json
import logging

from app.db.models import JobRun
from sqlalchemy import func
from app.jobs import service as jobs
from app.jobs.job_types import TAIWAN_HISTORICAL_INPUT_REPAIR_JOB_TYPE as JOB_TYPE
from app.jobs import tw_technical_input_readiness as readiness
from app.market.price_map_snapshot_repository import read_input_revisions

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
RETRY_DELAY = timedelta(hours=6)


def _load(value):
    return json.loads(value) if value else {}


def _dump(value):
    return json.dumps(value, sort_keys=True, default=str)


def historical_repair_candidate(payload):
    return bool(set(payload.get("missing") or ()) & {
        "TW_TECHNICAL_INSUFFICIENT_BARS", "TW_TECHNICAL_DECISION_WINDOW_GAP",
        "TW_TECHNICAL_BAR_STATE_NOT_ELIGIBLE", "PRICE_BASIS_EVENT_COVERAGE_REQUIRED",
    })


def _steps(plan):
    groups = {}
    for day, actions in plan["dates"].items():
        for action in actions:
            groups.setdefault((day[:7], action), []).append(day)
    order = {"instrument_event_refresh": 0, "daily_backfill": 1, "corporate_event_refresh": 2}
    return [(month + ":" + action, action, sorted(groups[(month, action)]))
            for month, action in sorted(groups, key=lambda item: (-int(item[0].replace("-", "")), order[item[1]]))]


def _next_step(plan, state, now):
    if state.get("owner_denied"):
        return None
    steps = _steps(plan)
    attempts = state.get("attempts", {})
    # Event clarification precedes official OHLC for an UNKNOWN month. After
    # that first attempt, unattempted work proceeds even if the page was empty:
    # genuine positive traded evidence can resolve UNKNOWN at canonical owner.
    for key, action, days in steps:
        if key not in attempts:
            return key, action, days
    for key, action, days in steps:
        attempt = attempts[key]
        if attempt["count"] < MAX_ATTEMPTS and datetime.fromisoformat(attempt["retry_at"]) <= now:
            return key, action, days
    return None


def read_pending_historical_repair_stocks(db, *, now):
    """Read due JobRun obligations during the producer's existing header read.

    This looks up this job type's compact continuation fields, never market
    inputs. A ready header may finish an existing bootstrap but cannot create one.
    """
    action = func.json_extract(JobRun.result_json, "$.next_action")
    retry = func.json_extract(JobRun.result_json, "$.next_retry_at")
    rows = db.query(JobRun.target, action, retry).filter(JobRun.job_type == JOB_TYPE,
        JobRun.status.in_(jobs.TERMINAL_STATUSES), action.in_(
            ("NEXT_PRODUCER_VISIT_CONTINUES_SAME_JOB", "WAIT_RETRY"))).all()
    return {target.split(":", 1)[0] for target, next_action, retry_at in rows
            if next_action != "WAIT_RETRY" or datetime.fromisoformat(retry_at) <= now}


def continue_existing_historical_input_repair(db, *, stock_id, now):
    job = db.query(JobRun).filter(JobRun.job_type == JOB_TYPE,
        JobRun.target.startswith(stock_id + ":daily:")).order_by(JobRun.id.desc()).first()
    if job is None or job.status not in jobs.TERMINAL_STATUSES:
        return {"submitted": False}
    state = _load(job.result_json)
    if (state.get("next_action") not in {"NEXT_PRODUCER_VISIT_CONTINUES_SAME_JOB", "WAIT_RETRY"}
            or _next_step(state["remaining"], state, now) is None):
        return {"submitted": False}
    return {"submitted": jobs.continue_job(db, job_id=job.id, task=run_taiwan_historical_input_repair_job)}


def admit_taiwan_historical_input_repair(db, *, stock_id, basis, input_revision, now):
    """Bounded local reread and durable gap dedupe; never provider IO."""
    before = readiness.read_taiwan_historical_repair_input(db, stock_id=stock_id, to_date=basis)
    plan = readiness.plan_taiwan_historical_input_repair(before, to_date=basis)
    if not plan["dates"]:
        return {"status": "not_repairable", "submitted": False}
    # Pin exact gap identity, independent of basis rollover, global event-cache
    # fetch times and revision bumps caused solely by a failed Raw receipt.
    gap_id = sha256(_dump(plan["dates"]).encode()).hexdigest()
    prefix = stock_id + ":daily:"
    # JobService reserves the existing SQLite writer before read/create, also
    # covering independent producers without a new schema or job ledger.
    with jobs.job_target_transaction(db):
        return _admit_locked(db, stock_id=stock_id, basis=basis, input_revision=input_revision,
                             now=now, plan=plan, gap_id=gap_id, prefix=prefix)


def _admit_locked(db, *, stock_id, basis, input_revision, now, plan, gap_id, prefix):
    prior = db.query(JobRun).filter(JobRun.job_type == JOB_TYPE,
        JobRun.target.startswith(prefix)).order_by(JobRun.id.desc()).all()
    for job in prior:
        if job.status in jobs.ACTIVE_STATUSES:
            db.rollback()
            return {"status": "active", "submitted": False, "job_id": job.id}
    for job in prior:
        request = _load(job.request_json)
        if _load(job.result_json).get("owner_denied"):
            db.rollback()
            return {"status": "owner_denied", "submitted": False, "job_id": job.id}
        if set(plan["dates"]) <= set(request["dates"]):
            state = _load(job.result_json)
            if _next_step(plan, state, now) is None:
                db.rollback()
                return {"status": "cooldown_or_exhausted", "submitted": False, "job_id": job.id}
            submitted = jobs.continue_job(db, job_id=job.id, task=run_taiwan_historical_input_repair_job)
            return {"status": "continued", "submitted": submitted, "job_id": job.id}
    request = {"stock_id": stock_id, "timeframe": "daily", "basis": basis.isoformat(),
               "input_revision": input_revision, "gap_id": gap_id, "dates": plan["dates"]}
    # A genuinely new gap may coexist with an exhausted older gap. Carry the
    # older month's attempt budget forward instead of bootstrapping it daily.
    inherited = {}
    for key, _, days in _steps(plan):
        for job in prior:
            attempt = _load(job.result_json).get("attempts", {}).get(key)
            if attempt and set(days) <= set(attempt["dates"]):
                inherited[key] = {**{name: attempt[name] for name in ("count", "dates", "retry_at", "status")},
                                  "prior_job_id": job.id}
                break
    if inherited:
        request["inherited_attempts"] = inherited
    job, created = jobs.enqueue_job(db, job_type=JOB_TYPE, target=prefix + gap_id,
        request=request, task=run_taiwan_historical_input_repair_job, dedupe_active=True,
        message="Queued single-stock bounded historical input repair.")
    return {"status": "queued", "submitted": created, "job_id": job.id}


def _receipt(receipt):
    # Retain official owner outcome/Raw IDs without copying raw pages into Jobs.
    keys = ("status", "reason", "error_type", "request_count", "provider_failure", "event_count")
    return {**{key: receipt[key] for key in keys if key in receipt}, "months": [
        {key: row.get(key) for key in ("month", "status", "raw_result_id", "http_status_code",
                                      "error_message", "inserted_count", "parsed_count")}
        for row in receipt.get("months", [])]}


def _summary(value):
    blockers = value.get("day_state_blockers") or []
    return {**{key: value.get(key) for key in (
        "available_bar_count", "expected_minimum_bar_count", "coverage_status", "from_date", "to_date",
        "technical_decision_usable", "technical_reasons", "required_bars", "decision_window")},
        "day_state_blocker_count": len(blockers),
        "day_state_reason_counts": dict(Counter(reason for item in blockers for reason in item["reasons"]))}


def repair_taiwan_historical_input_job_step(db, job_id, *, clock=lambda: datetime.now(timezone.utc)):
    job = jobs.get_job(db, job_id)
    request, state = _load(job.request_json), _load(job.result_json)
    if not state.get("attempts"):
        state["attempts"] = request.get("inherited_attempts", {})
    symbol, basis = request["stock_id"], date.fromisoformat(request["basis"])
    before = readiness.read_taiwan_historical_repair_input(db, stock_id=symbol, to_date=basis)
    plan = readiness.plan_taiwan_historical_input_repair(before, to_date=basis)
    # A continuation is pinned to its original gap, never to a newer market scan.
    plan["dates"] = {day: actions for day, actions in plan["dates"].items() if day in request["dates"]}
    state.update(status="partial", stock_id=symbol, gap_id=request["gap_id"], basis=str(basis),
                 before=_summary(before), before_revision=read_input_revisions(db, [symbol]).get(symbol, 0))
    step = _next_step(plan, state, clock())
    if step:
        key, operation, days = step
        attempts = state.setdefault("attempts", {})
        attempt = attempts.setdefault(key, {"count": 0})
        attempt.update(count=attempt["count"] + 1, status="attempting", dates=days,
                       retry_at=(clock() + RETRY_DELAY).isoformat())
        # Crash/timeout after this commit is an uncertain attempt, not permission
        # to replay immediately. Owner commits and receipts remain authoritative.
        job.result_json = _dump(state)
        db.commit()
        try:
            receipt = readiness.execute_taiwan_historical_input_step(db, stock_id=symbol,
                basis=basis, operation=operation, days=days, timeout_seconds=8)
            attempt.update(status="attempted", receipt=_receipt(receipt))
            if (receipt.get("error_type") == "PermissionError"
                    or str(receipt.get("status", "")).upper() in {"DENY", "DENIED", "POLICY_DENY"}):
                state["owner_denied"] = True
        except PermissionError:
            db.rollback()
            state["owner_denied"] = True
            attempt.update(status="denied", count=MAX_ATTEMPTS, receipt={"status": "unresolved", "reason": "OWNER_PERMISSION_DENIED"})
        except Exception as exc:
            db.rollback()
            attempt.update(status="error", receipt={"status": "unresolved", "error_type": type(exc).__name__})
            logger.exception("Single-stock history repair failed stock=%s month=%s", symbol, key)
    db.rollback()
    after = readiness.read_taiwan_historical_repair_input(db, stock_id=symbol, to_date=basis)
    remaining = readiness.plan_taiwan_historical_input_repair(after, to_date=basis)
    remaining["dates"] = {day: actions for day, actions in remaining["dates"].items() if day in request["dates"]}
    state.update(after=_summary(after), after_revision=read_input_revisions(db, [symbol]).get(symbol, 0),
                 remaining=remaining, status="repaired" if readiness._ready(after) and not remaining["dates"] else "partial")
    state.pop("next_retry_at", None)
    if state.get("owner_denied"):
        state["next_action"] = "REVIEW_OWNER_PERMISSION_DENIED"
    elif state["status"] == "repaired":
        state["next_action"] = "WAIT_ORIGINAL_PRICE_MAP_PRODUCER"
    elif _next_step(remaining, state, clock()):
        state["next_action"] = "NEXT_PRODUCER_VISIT_CONTINUES_SAME_JOB"
    else:
        retries = [state["attempts"][key]["retry_at"] for key, _, _ in _steps(remaining)
                   if state.get("attempts", {}).get(key, {}).get("count", MAX_ATTEMPTS) < MAX_ATTEMPTS]
        state["next_action"] = "WAIT_RETRY" if retries else "REVIEW_CANONICAL_BLOCKERS"
        if retries:
            state["next_retry_at"] = min(retries)
    return state


def run_taiwan_historical_input_repair_job(job_id: int) -> None:
    # One bounded step finishes normally during drain. A queued task is covered
    # by JobService's explicit not_started continuation policy.
    def worker(db, progress):
        try:
            return repair_taiwan_historical_input_job_step(db, job_id)
        except Exception as exc:
            # Preserve the pre-IO attempt even if canonical post-read fails.
            db.rollback()
            state = _load(jobs.get_job(db, job_id).result_json)
            state.update(status="partial", next_action="REVIEW_CANONICAL_READBACK_FAILURE",
                         error_type=type(exc).__name__)
            if isinstance(exc, PermissionError):
                state["owner_denied"] = True
            logger.exception("Historical input canonical reread failed job=%s", job_id)
            return state
    jobs.run_tracked_job(job_id, worker)
