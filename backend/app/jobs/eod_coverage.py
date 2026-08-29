from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.db.models import JobRun
from app.jobs import service as job_service
from app.jobs.job_types import MARKET_EOD_COVERAGE_RECONCILE_JOB_TYPE
from app.market.daily_ohlcv_platform import refresh_taiwan_official_daily_venue
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
) -> None:
    def worker(db: Session, progress: job_service.ProgressCallback):
        result = reconcile_eod_coverage(
            db,
            market=market,
            repair=repair,
            expected_trade_date=expected_trade_date,
            job_id=job_id,
            max_symbols=max_symbols,
            max_runtime_seconds=max_runtime_seconds,
            sleep_seconds=sleep_seconds,
            max_consecutive_errors=max_consecutive_errors,
            error_backoff_seconds=error_backoff_seconds,
            progress_callback=progress,
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
        if result.get("postcondition_met") is not True:
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
    expected_trade_date: date | None = None,
    max_symbols: int = 250,
    max_runtime_seconds: int = 600,
    sleep_seconds: float = 1.0,
    max_consecutive_errors: int = 5,
    error_backoff_seconds: int = 1800,
    message: str = "Queued full-market EOD coverage reconciliation.",
) -> tuple[JobRun, bool]:
    normalized = normalize_coverage_market(market)
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
        ),
    )


__all__ = [
    "enqueue_eod_coverage_reconcile",
    "run_eod_coverage_reconcile_job",
]
