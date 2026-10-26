from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
import json

from sqlalchemy.orm import Session
from sqlalchemy import func

from app.db.models import JobRun
from app.config import settings
from app.jobs.market_refresh_priority import active_market_refresh_priorities
from app.jobs import service as job_service
from app.jobs.owner_continuation import owner_continuation_arguments
from app.jobs.job_types import MARKET_EOD_COVERAGE_RECONCILE_JOB_TYPE
from app.market.daily_ohlcv_platform import refresh_taiwan_official_daily_venue, qualify_taiwan_eod_universe
from app.market_data.eod_coverage import (
    eod_reconcile_bounds,
    normalize_coverage_market,
    reconcile_eod_coverage,
)
from app.us_market.full_market_eod import US_FULL_MARKET_EOD_LIFECYCLE


def run_eod_coverage_reconcile_job(
    job_id: int,
    market: str,
    repair: bool,
    expected_trade_date: date | None,
    max_symbols: int,
    max_runtime_seconds: int,
    sleep_seconds: float,
    max_consecutive_errors: int,
    error_backoff_seconds: int,
    grouped_daily: bool = False,
) -> None:
    def worker(db: Session, progress: job_service.ProgressCallback):
        if grouped_daily:
            if market.strip().upper() != "US" or not repair:
                raise ValueError("grouped daily requires US repair command")
            from app.us_market.trading_calendar import US_MARKET_TIMEZONE, previous_us_trading_day
            now = datetime.now(timezone.utc)
            trade_date = expected_trade_date or previous_us_trading_day(now.astimezone(US_MARKET_TIMEZONE).date(), include_value=False)
            # The existing job ledger supplies cross-job cooldown; no new quota store.
            recent = (db.query(JobRun).filter(JobRun.job_type == MARKET_EOD_COVERAGE_RECONCILE_JOB_TYPE,
                      JobRun.target == "US:full_market_stock_universe", JobRun.id != job_id,
                      JobRun.started_at >= now - timedelta(minutes=30)).all())
            if any(json.loads(job.request_json or "{}").get("grouped_daily") for job in recent):
                raise job_service.JobExecutionError("US grouped EOD cooldown; no provider request admitted.",
                    result={"status": "blocked", "reason": "GROUPED_EOD_COOLDOWN", "external_call_count": 0})
            # A prior attempt on this date is not authorization to replay after
            # a 403 or an unknown outcome. Reconciliation is an operator gate.
            previous = (db.query(JobRun).filter(JobRun.job_type == MARKET_EOD_COVERAGE_RECONCILE_JOB_TYPE,
                        JobRun.target == "US:full_market_stock_universe", JobRun.id != job_id,
                        JobRun.started_at.isnot(None),
                        func.json_extract(JobRun.request_json, "$.grouped_daily") == 1).order_by(JobRun.id.desc()).all())
            for job in previous:
                request = json.loads(job.request_json or "{}")
                if not request.get("grouped_daily"):
                    continue
                result = json.loads(job.result_json or "{}")
                # A configuration/date/cooldown rejection made no provider call.
                if result.get("external_call_count") == 0:
                    continue
                from app.us_market.daily_price_repository import _aware_utc
                prior_date = request.get("expected_trade_date") or previous_us_trading_day(
                    _aware_utc(job.started_at).astimezone(US_MARKET_TIMEZONE).date(), include_value=False).isoformat()
                if prior_date == trade_date.isoformat():
                    raise job_service.JobExecutionError("US grouped date already attempted; reconcile before retry.",
                        result={"status": "blocked", "reason": "GROUPED_DATE_ALREADY_ATTEMPTED",
                                "prior_job_id": job.id, "external_call_count": 0})
            acquisition = US_FULL_MARKET_EOD_LIFECYCLE.refresh_grouped_daily(db, trade_date=trade_date, now=now)
            snapshot = US_FULL_MARKET_EOD_LIFECYCLE.publish_distribution(db, now=now)
            result = {"market": "US", "trade_date": trade_date.isoformat(), **acquisition, "snapshot": snapshot}
            if acquisition["status"] != "complete":
                raise job_service.JobExecutionError("US grouped EOD incomplete; inspect receipt and coverage.", result=result)
            return result
        result = reconcile_eod_coverage(
            db,
            market=market,
            repair=repair,
            taiwan_daily_qualifier=qualify_taiwan_eod_universe,
            expected_trade_date=expected_trade_date,
            job_id=job_id,
            max_symbols=max_symbols,
            max_runtime_seconds=max_runtime_seconds,
            sleep_seconds=sleep_seconds,
            max_consecutive_errors=max_consecutive_errors,
            error_backoff_seconds=error_backoff_seconds,
            progress_callback=progress,
            **(owner_continuation_arguments(db, "us_eod_symbols") if market.strip().upper() == "US" else {}),
            priority_symbols=(
                lambda: active_market_refresh_priorities(db, market=market)
            ) if settings.enable_market_refresh_priority else None,
            taiwan_venue_refresher=(
                refresh_taiwan_official_daily_venue
                if market.strip().upper() == "TW"
                else None
            ),
            us_port=(
                US_FULL_MARKET_EOD_LIFECYCLE
                if market.strip().upper() == "US"
                else None
            ),
        )
        if market.strip().upper() == "US":
            result["distribution_snapshot"] = US_FULL_MARKET_EOD_LIFECYCLE.publish_distribution(db)
        if result.get("postcondition_met") is not True and not (
            result.get("continuation_required") is True
            and result.get("status") == "partial"
            and result.get("error_count") == 0
        ):
            raise job_service.JobExecutionError(
                (
                    "EOD coverage postcondition not met: "
                    f"market={result.get('market')} "
                    f"current={result.get('current_count', 0)}/"
                    f"{result.get('universe_count', 0)} "
                    f"partial={result.get('partial_count', 0)} "
                    f"stale={result.get('stale_count', 0)} "
                    f"missing={result.get('missing_count', 0)}."
                ),
                result=result,
            )
        return result

    job_service.run_tracked_job(job_id, worker)


