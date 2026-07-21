from datetime import date

from sqlalchemy.orm import Session

from app.jobs.service import ProgressCallback, run_tracked_job
from app.jp_market import service as jp_market_service
from app.kr_market import service as kr_market_service
from app.market.backfill import backfill_tpex_trading_stock, backfill_twse_stock_day
from app.market.broker_branch_market_refresh import (
    refresh_taiwan_broker_branch_market,
)
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
from app.market.market_chips import refresh_market_chip_daily
from app.market.indices import refresh_market_index_summary
from app.market.shareholding_history_backfill import ensure_stock_shareholding_history
from app.market.stock_selection_refresh import refresh_selected_stock_data
from app.market.tw_derivatives import (
    TaiwanDerivativesFetchError,
    refresh_taiwan_derivatives,
)
from app.us_market import service as us_market_service
from app.watchlists.backfill_service import (
    backfill_watchlist_group_twse,
    refresh_watchlist_group_daily_prices,
)
from app.watchlists.radar_automation import run_watchlist_radar_automation


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


def run_market_chip_daily_refresh_job(
    job_id: int,
    index_ids: list[str],
    trade_date: date | None,
    include_today: bool | None,
    force: bool,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, len(index_ids) or 1, "Refreshing market chip daily.")
        return refresh_market_chip_daily(
            db=db,
            index_ids=index_ids,
            trade_date=trade_date,
            include_today=include_today,
            force=force,
            progress=progress,
        )

    run_tracked_job(job_id, worker)


def run_market_index_summary_refresh_job(job_id: int) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Refreshing Taiwan market index summary.")
        payload = refresh_market_index_summary(db=db)
        progress(1, 1, "Taiwan market index summary refreshed.")
        return {
            "status": "success",
            "as_of": payload.get("as_of"),
            "source": payload.get("source"),
            "index_count": len(payload.get("indices") or []),
        }

    run_tracked_job(job_id, worker)


def run_taiwan_derivatives_refresh_job(
    job_id: int,
    expected_trade_date: date,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 5, "Refreshing TAIFEX post-close derivatives datasets.")
        result = refresh_taiwan_derivatives(db)
        result["expected_trade_date"] = expected_trade_date
        result["is_stale"] = (
            bool(result.get("is_stale"))
            or result.get("as_of") != expected_trade_date
        )
        progress(
            int(result.get("successful_request_count") or 0),
            5,
            "TAIFEX post-close derivatives refresh completed provider requests.",
        )

        if result["is_stale"]:
            raise TaiwanDerivativesFetchError(
                "TAIFEX derivatives refresh did not reach the expected trade date: "
                f"expected={expected_trade_date.isoformat()} "
                f"actual={result.get('as_of') or 'missing'}."
            )
        if result.get("status") != "ready":
            errors = result.get("errors") or {}
            detail = "; ".join(f"{key}: {value}" for key, value in errors.items())
            raise TaiwanDerivativesFetchError(
                "TAIFEX derivatives refresh was incomplete"
                + (f": {detail}" if detail else ".")
            )

        progress(5, 5, "TAIFEX post-close derivatives data is ready.")
        return result

    run_tracked_job(job_id, worker)


