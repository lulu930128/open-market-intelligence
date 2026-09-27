"""Single-instrument consumer episodes on the canonical Taiwan bootstrap job.

SQLite admission is cross-connection safe. Dispatch/recovery still require one
runtime owner (the application's existing interrupted-job startup policy).
Viewer retries are command-driven: only a subsequent valid viewer heartbeat can
dispatch a due retry. Reads never dispatch and an abandoned episode does no IO.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone
from time import monotonic

from sqlalchemy import func, text, update
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import JobRun, StockMaster, TaiwanIntradaySchedulerState
from app.jobs import service as jobs
from app.jobs.job_types import TAIWAN_INTRADAY_BAR_BOOTSTRAP_JOB_TYPE as JOB_TYPE
from app.market.trading_calendar import TAIWAN_TZ, is_taiwan_trading_day, taiwan_market_session_phase, taiwan_presentation_session
from app.market.tw_bar_service import TaiwanBarService
from app.market.tw_intraday_acquisition import TaiwanIntradayAcquisitionExecutor
from app.market.tw_intraday_platform import refresh_taiwan_intraday_bars
from app.market.tw_instrument import resolve_taiwan_instrument
from app.market_data.contracts import InstrumentType
from app.market_data.policies import RealtimePolicy
from app.market_data.integration_contracts import RequestBounds


INDEX_NAME = "uq_job_run_tw_intraday_active_demand"
PREFIX = "tw-demand:"
VERSION = "tw.intraday.demand.v1"
RETRY_DELAYS = (15, 30)
ORIGINS = {"viewer", "ai", "scheduler", "close_tail", "completed_session_repair", "completed_session", "operator", "front"}
COMPLETED_BACKOFF_KEY = "tw-completed-materialization:backoff"


def completed_lane_backoff(db: Session) -> datetime | None:
    """Durable lane throttle, never acquired or changed by a read."""
    row = db.get(TaiwanIntradaySchedulerState, COMPLETED_BACKOFF_KEY, populate_existing=True)
    value = _decode(row.state_json).get("retry_not_before_at") if row else None
    return datetime.fromisoformat(value) if value else None


def _record_completed_backoff(db: Session, until: datetime) -> None:
    # UTC ISO strings make the monotonic MAX update safe across worker Sessions.
    until = until.astimezone(timezone.utc)
    payload = json.dumps({"retry_not_before_at": until.isoformat()})
    statement = insert(TaiwanIntradaySchedulerState).values(key=COMPLETED_BACKOFF_KEY,
        state_json=payload, revision=0, updated_at=_now())
    db.execute(statement.on_conflict_do_update(index_elements=["key"],
        set_={"state_json": payload, "revision": TaiwanIntradaySchedulerState.revision + 1,
              "updated_at": _now()},
        where=func.json_extract(TaiwanIntradaySchedulerState.state_json, "$.retry_not_before_at") < until.isoformat()))
    db.commit()


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


def materialization_request(job: JobRun) -> dict | None:
    """Validate one canonical series identity, including legacy v1 episodes."""
    request = _decode(job.request_json)
    try:
        if (
            job.job_type != JOB_TYPE
            or request.get("contract_version") != VERSION
            or request.get("market") != "TW"
            or request.get("venue") not in {"TWSE", "TPEX"}
            or not isinstance(request.get("stock_id"), str)
            or not 4 <= len(request["stock_id"]) <= 12
            or not request["stock_id"].isascii()
            or not request["stock_id"].isalnum()
            or request.get("dataset") != "tw.intraday.1m"
            or request.get("operation") != "tw.refresh_intraday_bars"
            or request.get("interval") != "1m"
            or request.get("consumer") not in ORIGINS
            or request.get("mode", "current_session") not in {"current_session", "completed_session", "completed_session_repair"}
            or request.get("realtime_policy", "prefer_live") not in {"prefer_live", "require_live"}
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


def consumer_request(job: JobRun) -> dict | None:
    # Origin does not change public access to a validated single-instrument job.
    # refresh_status owns the explicit redacted outward field allowlist.
    return materialization_request(job)


def _admit_instrument(db: Session, stock_id: str):
    instrument = resolve_taiwan_instrument(db, stock_id)
    if instrument.instrument_type not in {InstrumentType.STOCK, InstrumentType.ETF}:
        raise ValueError("Intraday demand requires one active ordinary stock or ETF")
    master = db.query(StockMaster).filter(StockMaster.stock_id == instrument.symbol).first()
    if master is None or not master.is_active:
        raise ValueError("Intraday demand requires one active ordinary stock or ETF")
    return instrument


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
    target = date.fromisoformat(request["trade_date"])
    if target != taiwan_presentation_session(now)["trade_date"]:
        series = TaiwanBarService(db).read_bars(
            instrument_id=request["stock_id"], interval="1m",
            from_time=datetime.combine(target, time(9), tzinfo=TAIWAN_TZ),
            to_time=datetime.combine(target, time(13, 30), tzinfo=TAIWAN_TZ),
            requested_at=now,
        )
        manifest = next((item for item in series.session_resolution if item.trade_date == target), None)
        count = sum(bar.start_at.astimezone(TAIWAN_TZ).date() == target for bar in series.bars)
        ready = bool(manifest and count and manifest.coverage_status.value == "ready")
        return {"reread_trade_date": target.isoformat(), "current_session_bar_count": count,
                "reread_ready": ready, "snapshot_phase": "ready" if ready else "degraded",
                "coverage_status": manifest.coverage_status.value if manifest else "missing",
                "snapshot_revision": series.identity.series_revision}
    series = TaiwanBarService(db).read_current_session_bars(
        instrument_id=request["stock_id"], interval="1m", requested_at=now,
        bypass_snapshot_cache=True,
    )
    coverage = series.current_session_coverage
    same_date = bool(coverage and coverage.trade_date.isoformat() == request["trade_date"])
    count = coverage.snapshot_bar_count if same_date else 0
    ready = bool(same_date and count > 0 and coverage.snapshot_phase.value == "ready"
                 and series.history.requested_coverage_satisfied)
    if request.get("realtime_policy") == "require_live":
        # Validate policy through the canonical resolver; never equate full bars with live.
        from app.market.intraday_repository import TaiwanIntradayBarRepository
        from app.market.tw_intraday_platform import build_taiwan_intraday_requirement
        from app.market_data.gateway import MarketDataGateway
        requirement = build_taiwan_intraday_requirement(
            instrument=resolve_taiwan_instrument(db, request["stock_id"]), interval="1m",
            range_value="1d", policy=RealtimePolicy.REQUIRE_LIVE, requested_at=now, acquiring=False)
        resolved = MarketDataGateway().resolve_bars(requirement, reader=TaiwanIntradayBarRepository(db))
        ready = ready and resolved.resolved.health.status.value in {"selected", "fallback"}
    return {
        "reread_trade_date": coverage.trade_date.isoformat() if coverage else None,
        "current_session_bar_count": count,
        "reread_ready": ready,
        "snapshot_phase": coverage.snapshot_phase.value if coverage else "missing",
        "snapshot_revision": coverage.snapshot_revision if same_date else None,
    }


def _finish(db: Session, job: JobRun, result: dict, reason: str) -> None:
    # Admission may strengthen a running goal. Compare the evaluated request at
    # the write boundary; a late goal must never inherit an older success.
    for _ in range(5):
        expected_request = job.request_json
        result["reason_code"] = reason
        result["next_retry_at"] = None
        ready = bool(result.get("reread_ready"))
        result["status"] = "success" if ready else "partial" if result.get("current_session_bar_count", 0) else "failed"
        changed = db.execute(update(JobRun).where(
            JobRun.id == job.id, JobRun.status.in_(("queued", "running")),
            JobRun.request_json == expected_request,
        ).values(status="success" if ready else "error", result_json=json.dumps(result),
                 error_message=None if ready else reason, ended_at=_now(), updated_at=_now(),
                 result_summary_json=jobs._to_result_summary_json(result)),
            execution_options={"synchronize_session": False}).rowcount
        db.commit()
        db.refresh(job)
        if changed or job.status not in {"queued", "running"}:
            return
        request = materialization_request(job)
        if request is None:
            raise RuntimeError("TW_INTRADAY_DEMAND_INVALID_EPISODE")
        result.update(_reread(db, request, _now()))
        result["reread_count"] = result.get("reread_count", 0) + 1
    # Continually changing requests cannot manufacture a success. Preserve the
    # remaining budget and let the command dispatcher resume the same episode.
    job.status = "queued"
    result.update(reread_ready=False, next_retry_at=_now().isoformat())
    job.result_json = json.dumps(result)
    db.commit()


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
        request = materialization_request(job) or {}
        background = request.get("consumer") in {"scheduler", "close_tail", "completed_session_repair"}
        jobs.submit_job_task(run_consumer_demand, job.id,
            execution_lane=("market_completed" if request.get("consumer") == "completed_session"
                            else "market_background" if background else "market_interactive"))
    except Exception:
        _finish(db, job, result, "TW_INTRADAY_DEMAND_SUBMIT_FAILED")
    return True


def enqueue_intraday_materialization_demand(
    db: Session, *, stock_id: str, requested_at: datetime,
    consumer: str, timeout_seconds: float = 180, max_external_calls: int = 6,
    trade_date: str | None = None,
    policy: str = "prefer_live",
    desired_coverage_end_at: datetime | None = None,
    _admission_retry: int = 0,
) -> tuple[JobRun | None, bool]:
    now = _aware(requested_at).astimezone(TAIWAN_TZ)
    if consumer not in ORIGINS:
        raise ValueError("Unsupported intraday consumer")
    if timeout_seconds < 1 or max_external_calls < 1:
        raise ValueError("Intraday demand requires a positive caller budget")
    target_date = date.fromisoformat(trade_date) if trade_date else taiwan_presentation_session(now)["trade_date"]
    if target_date > now.date() or not is_taiwan_trading_day(target_date):
        raise ValueError("TW_INTRADAY_INVALID_TRADE_DATE")
    session_end = datetime.combine(target_date, time(13, 30), tzinfo=TAIWAN_TZ)
    completed = now >= session_end
    if consumer == "completed_session" and not completed:
        raise ValueError("TW_INTRADAY_SESSION_NOT_COMPLETED")
    if not completed and taiwan_market_session_phase(now) not in {"regular", "closing_auction"}:
        return None, False
    if policy not in {"prefer_live", "require_live"}:
        raise ValueError("Unsupported intraday policy")
    if completed and policy == "require_live":
        raise ValueError("TW_INTRADAY_COMPLETED_SESSION_NOT_LIVE")
    coverage_end = min(session_end, now.replace(second=0, microsecond=0))
    if desired_coverage_end_at is not None:
        coverage_end = min(coverage_end, _aware(desired_coverage_end_at).astimezone(TAIWAN_TZ))
    if coverage_end <= datetime.combine(target_date, time(9), tzinfo=TAIWAN_TZ):
        return None, False
    normalized = str(stock_id).strip()
    if not normalized:
        raise ValueError("Intraday demand requires one active ordinary stock")
    try:
        instrument = _admit_instrument(db, normalized)
    except ValueError as exc:
        raise ValueError("Intraday demand requires one active ordinary stock or ETF") from exc
    _require_index(db)
    request = {
        "contract_version": VERSION, "market": "TW", "venue": instrument.venue,
        "instrument_type": instrument.instrument_type.value,
        "stock_id": instrument.symbol, "trade_date": target_date.isoformat(),
        "mode": ("completed_session" if consumer == "completed_session"
                 else "completed_session_repair" if completed else "current_session"),
        "desired_coverage_end_at": coverage_end.isoformat(), "realtime_policy": policy,
        "postcondition_version": "tw.materialization.coverage.v1",
        "dataset": "tw.intraday.1m", "interval": "1m", "consumer": consumer,
        "operation": "tw.refresh_intraday_bars",
        "expires_at": (now + timedelta(seconds=min(timeout_seconds, 180))).isoformat(),
        "max_attempts": 3 if consumer in {"viewer", "scheduler", "close_tail", "completed_session_repair"} else 1,
        "max_external_calls": min(max_external_calls, 6 if consumer in {"viewer", "scheduler", "close_tail", "completed_session_repair"} else 2),
    }
    target = _target(request)
    evidence = _reread(db, request, now)
    backoff_until = None
    existing = db.query(JobRun).filter(JobRun.job_type == JOB_TYPE, JobRun.target == target).order_by(JobRun.id.desc()).first()
    if existing is not None:
        original = consumer_request(existing)
        if original is None:
            raise RuntimeError("TW_INTRADAY_DEMAND_INVALID_EPISODE")
        expires = _reuse_until(existing, original)
        previous_backoff = _decode(existing.result_json).get("retry_not_before_at")
        if previous_backoff and now < datetime.fromisoformat(previous_backoff):
            backoff_until = previous_backoff
        if existing.status in {"queued", "running"}:
            # Strengthen only unsatisfied goals. Never extend the owner's budget/deadline.
            # CAS includes the request so a worker terminalizing cannot lose a new goal.
            for _ in range(5):
                original = materialization_request(existing)
                old_end = datetime.fromisoformat(original.get("desired_coverage_end_at", coverage_end.isoformat()))
                merged = {**original, "desired_coverage_end_at": max(old_end, coverage_end).isoformat()}
                if policy == "require_live":
                    merged["realtime_policy"] = policy
                if completed:
                    merged["mode"] = "completed_session_repair"
                changed = db.execute(update(JobRun).where(JobRun.id == existing.id,
                    JobRun.status.in_(("queued", "running")), JobRun.request_json == existing.request_json
                ).values(request_json=json.dumps(merged)), execution_options={"synchronize_session": False}).rowcount
                db.commit()
                db.refresh(existing)
                if changed or existing.status not in {"queued", "running"}:
                    break
            else:
                raise RuntimeError("TW_INTRADAY_DEMAND_GOAL_MERGE_CONTENTION")
            if existing.status not in {"queued", "running"}:
                # A terminalization winner cannot satisfy an unmerged goal.
                if existing.status == "success" and evidence["reread_ready"]:
                    return existing, False
                expires = now
        elif existing.status == "success":
            # Evidence reuse is distinct from acquisition admission/backoff.
            if evidence["reread_ready"]:
                return existing, False
            expires = now
        elif evidence["reread_ready"]:
            # A stream can satisfy evidence during acquisition backoff. Record a
            # new zero-IO completion without granting another provider budget.
            expires = now
        if now < expires:
            if existing.status == "queued" and consumer != "ai":
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
        "provider_failure_count": 0, "provider_backoff_count": 0,
        "reread_count": 0, "next_retry_at": None,
    }
    result.update(evidence)
    result["reread_count"] = 1
    if backoff_until:
        result["retry_not_before_at"] = backoff_until
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
        if prior_request is not None and (
            (previous.status == "success" and evidence["reread_ready"])
            or (previous.status != "success" and not evidence["reread_ready"] and now < _reuse_until(previous, prior_request))
        ):
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
        # The concurrent winner may carry an earlier/weaker goal or may have
        # terminalized. Re-enter the bounded admission check to merge/reread;
        # returning it directly could falsely satisfy this caller's new goal.
        if _admission_retry >= 4:
            raise RuntimeError("TW_INTRADAY_DEMAND_ADMISSION_CONTENTION")
        return enqueue_intraday_materialization_demand(
            db, stock_id=stock_id, requested_at=requested_at, consumer=consumer,
            timeout_seconds=timeout_seconds, max_external_calls=max_external_calls,
            trade_date=trade_date, policy=policy,
            desired_coverage_end_at=desired_coverage_end_at,
            _admission_retry=_admission_retry + 1,
        )
    if evidence["reread_ready"]:
        _finish(db, job, result, "CANONICAL_COVERAGE_READY")
    elif backoff_until:
        _finish(db, job, result, "TW_INTRADAY_DEMAND_PROVIDER_BACKOFF")
    else:
        _dispatch(db, job, now)
    return job, True


def enqueue_consumer_demand(db: Session, *, stock_id: str, requested_at: datetime,
                            consumer: str, timeout_seconds: float = 180,
                            max_external_calls: int = 6, trade_date: str | None = None,
                            policy: str = "prefer_live") -> tuple[JobRun | None, bool]:
    """Consumer command facade; historical requests share the same durable owner."""
    if consumer not in {"viewer", "ai"}:
        raise ValueError("Unsupported intraday consumer")
    return enqueue_intraday_materialization_demand(db, stock_id=stock_id,
        requested_at=requested_at, consumer=consumer, timeout_seconds=timeout_seconds,
        max_external_calls=max_external_calls, trade_date=trade_date, policy=policy)


def run_consumer_demand(job_id: int) -> None:
    db = jobs.SessionLocal()
    result = {}
    try:
        job = jobs.get_job(db, job_id)
        request = consumer_request(job)
        if request is None or job.status != "running":
            return
        instrument = _admit_instrument(db, request["stock_id"])
        if instrument.venue != request["venue"]:
            _finish(db, job, _decode(job.result_json), "TW_INTRADAY_DEMAND_INSTRUMENT_UNAVAILABLE")
            return
        now = _now()
        result = _decode(job.result_json)
        remaining = int((datetime.fromisoformat(request["expires_at"]) - now).total_seconds())
        calls = min(2, request["max_external_calls"] - result.get("external_call_budget_used", 0))
        if remaining < 1 or calls < 1:
            _finish(db, job, result, "TW_INTRADAY_DEMAND_EXPIRED")
            return
        result.update(_reread(db, request, now))
        result["reread_count"] += 1
        if result["reread_ready"]:
            _finish(db, job, result, "CANONICAL_CURRENT_SESSION_READY")
            return
        if request["consumer"] in {"completed_session", "completed_session_repair"}:
            backoff = completed_lane_backoff(db)
            if backoff and now < backoff:
                result["retry_not_before_at"] = backoff.isoformat()
                _finish(db, job, result, "TW_INTRADAY_DEMAND_PROVIDER_BACKOFF")
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
                target_trade_date=date.fromisoformat(request["trade_date"]),
                desired_coverage_end_at=(datetime.fromisoformat(request["desired_coverage_end_at"])
                    if request.get("desired_coverage_end_at") else None),
                policy=RealtimePolicy(request.get("realtime_policy", "prefer_live")),
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
            acquisition = getattr(acquired, "acquisition", None)
            if "PROVIDER_REQUEST_OR_PARSE_FAILED" in getattr(acquisition, "limitations", ()):
                result["provider_failure_count"] = result.get("provider_failure_count", 0) + 1
            if delays:
                result["provider_backoff_count"] = result.get("provider_backoff_count", 0) + 1
                result["retry_not_before_at"] = (_now() + timedelta(seconds=max(delays))).isoformat()
                if request["consumer"] in {"completed_session", "completed_session_repair"}:
                    _record_completed_backoff(db, datetime.fromisoformat(result["retry_not_before_at"]))
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
        db.refresh(job)
        request = materialization_request(job) or request
        result.update(_reread(db, request, now))
        result["reread_count"] += 1
        if result["reread_ready"]:
            _finish(db, job, result, "CANONICAL_CURRENT_SESSION_READY")
            return
        attempt = result["attempt_count"]
        delay = RETRY_DELAYS[attempt - 1] if attempt <= len(RETRY_DELAYS) else None
        if delay is not None and result.get("retry_not_before_at"):
            delay = max(delay, (datetime.fromisoformat(result["retry_not_before_at"]) - now).total_seconds())
        if (request["consumer"] in {"viewer", "scheduler", "close_tail", "completed_session_repair"} and attempt < request["max_attempts"]
                and result["external_call_budget_used"] < request["max_external_calls"]
                and delay is not None and now + timedelta(seconds=delay + 1) < datetime.fromisoformat(request["expires_at"])):
            result.update(reason_code=reason, next_retry_at=(now + timedelta(seconds=delay)).isoformat())
            job.status = "queued"
            job.result_json = json.dumps(result)
            job.message = "Waiting for command dispatch after bounded backoff."
            job.updated_at = now
            db.commit()
        else:
            _finish(db, job, result, reason)
    except Exception:
        jobs.logger.exception("Taiwan consumer demand %s failed", job_id)
        # Keep consumed quota/provider evidence even if the canonical reread
        # itself fails. A generic failure must not erase the episode ledger.
        result.update(reread_ready=False, reason_code="TW_INTRADAY_DEMAND_FAILED")
        jobs.fail_job(db, job_id, error_message="TW_INTRADAY_DEMAND_FAILED", result=result)
    finally:
        db.close()


def dispatch_due_materializations(db: Session, *, requested_at: datetime, limit: int = 3) -> int:
    """Scheduler command only: bounded recovery for background-owned retries."""
    dispatched = 0
    candidates = db.query(JobRun).filter(JobRun.job_type == JOB_TYPE,
        JobRun.target.like(PREFIX + "%"), JobRun.status == "queued").order_by(JobRun.id).limit(64).all()
    for job in candidates:
        request = materialization_request(job)
        if request is None:
            continue
        if requested_at >= datetime.fromisoformat(request["expires_at"]):
            _finish(db, job, _decode(job.result_json), "TW_INTRADAY_DEMAND_EXPIRED")
        elif request["consumer"] in {"scheduler", "close_tail", "completed_session_repair", "completed_session"}:
            dispatched += int(_dispatch(db, job, requested_at))
            if dispatched >= limit:
                break
    return dispatched
