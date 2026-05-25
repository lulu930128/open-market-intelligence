from collections.abc import Callable
from datetime import time

from sqlalchemy.orm import Session

from app.market.broker_branch import ensure_broker_branch_daily
from app.market.daily_metrics_backfill import ensure_stock_daily_metrics
from app.market.financial_metrics_history_backfill import ensure_stock_financial_metrics_history
from app.market.monthly_revenue_history_backfill import ensure_stock_monthly_revenue_history
from app.market.shareholding_history_backfill import ensure_stock_shareholding_history
from app.market.trading_calendar import latest_released_trading_day


ProgressCallback = Callable[[int | None, int | None, str | None], None]

DAILY_METRIC_RELEASE_TIMES = {
    "institutional_trade": time(18, 10),
    "margin_trading": time(21, 10),
}


def _step_status(result: dict) -> str:
    status = result.get("status")
    return status if isinstance(status, str) else "success"


def _run_refresh_step(
    *,
    key: str,
    label: str,
    step_index: int,
    step_total: int,
    progress: ProgressCallback | None,
    results: dict[str, dict],
    action: Callable[[], dict],
) -> None:
    if progress is not None:
        progress(step_index - 1, step_total, f"{label}更新中。")

    try:
        result = action()
        status = _step_status(result)
        results[key] = {
            "label": label,
            "status": status,
            "result": result,
            "error_message": None,
        }
    except Exception as exc:
        results[key] = {
            "label": label,
            "status": "error",
            "result": None,
            "error_message": str(exc),
        }

    if progress is not None:
        progress(step_index, step_total, f"{label}更新完成。")


def refresh_selected_stock_data(
    *,
    db: Session,
    stock_id: str,
    include_today: bool | None = None,
    sleep_seconds: float = 0.05,
    progress: ProgressCallback | None = None,
) -> dict:
    step_total = 6
    results: dict[str, dict] = {}
    institutional_trade_date = latest_released_trading_day(
        release_time=DAILY_METRIC_RELEASE_TIMES["institutional_trade"],
        include_today=include_today,
    )
    margin_trade_date = latest_released_trading_day(
        release_time=DAILY_METRIC_RELEASE_TIMES["margin_trading"],
        include_today=include_today,
    )

    _run_refresh_step(
        key="institutional_trade",
        label="法人",
        step_index=1,
        step_total=step_total,
        progress=progress,
        results=results,
        action=lambda: ensure_stock_daily_metrics(
            db=db,
            stock_id=stock_id,
            start_date=institutional_trade_date,
            end_date=institutional_trade_date,
            categories=["institutional_trade"],
            sleep_seconds=sleep_seconds,
            skip_existing=True,
        ),
    )
    _run_refresh_step(
        key="margin_trading",
        label="融資融券",
        step_index=2,
        step_total=step_total,
        progress=progress,
        results=results,
        action=lambda: ensure_stock_daily_metrics(
            db=db,
            stock_id=stock_id,
            start_date=margin_trade_date,
            end_date=margin_trade_date,
            categories=["margin_trading"],
            sleep_seconds=sleep_seconds,
            skip_existing=True,
        ),
    )
    _run_refresh_step(
        key="broker_branch",
        label="分點",
        step_index=3,
        step_total=step_total,
        progress=progress,
        results=results,
        action=lambda: {
            "status": "success",
            "rows": len(ensure_broker_branch_daily(db=db, stock_id=stock_id)),
        },
    )
    _run_refresh_step(
        key="shareholding_distribution",
        label="股權分散",
        step_index=4,
        step_total=step_total,
        progress=progress,
        results=results,
        action=lambda: ensure_stock_shareholding_history(
            db=db,
            stock_id=stock_id,
            lookback_weeks=52,
            sleep_seconds=sleep_seconds,
            skip_existing=True,
        ),
    )
    _run_refresh_step(
        key="monthly_revenue",
        label="營收",
        step_index=5,
        step_total=step_total,
        progress=progress,
        results=results,
        action=lambda: ensure_stock_monthly_revenue_history(
            db=db,
            stock_id=stock_id,
            lookback_months=120,
            sleep_seconds=sleep_seconds,
            skip_existing=True,
        ),
    )
    _run_refresh_step(
        key="financial_metrics",
        label="盈餘",
        step_index=6,
        step_total=step_total,
        progress=progress,
        results=results,
        action=lambda: ensure_stock_financial_metrics_history(
            db=db,
            stock_id=stock_id,
            lookback_quarters=40,
            sleep_seconds=sleep_seconds,
            skip_existing=True,
        ),
    )

    error_count = sum(1 for result in results.values() if result["status"] == "error")
    skipped_count = sum(1 for result in results.values() if result["status"] == "skipped")
    refreshed_count = len(results) - error_count - skipped_count

    if error_count == len(results):
        status = "error"
    elif error_count:
        status = "partial_success"
    elif refreshed_count == 0:
        status = "skipped"
    else:
        status = "success"

    return {
        "status": status,
        "message": "Selected stock data refresh completed.",
        "stock_id": stock_id,
        "include_today": include_today,
        "institutional_trade_date": institutional_trade_date,
        "margin_trade_date": margin_trade_date,
        "requested_count": step_total,
        "refreshed_count": refreshed_count,
        "skipped_count": skipped_count,
        "error_count": error_count,
        "results": results,
    }


__all__ = ["refresh_selected_stock_data"]
