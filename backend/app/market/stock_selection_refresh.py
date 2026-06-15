from collections.abc import Callable
from datetime import date

from sqlalchemy.orm import Session

from app.db.models import StockMaster
from app.market.broker_branch import ensure_broker_branch_daily
from app.market.backfill import backfill_tpex_trading_stock, backfill_twse_stock_day
from app.market.daily_metrics_backfill import ensure_stock_daily_metrics
from app.market.financial_metrics_history_backfill import ensure_stock_financial_metrics_history
from app.market.monthly_revenue_history_backfill import ensure_stock_monthly_revenue_history
from app.market.shareholding_history_backfill import ensure_stock_shareholding_history
from app.market.calendar_status import expected_taiwan_trade_date
from app.market.taiwan_rules import (
    TAIWAN_DATASET_BROKER_BRANCH,
    TAIWAN_DATASET_DAILY_PRICE,
    TAIWAN_DATASET_INSTITUTIONAL_TRADE,
    TAIWAN_DATASET_MARGIN_TRADING,
    TAIWAN_REFRESH_BROKER_BRANCH,
    TAIWAN_REFRESH_DAILY_PRICE,
    TAIWAN_REFRESH_INSTITUTIONAL_TRADE,
    TAIWAN_REFRESH_MARGIN_TRADING,
    TAIWAN_REFRESH_STEP_LABELS,
    normalize_refresh_profile,
    refresh_profile_steps,
)


ProgressCallback = Callable[[int | None, int | None, str | None], None]
def expected_daily_price_date(*, include_today: bool | None = None) -> date | None:
    return expected_taiwan_trade_date(
        TAIWAN_DATASET_DAILY_PRICE,
        include_today=include_today,
    )


def expected_institutional_trade_date(*, include_today: bool | None = None) -> date | None:
    return expected_taiwan_trade_date(
        TAIWAN_DATASET_INSTITUTIONAL_TRADE,
        include_today=include_today,
    )


def expected_margin_trade_date(*, include_today: bool | None = None) -> date | None:
    return expected_taiwan_trade_date(
        TAIWAN_DATASET_MARGIN_TRADING,
        include_today=include_today,
    )


def expected_broker_branch_date(*, include_today: bool | None = None) -> date | None:
    return expected_taiwan_trade_date(
        TAIWAN_DATASET_BROKER_BRANCH,
        include_today=include_today,
    )


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


def _get_stock_market(db: Session, stock_id: str) -> str | None:
    stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()

    if stock is None:
        return None

    return stock.market.upper()


def _expected_refresh_trade_date(
    step_key: str,
    *,
    include_today: bool | None,
) -> date:
    expected_by_step = {
        TAIWAN_REFRESH_DAILY_PRICE: expected_daily_price_date,
        TAIWAN_REFRESH_INSTITUTIONAL_TRADE: expected_institutional_trade_date,
        TAIWAN_REFRESH_MARGIN_TRADING: expected_margin_trade_date,
        TAIWAN_REFRESH_BROKER_BRANCH: expected_broker_branch_date,
    }
    expected_date = expected_by_step[step_key](include_today=include_today)
    if expected_date is None:
        raise ValueError(f"No expected trade date is configured for refresh step '{step_key}'.")

    return expected_date


def _ensure_current_month_daily_prices(
    *,
    db: Session,
    stock_id: str,
    target_date: date,
    sleep_seconds: float,
) -> dict:
    start_date = date(target_date.year, target_date.month, 1)
    market = _get_stock_market(db=db, stock_id=stock_id)

    if market == "TWSE":
        return backfill_twse_stock_day(
            db=db,
            stock_id=stock_id,
            start_date=start_date,
            end_date=target_date,
            sleep_seconds=sleep_seconds,
            skip_existing_months=True,
        )

    if market == "TPEX":
        return backfill_tpex_trading_stock(
            db=db,
            stock_id=stock_id,
            start_date=start_date,
            end_date=target_date,
            sleep_seconds=sleep_seconds,
            skip_existing_months=True,
        )

    return {
        "status": "skipped",
        "stock_id": stock_id,
        "start_date": start_date,
        "end_date": target_date,
        "message": f"Daily price refresh is not configured for market='{market}'.",
    }