def enqueue_eod_coverage_reconcile(
    db: Session,
    *,
    market: str,
    repair: bool = True,
    grouped_daily: bool = False,
    expected_trade_date: date | None = None,
    max_symbols: int = 250,
    max_runtime_seconds: int = 600,
    sleep_seconds: float = 1.0,
    max_consecutive_errors: int = 5,
    error_backoff_seconds: int = 1800,
    message: str = "Queued full-market EOD coverage reconciliation.",
) -> tuple[JobRun, bool]:
    normalized = normalize_coverage_market(market)
    if grouped_daily and (normalized != "US" or not repair):
        raise ValueError("grouped daily requires US repair command")
    bounds = eod_reconcile_bounds(normalized)
    effective_max_symbols = min(
        max(int(max_symbols), 1),
        bounds.max_symbols,
        bounds.max_calls,
    )
    effective_max_runtime_seconds = min(
        max(int(max_runtime_seconds), 1),
        bounds.timeout_seconds,
    )
    target = f"{normalized}:full_market_stock_universe"
    active = job_service.find_active_job_by_target(
        db,
        MARKET_EOD_COVERAGE_RECONCILE_JOB_TYPE,
        target,
    )
    if active is not None:
        return active, False
    request = {
        "market": normalized,
        "repair": repair,
        "grouped_daily": grouped_daily,
        "expected_trade_date": expected_trade_date,
        "max_symbols": effective_max_symbols,
        "max_runtime_seconds": effective_max_runtime_seconds,
        "sleep_seconds": sleep_seconds,
        "max_consecutive_errors": max_consecutive_errors,
        "error_backoff_seconds": error_backoff_seconds,
    }
    return job_service.enqueue_job(
        db=db,
        job_type=MARKET_EOD_COVERAGE_RECONCILE_JOB_TYPE,
        target=target,
        request=request,
        progress_total=effective_max_symbols,
        message=message,
        task=run_eod_coverage_reconcile_job,
        task_args=(
            normalized,
            repair,
            expected_trade_date,
            effective_max_symbols,
            effective_max_runtime_seconds,
            sleep_seconds,
            max_consecutive_errors,
            error_backoff_seconds,
            grouped_daily,
        ),
    )


__all__ = [
    "enqueue_eod_coverage_reconcile",
    "run_eod_coverage_reconcile_job",
]
