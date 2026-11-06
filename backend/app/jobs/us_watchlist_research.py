"""Bounded cache-only US research commands and read-only job receipts."""
from datetime import date, datetime
import json
from time import monotonic
from threading import Lock

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import JobRun, utc_now
from app.config import settings
from app.jobs import service as jobs
from app.research.stock_nomination import StockNomination, create_nominations
from app.research.trade_journal_http_service import JournalHttpError
from app.research.trade_proposal import content_hash
from app.us_market.trading_calendar import expected_us_daily_price_date
from app.us_market.research_schedule import postclose_schedule
from app.us_market.watchlist_store import list_us_watchlist_symbols

JOB_TYPE = "us_watchlist_research"
MAX_SYMBOLS_PER_SLICE = 25
MAX_SLICE_SECONDS = 30
_scan_command_lock = Lock()


class ScanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resume_job_id: int | None = Field(default=None, gt=0)


def read_latest(db):
    job = db.query(JobRun).filter(JobRun.job_type == JOB_TYPE).order_by(JobRun.id.desc()).first()
    receipt = jobs.serialize_job(job) if job else None
    schedule = postclose_schedule(utc_now())
    schedule.update(enabled=settings.enable_us_watchlist_research_scheduler,
                    state="waiting_window" if not schedule["in_window"] else "ready")
    if receipt:
        if receipt["status"] in jobs.ACTIVE_STATUSES:
            schedule["state"] = "running"
        elif receipt["request"].get("basis_trade_date") == schedule["basis_trade_date"]:
            if receipt["status"] != "success":
                schedule["state"] = "requires_attention"
            elif (receipt.get("result") or {}).get("next_cursor") is None:
                schedule["state"] = "completed_for_session"
            if schedule["state"] in {"requires_attention", "completed_for_session"}:
                schedule["next_check_at"] = schedule["following_window_at"]
    if not schedule["enabled"]:
        schedule.update(state="disabled", next_check_at=None)
    return {"scope": "enabled_us_watchlist", "schedule": schedule, "job": receipt}


def enqueue_scan(db, request: ScanRequest):
    with _scan_command_lock:
        return _enqueue_scan(db, request)


def _enqueue_scan(db, request):
    # One active scan, regardless of repeated clicks or a scheduler tick.
    active = db.query(JobRun).filter(JobRun.job_type == JOB_TYPE,
        JobRun.status.in_(jobs.ACTIVE_STATUSES)).order_by(JobRun.id.desc()).first()
    if active:
        return jobs.serialize_job(active)
    now = utc_now()
    if request.resume_job_id is not None:
        previous = db.get(JobRun, request.resume_job_id)
        if previous is None or previous.job_type != JOB_TYPE or previous.status != "success":
            raise JournalHttpError(409, "US_SCAN_NOT_RESUMABLE", "A completed scan receipt is required.")
        payload, result = json.loads(previous.request_json), json.loads(previous.result_json or "{}")
        cursor = result.get("next_cursor")
        if type(cursor) is not int or not 0 <= cursor < len(payload["symbols"]):
            raise JournalHttpError(409, "US_SCAN_ALREADY_COMPLETE", "The frozen watchlist scan is complete.")
        if payload["basis_trade_date"] != expected_us_daily_price_date(now=now).isoformat():
            raise JournalHttpError(409, "US_SCAN_SESSION_CHANGED", "Start a new scan for the latest completed session.")
        payload = {**payload, "cursor": cursor}
    else:
        symbols = list_us_watchlist_symbols(db, enabled_only=True)
        if len(symbols) > 5000:
            raise JournalHttpError(422, "US_WATCHLIST_SCAN_LIMIT", "At most 5000 enabled watchlist symbols per scan.")
        payload = {"symbols": symbols, "membership_hash": content_hash(symbols), "cursor": 0,
                   "basis_trade_date": expected_us_daily_price_date(now=now).isoformat(),
                   "requested_at": now.isoformat(), "scope": "enabled_us_watchlist"}
    # Deduplication binds the frozen membership/session/cursor, not wall time.
    key = {k: payload[k] for k in ("membership_hash", "basis_trade_date", "cursor")}
    job, _ = jobs.enqueue_job(db, job_type=JOB_TYPE, target=content_hash(key), request=payload,
        progress_total=len(payload["symbols"]) or 1, task=run_scan, task_args=(payload,),
        message="US watchlist technical research; cache only, long and short.", dedupe_active=True)
    return jobs.serialize_job(job)