def refresh_selected_stock_data(
    *,
    db: Session,
    stock_id: str,
    include_today: bool | None = None,
    sleep_seconds: float = 0.05,
    profile: str | None = "full",
    progress: ProgressCallback | None = None,
) -> dict:
    refresh_profile = normalize_refresh_profile(profile)
    requested_steps = refresh_profile_steps(refresh_profile)
    step_total = len(requested_steps)
    results: dict[str, dict] = {}
    daily_price_date = _expected_refresh_trade_date(
        TAIWAN_REFRESH_DAILY_PRICE,
        include_today=include_today,
    )
    institutional_trade_date = _expected_refresh_trade_date(
        TAIWAN_REFRESH_INSTITUTIONAL_TRADE,
        include_today=include_today,
    )
    margin_trade_date = _expected_refresh_trade_date(
        TAIWAN_REFRESH_MARGIN_TRADING,
        include_today=include_today,
    )
    branch_trade_date = _expected_refresh_trade_date(
        TAIWAN_REFRESH_BROKER_BRANCH,
        include_today=include_today,
    )

    refresh_steps: dict[str, Callable[[], dict]] = {
        "daily_price": (
            lambda: _ensure_current_month_daily_prices(
                db=db,
                stock_id=stock_id,
                target_date=daily_price_date,
                sleep_seconds=sleep_seconds,
            )
        ),
        "institutional_trade": (
            lambda: ensure_stock_daily_metrics(
                db=db,
                stock_id=stock_id,
                start_date=institutional_trade_date,
                end_date=institutional_trade_date,
                categories=["institutional_trade"],
                sleep_seconds=sleep_seconds,
                skip_existing=True,
            )
        ),
        "margin_trading": (
            lambda: ensure_stock_daily_metrics(
                db=db,
                stock_id=stock_id,
                start_date=margin_trade_date,
                end_date=margin_trade_date,
                categories=["margin_trading"],
                sleep_seconds=sleep_seconds,
                skip_existing=True,
            )
        ),
        "broker_branch": (
            lambda: {
                "status": "success",
                "rows": len(
                    ensure_broker_branch_daily(
                        db=db,
                        stock_id=stock_id,
                        trade_date=branch_trade_date,
                    )
                ),
            }
        ),
        "shareholding_distribution": (
            lambda: ensure_stock_shareholding_history(
                db=db,
                stock_id=stock_id,
                lookback_weeks=52,
                sleep_seconds=sleep_seconds,
                skip_existing=True,
            )
        ),
        "monthly_revenue": (
            lambda: ensure_stock_monthly_revenue_history(
                db=db,
                stock_id=stock_id,
                lookback_months=120,
                sleep_seconds=sleep_seconds,
                skip_existing=True,
            )
        ),
        "financial_metrics": (
            lambda: ensure_stock_financial_metrics_history(
                db=db,
                stock_id=stock_id,
                lookback_quarters=40,
                sleep_seconds=sleep_seconds,
                skip_existing=True,
            )
        ),
    }

    for step_index, step_key in enumerate(requested_steps, start=1):
        label = TAIWAN_REFRESH_STEP_LABELS[step_key]
        action = refresh_steps[step_key]
        _run_refresh_step(
            key=step_key,
            label=label,
            step_index=step_index,
            step_total=step_total,
            progress=progress,
            results=results,
            action=action,
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
        "profile": refresh_profile,
        "daily_price_date": daily_price_date,
        "institutional_trade_date": institutional_trade_date,
        "margin_trade_date": margin_trade_date,
        "broker_branch_date": branch_trade_date,
        "requested_count": step_total,
        "refreshed_count": refreshed_count,
        "skipped_count": skipped_count,
        "error_count": error_count,
        "results": results,
    }


__all__ = ["refresh_selected_stock_data"]
