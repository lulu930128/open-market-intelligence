from datetime import date

from sqlalchemy.orm import Session

from app.jobs.service import ProgressCallback, run_tracked_job
from app.market.backfill import backfill_tpex_trading_stock, backfill_twse_stock_day
from app.market.daily_metrics_backfill import (
    ensure_daily_metrics,
    ensure_latest_daily_metrics,
    ensure_stock_daily_metrics,
)
from app.market.financial_metrics_history_backfill import ensure_stock_financial_metrics_history
from app.market.fundamental_metrics_backfill import (
    ensure_fundamental_metrics,
    ensure_stock_fundamental_metrics,
)
from app.market.monthly_revenue_history_backfill import ensure_stock_monthly_revenue_history
from app.market.shareholding_history_backfill import ensure_stock_shareholding_history
from app.watchlists.backfill_service import backfill_watchlist_group_twse


def run_twse_daily_price_job(
    job_id: int,
    stock_id: str,
    start_date: date,
    end_date: date,
    source_id: int | None,
    sleep_seconds: float,
    skip_existing_months: bool,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Backfilling TWSE daily prices.")
        return backfill_twse_stock_day(
            db=db,
            stock_id=stock_id,
            start_date=start_date,
            end_date=end_date,
            source_id=source_id,
            sleep_seconds=sleep_seconds,
            skip_existing_months=skip_existing_months,
        )

    run_tracked_job(job_id, worker)


def run_tpex_daily_price_job(
    job_id: int,
    stock_id: str,
    start_date: date,
    end_date: date,
    source_id: int | None,
    sleep_seconds: float,
    skip_existing_months: bool,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Backfilling TPEx daily prices.")
        return backfill_tpex_trading_stock(
            db=db,
            stock_id=stock_id,
            start_date=start_date,
            end_date=end_date,
            source_id=source_id,
            sleep_seconds=sleep_seconds,
            skip_existing_months=skip_existing_months,
        )

    run_tracked_job(job_id, worker)


def run_market_daily_metrics_job(
    job_id: int,
    start_date: date | None,
    end_date: date | None,
    categories: list[str],
    lookback_days: int,
    include_today: bool,
    sleep_seconds: float,
    skip_existing: bool,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Backfilling market daily metrics.")

        if start_date is not None:
            return ensure_daily_metrics(
                db=db,
                start_date=start_date,
                end_date=end_date or start_date,
                categories=categories,
                sleep_seconds=sleep_seconds,
                skip_existing=skip_existing,
            )

        return ensure_latest_daily_metrics(
            db=db,
            categories=categories,
            to_date=end_date,
            lookback_days=lookback_days,
            include_today=include_today,
            sleep_seconds=sleep_seconds,
            skip_existing=skip_existing,
        )

    run_tracked_job(job_id, worker)


def run_stock_daily_metrics_history_job(
    job_id: int,
    stock_id: str,
    start_date: date,
    end_date: date,
    categories: list[str],
    sleep_seconds: float,
    skip_existing: bool,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Backfilling stock daily metrics.")
        return ensure_stock_daily_metrics(
            db=db,
            stock_id=stock_id,
            start_date=start_date,
            end_date=end_date,
            categories=categories,
            sleep_seconds=sleep_seconds,
            skip_existing=skip_existing,
        )

    run_tracked_job(job_id, worker)


def run_market_fundamental_metrics_job(
    job_id: int,
    categories: list[str],
    force: bool,
    sleep_seconds: float,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Backfilling market fundamental metrics.")
        return ensure_fundamental_metrics(
            db=db,
            categories=categories,
            force=force,
            sleep_seconds=sleep_seconds,
        )

    run_tracked_job(job_id, worker)


def run_stock_fundamental_metrics_job(
    job_id: int,
    stock_id: str,
    categories: list[str],
    force: bool,
    sleep_seconds: float,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Backfilling stock fundamental metrics.")
        return ensure_stock_fundamental_metrics(
            db=db,
            stock_id=stock_id,
            categories=categories,
            force=force,
            sleep_seconds=sleep_seconds,
        )

    run_tracked_job(job_id, worker)


def run_stock_shareholding_history_job(
    job_id: int,
    stock_id: str,
    from_date: date | None,
    to_date: date | None,
    lookback_weeks: int,
    sleep_seconds: float,
    skip_existing: bool,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Backfilling stock shareholding history.")
        return ensure_stock_shareholding_history(
            db=db,
            stock_id=stock_id,
            from_date=from_date,
            to_date=to_date,
            lookback_weeks=lookback_weeks,
            sleep_seconds=sleep_seconds,
            skip_existing=skip_existing,
        )

    run_tracked_job(job_id, worker)


def run_stock_monthly_revenue_history_job(
    job_id: int,
    stock_id: str,
    from_period: date | None,
    to_period: date | None,
    lookback_months: int,
    sleep_seconds: float,
    skip_existing: bool,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Backfilling stock monthly revenue history.")
        return ensure_stock_monthly_revenue_history(
            db=db,
            stock_id=stock_id,
            from_period=from_period,
            to_period=to_period,
            lookback_months=lookback_months,
            sleep_seconds=sleep_seconds,
            skip_existing=skip_existing,
        )

    run_tracked_job(job_id, worker)


def run_stock_financial_metrics_history_job(
    job_id: int,
    stock_id: str,
    from_fiscal_year: int | None,
    from_quarter: int | None,
    to_fiscal_year: int | None,
    to_quarter: int | None,
    lookback_quarters: int,
    sleep_seconds: float,
    skip_existing: bool,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Backfilling stock financial metrics history.")
        return ensure_stock_financial_metrics_history(
            db=db,
            stock_id=stock_id,
            from_fiscal_year=from_fiscal_year,
            from_quarter=from_quarter,
            to_fiscal_year=to_fiscal_year,
            to_quarter=to_quarter,
            lookback_quarters=lookback_quarters,
            sleep_seconds=sleep_seconds,
            skip_existing=skip_existing,
        )

    run_tracked_job(job_id, worker)


def run_watchlist_group_backfill_job(
    job_id: int,
    group_id: int,
    start_date: date,
    end_date: date,
    source_id: int | None,
    tpex_source_id: int | None,
    include_children: bool,
    enabled_only: bool,
    sleep_seconds: float,
    skip_existing_months: bool,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Backfilling watchlist group daily prices.")
        return backfill_watchlist_group_twse(
            db=db,
            group_id=group_id,
            start_date=start_date,
            end_date=end_date,
            source_id=source_id,
            tpex_source_id=tpex_source_id,
            include_children=include_children,
            enabled_only=enabled_only,
            sleep_seconds=sleep_seconds,
            skip_existing_months=skip_existing_months,
            progress_callback=progress,
        )

    run_tracked_job(job_id, worker)