def scan_slice(db, payload, progress):
    """Each symbol commits independently; resume only from a recorded cursor.

    A failed/interrupted slice can be restarted safely because automatic Journal
    IDs are deterministic. Empty membership stays empty; no universe fallback.
    """
    symbols, cursor = payload["symbols"], payload["cursor"]
    started = monotonic()
    rows = []
    # JobService refresh starts a read transaction; end that owner-owned read.
    db.rollback()
    stop = min(len(symbols), cursor + MAX_SYMBOLS_PER_SLICE)
    while cursor < stop and (not rows or monotonic() - started < MAX_SLICE_SECONDS):
        result = create_nominations(db, StockNomination(market="US", stock_ids=(symbols[cursor],),
            as_of_trade_date=date.fromisoformat(payload["basis_trade_date"]),
            requested_at=datetime.fromisoformat(payload["requested_at"]), nomination_origin="OMI_SCREEN",
            direction="both", quantity=1), automatic=True,
            discovery_context={"scope": "enabled_us_watchlist", "membership_hash": payload["membership_hash"],
                               "membership_count": len(symbols), "full_market": False})
        for row in result["scenarios"]:
            proposal = row.pop("proposal")
            rows.append({**row, "creation_id": proposal["proposal"]["creation_id"] if proposal else None})
        cursor += 1
        progress(current=cursor, total=len(symbols), message=f"US watchlist: {cursor}/{len(symbols)}")
        db.rollback()  # End JobService's post-progress refresh transaction.
    return {"status": "partial" if cursor < len(symbols) else "completed", "scope": "enabled_us_watchlist",
        "basis_trade_date": payload["basis_trade_date"], "membership_hash": payload["membership_hash"],
        "total_symbols": len(symbols), "processed_symbols": cursor, "slice_start": payload["cursor"],
        "next_cursor": cursor if cursor < len(symbols) else None,
        "created": sum(bool(r["creation_id"]) and not r["deduplicated"] for r in rows),
        "data_blocked": sum(r["status"] == "DATA_BLOCKED" for r in rows), "scenarios": rows,
        "quality_status": "partial" if any(r["status"] == "DATA_BLOCKED" for r in rows) else "complete",
        "message": "Continue the frozen watchlist to finish coverage." if cursor < len(symbols) else "Watchlist scan finished.",
        "execution_ready": False, "provider_calls": 0}


def run_scan(job_id, payload):
    jobs.run_tracked_job(job_id, lambda db, progress: scan_slice(db, payload, progress))


def run_scheduled_scan():
    """Post-close scheduler: finish frozen membership, then wait for a new session.

    Errors require an explicit retry; a timer does not replay an unknown outcome.
    """
    if not settings.enable_us_watchlist_research_scheduler:
        return
    window = postclose_schedule(utc_now())
    if not window["in_window"]:
        return
    from app.db.session import SessionLocal
    with SessionLocal() as db:
        latest = read_latest(db)["job"]
        expected = window["basis_trade_date"]
        if latest and latest["request"]["basis_trade_date"] == expected:
            if latest["status"] != "success" or (latest.get("result") or {}).get("next_cursor") is None:
                return
            return enqueue_scan(db, ScanRequest(resume_job_id=latest["id"]))
        return enqueue_scan(db, ScanRequest())
