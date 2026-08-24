from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.db.models import JobRun
from app.jobs import service as job_service
from app.jobs.job_types import MARKET_EOD_COVERAGE_RECONCILE_JOB_TYPE
from app.market_data.eod_coverage import normalize_coverage_market, reconcile_eod_coverage


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
        )
        if result.get("status") == "failed":
            raise job_service.JobExecutionError(
                str(result.get("message") or "EOD coverage reconciliation failed."),
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
        "max_symbols": max_symbols,
        "max_runtime_seconds": max_runtime_seconds,
        "sleep_seconds": sleep_seconds,
        "max_consecutive_errors": max_consecutive_errors,
        "error_backoff_seconds": error_backoff_seconds,
    }
    return job_service.enqueue_job(
        db=db,
        job_type=MARKET_EOD_COVERAGE_RECONCILE_JOB_TYPE,
        target=target,
        request=request,
        progress_total=2 if normalized == "TW" else max(max_symbols, 1),
        message=message,
        task=run_eod_coverage_reconcile_job,
        task_args=(
            normalized,
            repair,
            expected_trade_date,
            max_symbols,
            max_runtime_seconds,
            sleep_seconds,
            max_consecutive_errors,
            error_backoff_seconds,
        ),
    )


__all__ = [
    "enqueue_eod_coverage_reconcile",
    "run_eod_coverage_reconcile_job",
]
