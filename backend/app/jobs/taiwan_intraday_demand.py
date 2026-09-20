"""Single-instrument consumer episodes on the canonical Taiwan bootstrap job.

SQLite admission is cross-connection safe. Dispatch/recovery still require one
runtime owner (the application's existing interrupted-job startup policy).
Viewer retries are command-driven: only a subsequent valid viewer heartbeat can
dispatch a due retry. Reads never dispatch and an abandoned episode does no IO.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from time import monotonic

from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import JobRun
from app.jobs import service as jobs
from app.jobs.job_types import TAIWAN_INTRADAY_BAR_BOOTSTRAP_JOB_TYPE as JOB_TYPE
from app.market.trading_calendar import TAIWAN_TZ, is_taiwan_trading_day, taiwan_market_session_phase
from app.market.tw_bar_service import TaiwanBarService
from app.market.tw_intraday_acquisition import TaiwanIntradayAcquisitionExecutor
from app.market.tw_intraday_platform import refresh_taiwan_intraday_bars
from app.market.tw_universe import list_taiwan_stock_universe
from app.market_data.integration_contracts import RequestBounds


INDEX_NAME = "uq_job_run_tw_intraday_active_demand"
PREFIX = "tw-demand:"
VERSION = "tw.intraday.demand.v1"
RETRY_DELAYS = (15, 30)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Taiwan intraday demand time must be timezone-aware")
    return value


def _decode(value: str | None) -> dict:
    try:
        parsed = json.loads(value or "{}")
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _target(request: dict) -> str:
    return (
        f"{PREFIX}TW:{request['venue']}:{request['stock_id']}:"
        f"{request['trade_date']}:tw.intraday.1m:1m"
    )


def consumer_request(job: JobRun) -> dict | None:
    """Validate the public allowlist, never expose a legacy/multi-stock job."""
    request = _decode(job.request_json)
    try:
        if (
            job.job_type != JOB_TYPE
            or request.get("contract_version") != VERSION
            or request.get("market") != "TW"
            or request.get("venue") not in {"TWSE", "TPEX"}
            or not isinstance(request.get("stock_id"), str)
            or len(request["stock_id"]) != 4
            or not request["stock_id"].isascii()
            or not request["stock_id"].isdigit()
            or request.get("dataset") != "tw.intraday.1m"
            or request.get("operation") != "tw.refresh_intraday_bars"
            or request.get("interval") != "1m"
            or request.get("consumer") not in {"viewer", "ai"}
            or request.get("max_attempts") not in {1, 3}
            or not isinstance(request.get("max_external_calls"), int)
            or not 1 <= request["max_external_calls"] <= 6
            or "symbols" in request
            or job.target != _target(request)
        ):
            return None
        date.fromisoformat(request["trade_date"])
        _aware(datetime.fromisoformat(request["expires_at"]))
    except (ValueError, TypeError, KeyError):
        return None
    return request


def _require_index(db: Session) -> None:
    if db.get_bind().dialect.name != "sqlite":
        raise RuntimeError("TW_INTRADAY_DEMAND_SCHEMA_NOT_READY")
    definition = db.execute(text(
        "SELECT sql FROM sqlite_master WHERE type='index' AND name=:name"
    ), {"name": INDEX_NAME}).scalar()
    # Check the actual constraint, not an Alembic version or same-named index.
    normalized = "".join(str(definition or "").lower().split()).replace('"', '')
    expected = (
        "createuniqueindex" + INDEX_NAME + "onjob_run(job_type,target)where"
        "job_type='tw.bootstrap_intraday_base_1m'and"
        "substr(target,1,10)='tw-demand:'andstatusin('queued','running')"
    )
    if normalized != expected:
        raise RuntimeError("TW_INTRADAY_DEMAND_SCHEMA_NOT_READY")


def _reuse_until(job: JobRun, request: dict) -> datetime:
    expires = datetime.fromisoformat(request["expires_at"])
    cooldown = _decode(job.result_json).get("retry_not_before_at")
    return max(expires, datetime.fromisoformat(cooldown)) if cooldown else expires


def _reread(db: Session, request: dict, now: datetime) -> dict:
    series = TaiwanBarService(db).read_current_session_bars(
        instrument_id=request["stock_id"], interval="1m", requested_at=now,
        bypass_snapshot_cache=True,
    )
    coverage = series.current_session_coverage
    same_date = bool(coverage and coverage.trade_date.isoformat() == request["trade_date"])
    count = coverage.snapshot_bar_count if same_date else 0
    ready = bool(same_date and count > 0 and coverage.snapshot_phase.value == "ready")
    return {
        "reread_trade_date": coverage.trade_date.isoformat() if coverage else None,
        "current_session_bar_count": count,
        "reread_ready": ready,
        "snapshot_phase": coverage.snapshot_phase.value if coverage else "missing",
        "snapshot_revision": coverage.snapshot_revision if same_date else None,
    }


def _finish(db: Session, job: JobRun, result: dict, reason: str) -> None:
    result["reason_code"] = reason
    result["next_retry_at"] = None
    if result.get("reread_ready"):
        result["status"] = "success"
        jobs.complete_job(db, job.id, result=result)
    else:
        result["status"] = "partial" if result.get("current_session_bar_count", 0) else "failed"
        jobs.fail_job(db, job.id, error_message=reason, result=result)


def _dispatch(db: Session, job: JobRun, now: datetime) -> bool:
    result = _decode(job.result_json)
    next_retry = result.get("next_retry_at")
    if next_retry and now < datetime.fromisoformat(next_retry):
        return False
    # Only one caller may dispatch this attempt, even across Sessions/processes.
    changed = db.execute(update(JobRun).where(
        JobRun.id == job.id, JobRun.status == "queued",
        JobRun.result_json == job.result_json,
    ).values(status="running", started_at=job.started_at or now, updated_at=now)).rowcount
    db.commit()
    db.refresh(job)
    if not changed:
        return False
    try:
        jobs.submit_job_task(run_consumer_demand, job.id)
    except Exception:
        _finish(db, job, result, "TW_INTRADAY_DEMAND_SUBMIT_FAILED")
    return True


def enqueue_consumer_demand(
    db: Session, *, stock_id: str, requested_at: datetime,
    consumer: str, timeout_seconds: float = 180, max_external_calls: int = 6,
    trade_date: str | None = None,
) -> tuple[JobRun | None, bool]:
    now = _aware(requested_at).astimezone(TAIWAN_TZ)
    if consumer not in {"viewer", "ai"}:
        raise ValueError("Unsupported intraday consumer")
    if timeout_seconds < 1 or max_external_calls < 1:
        raise ValueError("Intraday demand requires a positive caller budget")
    if trade_date is not None and date.fromisoformat(trade_date) != now.date():
        raise ValueError("Intraday demand supports only the requested current trading session")
    if not is_taiwan_trading_day(now.date()) or taiwan_market_session_phase(now) not in {"regular", "closing_auction"}:
        return None, False
    normalized = str(stock_id).strip()
    if not normalized:
        raise ValueError("Intraday demand requires one active ordinary stock")
    stocks = list_taiwan_stock_universe(db, stock_ids=(normalized,))
    if len(stocks) != 1:
        raise ValueError("Intraday demand requires one active ordinary stock")
    _require_index(db)
    request = {
        "contract_version": VERSION, "market": "TW", "venue": stocks[0].market.upper(),
        "stock_id": normalized, "trade_date": now.date().isoformat(),
        "dataset": "tw.intraday.1m", "interval": "1m", "consumer": consumer,
        "operation": "tw.refresh_intraday_bars",
        "expires_at": (now + timedelta(seconds=min(timeout_seconds, 180))).isoformat(),
        "max_attempts": 3 if consumer == "viewer" else 1,
        "max_external_calls": min(max_external_calls, 6 if consumer == "viewer" else 2),
    }
    target = _target(request)
    existing = db.query(JobRun).filter(JobRun.job_type == JOB_TYPE, JobRun.target == target).order_by(JobRun.id.desc()).first()
    if existing is not None:
        original = consumer_request(existing)
        if original is None:
            raise RuntimeError("TW_INTRADAY_DEMAND_INVALID_EPISODE")
        expires = _reuse_until(existing, original)
        if now < expires:
            if existing.status == "queued" and consumer == "viewer":
                _dispatch(db, existing, now)
            return existing, False
        if existing.status == "running":
            # Do not expire a running callback and admit an overlapping writer.
            # The runtime owner finishes it; startup cleanup handles interruption.
            return existing, False
        if existing.status == "queued":
            _finish(db, existing, _decode(existing.result_json), "TW_INTRADAY_DEMAND_EXPIRED")
    result = {
        "attempt_count": 0, "external_call_budget_used": 0,
        "external_call_count": 0, "bars_written_count": 0,
        "reread_count": 0, "next_retry_at": None,
    }
    try:
        job = jobs.create_job_record(db, JOB_TYPE, target=target, request=request, progress_total=request["max_attempts"])
        job.result_json = json.dumps(result)
        db.flush()
        # The winner can finish between the admission SELECT and this INSERT.
        # Under the acquired SQLite writer lock, preserve its episode cooldown
        # instead of creating another immediately successful/failed job.
        previous = db.query(JobRun).filter(
            JobRun.job_type == JOB_TYPE, JobRun.target == target, JobRun.id < job.id,
        ).order_by(JobRun.id.desc()).first()
        prior_request = consumer_request(previous) if previous is not None else None
        if prior_request is not None and now < _reuse_until(previous, prior_request):
            previous_id = previous.id
            db.rollback()
            return jobs.get_job(db, previous_id), False
        db.commit()
        db.refresh(job)
    except IntegrityError:
        db.rollback()
        winner = jobs.find_active_job_by_target(db, JOB_TYPE, target)
        if winner is None:
            # The winning worker may already have terminalized while this
            # connection rolled back its conflicting insert.
            winner = db.query(JobRun).filter(
                JobRun.job_type == JOB_TYPE, JobRun.target == target,
            ).order_by(JobRun.id.desc()).first()
        if winner is None or consumer_request(winner) is None:
            raise
        return winner, False
    _dispatch(db, job, now)
    return job, True


def run_consumer_demand(job_id: int) -> None:
    db = jobs.SessionLocal()
    try:
        job = jobs.get_job(db, job_id)
        request = consumer_request(job)
        if request is None or job.status != "running":
            return
        current_stocks = list_taiwan_stock_universe(db, stock_ids=(request["stock_id"],))
        if len(current_stocks) != 1 or current_stocks[0].market.upper() != request["venue"]:
            _finish(db, job, _decode(job.result_json), "TW_INTRADAY_DEMAND_INSTRUMENT_UNAVAILABLE")
            return
        now = _now()
        result = _decode(job.result_json)
        remaining = int((datetime.fromisoformat(request["expires_at"]) - now).total_seconds())
        calls = min(2, request["max_external_calls"] - result.get("external_call_budget_used", 0))
        if (remaining < 1 or calls < 1 or now.astimezone(TAIWAN_TZ).date().isoformat() != request["trade_date"]
                or taiwan_market_session_phase(now) not in {"regular", "closing_auction"}):
            _finish(db, job, result, "TW_INTRADAY_DEMAND_EXPIRED")
            return
        result.update(_reread(db, request, now))
        result["reread_count"] += 1
        if result["reread_ready"]:
            _finish(db, job, result, "CANONICAL_CURRENT_SESSION_READY")
            return
        result["attempt_count"] += 1
        # Reserve the maximum before IO; failure/unknown usage cannot mint quota.
        result["external_call_budget_used"] += calls
        result["next_retry_at"] = None
        job.result_json = json.dumps(result)
        job.progress_current = result["attempt_count"]
        db.commit()
        # The pre-read and queue/DB latency consume the same caller deadline.
        duration = min(40, int((datetime.fromisoformat(request["expires_at"]) - _now()).total_seconds()))
        if duration < 1:
            _finish(db, job, result, "TW_INTRADAY_DEMAND_EXPIRED")
            return
        deadline = monotonic() + duration
        reason = "CURRENT_SESSION_BASELINE_NOT_READY"
        try:
            acquired = refresh_taiwan_intraday_bars(
                db, stock_id=request["stock_id"], interval="1m", range_value="1d",
                requested_at=now,
                acquisition_bounds=RequestBounds(
                    max_provider_attempts=calls, max_external_calls=calls,
                    timeout_seconds=duration, max_candidates=3, max_rows=5000,
                ),
                acquisition=TaiwanIntradayAcquisitionExecutor(clock=_now, deadline_monotonic=deadline),
            )
            actual_calls = getattr(getattr(acquired, "acquisition", None), "external_calls", None)
            written = getattr(acquired.persistence, "observations_written", None)
            result["external_call_count"] = (
                result["external_call_count"] + actual_calls
                if result["external_call_count"] is not None and actual_calls is not None else None
            )
            result["bars_written_count"] = (
                result["bars_written_count"] + written
                if result["bars_written_count"] is not None and written is not None else None
            )
            delays = [
                int(code.split(":", 1)[1])
                for code in getattr(getattr(acquired, "acquisition", None), "limitations", ())
                if str(code).startswith("PROVIDER_RETRY_AFTER_SECONDS:")
                and str(code).split(":", 1)[1].isdigit()
            ]
            if delays:
                result["retry_not_before_at"] = (_now() + timedelta(seconds=max(delays))).isoformat()
                reason = "TW_INTRADAY_DEMAND_PROVIDER_BACKOFF"
            if acquired.persistence.attempted and not acquired.persistence.committed:
                reason = "CANONICAL_PERSISTENCE_REJECTED"
        except Exception as exc:
            db.rollback()
            result["external_call_count"] = None
            result["bars_written_count"] = None
            reason = "TW_INTRADAY_DEMAND_TIMEOUT" if isinstance(exc, TimeoutError) else "TW_INTRADAY_DEMAND_ACQUISITION_FAILED"
            jobs.logger.warning("Taiwan demand %s acquisition failed: %s", job_id, type(exc).__name__)
        now = _now()
        result.update(_reread(db, request, now))
        result["reread_count"] += 1
        if result["reread_ready"]:
            _finish(db, job, result, "CANONICAL_CURRENT_SESSION_READY")
            return
        attempt = result["attempt_count"]
        delay = RETRY_DELAYS[attempt - 1] if attempt <= len(RETRY_DELAYS) else None
        if delay is not None and result.get("retry_not_before_at"):
            delay = max(delay, (datetime.fromisoformat(result["retry_not_before_at"]) - now).total_seconds())
        if (request["consumer"] == "viewer" and attempt < request["max_attempts"]
                and result["external_call_budget_used"] < request["max_external_calls"]
                and delay is not None and now + timedelta(seconds=delay + 1) < datetime.fromisoformat(request["expires_at"])):
            result.update(reason_code=reason, next_retry_at=(now + timedelta(seconds=delay)).isoformat())
            job.status = "queued"
            job.result_json = json.dumps(result)
            job.message = "Waiting for a valid viewer heartbeat after bounded backoff."
            job.updated_at = now
            db.commit()
        else:
            _finish(db, job, result, reason)
    except Exception:
        jobs.logger.exception("Taiwan consumer demand %s failed", job_id)
        jobs.fail_job(db, job_id, error_message="TW_INTRADAY_DEMAND_FAILED")
    finally:
        db.close()