def run_taiwan_broker_branch_market_refresh_job(
    job_id: int,
    trade_date: date,
    sleep_seconds: float,
    max_stocks: int,
    max_runtime_seconds: int,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Preparing Taiwan all-market broker-branch collection.")
        return refresh_taiwan_broker_branch_market(
            db,
            trade_date=trade_date,
            sleep_seconds=sleep_seconds,
            max_stocks=max_stocks,
            max_runtime_seconds=max_runtime_seconds,
            progress=progress,
            job_run_id=job_id,
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


def run_stock_selection_refresh_job(
    job_id: int,
    stock_id: str,
    include_today: bool | None,
    sleep_seconds: float,
    profile: str = "full",
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, None, "Refreshing selected stock data.")
        return refresh_selected_stock_data(
            db=db,
            stock_id=stock_id,
            include_today=include_today,
            sleep_seconds=sleep_seconds,
            profile=profile,
            progress=progress,
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


def run_watchlist_group_refresh_latest_job(
    job_id: int,
    group_id: int,
    to_date: date | None,
    lookback_days: int,
    include_today: bool,
    source_id: int | None,
    tpex_source_id: int | None,
    include_children: bool,
    enabled_only: bool,
    sleep_seconds: float,
    skip_existing_months: bool,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Refreshing watchlist group daily prices.")
        return refresh_watchlist_group_daily_prices(
            db=db,
            group_id=group_id,
            to_date=to_date,
            lookback_days=lookback_days,
            include_today=include_today,
            source_id=source_id,
            tpex_source_id=tpex_source_id,
            include_children=include_children,
            enabled_only=enabled_only,
            sleep_seconds=sleep_seconds,
            skip_existing_months=skip_existing_months,
            progress_callback=progress,
        )

    run_tracked_job(job_id, worker)


def run_watchlist_radar_auto_snapshot_job(
    job_id: int,
    group_ids: str | list[int] | None,
    modes: str,
    include_children: bool,
    enabled_only: bool,
    max_results: int,
    calculation_limit: int,
    use_intraday: bool,
    intraday_limit: int,
    evaluate_before_date: date,
    evaluate_lookback_days: int,
    save_snapshots: bool,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Running watchlist radar snapshot automation.")
        return run_watchlist_radar_automation(
            db=db,
            group_ids=group_ids,
            modes=modes,
            include_children=include_children,
            enabled_only=enabled_only,
            max_results=max_results,
            calculation_limit=calculation_limit,
            use_intraday=use_intraday,
            intraday_limit=intraday_limit,
            evaluate_before_date=evaluate_before_date,
            evaluate_lookback_days=evaluate_lookback_days,
            save_snapshots=save_snapshots,
            progress_callback=progress,
        )

    run_tracked_job(job_id, worker)


def run_us_watchlist_daily_refresh_job(
    job_id: int,
    group_id: int | None,
    include_children: bool,
    enabled_only: bool,
    outputsize: str,
    adjusted: bool,
    sleep_seconds: float,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Refreshing US watchlist daily prices.")
        return us_market_service.refresh_us_watchlist_daily_prices(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            outputsize=outputsize,
            adjusted=adjusted,
            sleep_seconds=sleep_seconds,
            progress_callback=progress,
        )

    run_tracked_job(job_id, worker)


def run_us_daily_price_quality_repair_job(
    job_id: int,
    symbol: str | None,
    dry_run: bool,
    limit: int,
    refresh: bool,
    outputsize: str,
    adjusted: bool,
    sleep_seconds: float,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Repairing US daily price quality.")
        return us_market_service.repair_us_daily_price_quality(
            db=db,
            symbol=symbol,
            dry_run=dry_run,
            limit=limit,
            refresh=refresh,
            outputsize=outputsize,
            adjusted=adjusted,
            sleep_seconds=sleep_seconds,
            progress_callback=progress,
        )

    run_tracked_job(job_id, worker)


def run_us_watchlist_resource_refresh_job(
    job_id: int,
    group_id: int | None,
    include_children: bool,
    enabled_only: bool,
    include_daily: bool,
    include_sec_facts: bool,
    include_profile: bool,
    include_actions: bool,
    outputsize: str,
    adjusted: bool,
    sleep_seconds: float,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Refreshing US watchlist resources.")
        return us_market_service.refresh_us_watchlist_resources(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            include_daily=include_daily,
            include_sec_facts=include_sec_facts,
            include_profile=include_profile,
            include_actions=include_actions,
            outputsize=outputsize,
            adjusted=adjusted,
            sleep_seconds=sleep_seconds,
            progress_callback=progress,
        )

    run_tracked_job(job_id, worker)


def run_jp_watchlist_resource_refresh_job(
    job_id: int,
    group_id: int | None,
    include_children: bool,
    enabled_only: bool,
    include_daily: bool,
    include_fundamentals: bool,
    outputsize: str,
    provider: str,
    sleep_seconds: float,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Refreshing JP watchlist resources.")
        return jp_market_service.refresh_jp_watchlist_resources(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            include_daily=include_daily,
            include_fundamentals=include_fundamentals,
            outputsize=outputsize,
            provider=provider,
            sleep_seconds=sleep_seconds,
            progress_callback=progress,
        )

    run_tracked_job(job_id, worker)


def run_kr_watchlist_resource_refresh_job(
    job_id: int,
    group_id: int | None,
    include_children: bool,
    enabled_only: bool,
    include_daily: bool,
    include_investors: bool,
    include_fundamentals: bool,
    outputsize: str,
    provider: str,
    sleep_seconds: float,
    max_symbols: int | None = None,
) -> None:
    def worker(db: Session, progress: ProgressCallback):
        progress(0, 1, "Refreshing KR watchlist resources.")
        return kr_market_service.refresh_kr_watchlist_resources(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            include_daily=include_daily,
            include_investors=include_investors,
            include_fundamentals=include_fundamentals,
            outputsize=outputsize,
            provider=provider,
            sleep_seconds=sleep_seconds,
            max_symbols=max_symbols,
            progress_callback=progress,
        )

    run_tracked_job(job_id, worker)
