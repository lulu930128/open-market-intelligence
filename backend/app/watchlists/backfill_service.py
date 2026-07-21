from collections.abc import Callable
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import MarketDailyPrice, StockMaster
from app.market.backfill import backfill_tpex_trading_stock, backfill_twse_stock_day
from app.market.calendar_status import expected_taiwan_trade_date
from app.market.taiwan_rules import TAIWAN_DATASET_DAILY_PRICE
from app.market.trading_calendar import (
    is_taiwan_trading_day,
    previous_taiwan_trading_day,
)
from app.watchlists import service as watchlist_service


ProgressCallback = Callable[[int, int, str], None]
CancellationCheck = Callable[[], bool]


def _get_result_field(result, field_name: str, default=None):
    if isinstance(result, dict):
        return result.get(field_name, default)

    return getattr(result, field_name, default)


def _normalize_status(status: str | None) -> str:
    if not status:
        return "unknown"

    return status.lower()


def _get_stock_market(db: Session, stock_id: str) -> str | None:
    stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()

    if stock is None:
        return None

    return stock.market.upper()


def _get_latest_trade_date(db: Session, stock_id: str) -> date | None:
    return (
        db.query(func.max(MarketDailyPrice.trade_date))
        .filter(MarketDailyPrice.stock_id == stock_id)
        .scalar()
    )


def _trading_day_count(start_date: date, end_date: date) -> int:
    if end_date < start_date:
        return 0

    count = 0
    current = start_date

    while current <= end_date:
        if is_taiwan_trading_day(current):
            count += 1

        current += timedelta(days=1)

    return count


def _existing_daily_price_count(
    db: Session,
    stock_id: str,
    start_date: date,
    end_date: date,
) -> int:
    return (
        db.query(func.count(MarketDailyPrice.id))
        .filter(MarketDailyPrice.stock_id == stock_id)
        .filter(MarketDailyPrice.trade_date >= start_date)
        .filter(MarketDailyPrice.trade_date <= end_date)
        .scalar()
        or 0
    )


def _has_complete_daily_price_range(
    db: Session,
    stock_id: str,
    start_date: date,
    end_date: date,
) -> bool:
    expected_count = _trading_day_count(start_date, end_date)

    if expected_count <= 0:
        return True

    return _existing_daily_price_count(
        db=db,
        stock_id=stock_id,
        start_date=start_date,
        end_date=end_date,
    ) >= expected_count


def _expected_latest_trade_date(to_date: date | None, include_today: bool) -> date:
    if to_date is not None:
        return previous_taiwan_trading_day(to_date, include_value=True)

    expected_date = expected_taiwan_trade_date(
        TAIWAN_DATASET_DAILY_PRICE,
        include_today=True if include_today else None,
    )
    if expected_date is None:
        return previous_taiwan_trading_day(date.today(), include_value=False)

    return expected_date


def _list_unique_watchlist_items(
    db: Session,
    group_id: int,
    include_children: bool,
    enabled_only: bool,
) -> list[dict]:
    watchlist_service.get_group(db=db, group_id=group_id)

    items = watchlist_service.list_items(
        db=db,
        group_id=group_id,
        enabled=True if enabled_only else None,
        include_children=include_children,
        limit=1000,
        offset=0,
    )

    seen_stock_ids: set[str] = set()
    unique_items: list[dict] = []

    for item in items:
        stock_id = item["stock_id"]

        if stock_id in seen_stock_ids:
            continue

        seen_stock_ids.add(stock_id)
        unique_items.append(item)

    return unique_items


def _backfill_stock_by_market(
    db: Session,
    stock_id: str,
    market: str | None,
    start_date: date,
    end_date: date,
    twse_source_id: int | None,
    tpex_source_id: int | None,
    sleep_seconds: float,
    skip_existing_months: bool,
) -> dict:
    if market == "TWSE":
        return backfill_twse_stock_day(
            db=db,
            stock_id=stock_id,
            start_date=start_date,
            end_date=end_date,
            source_id=twse_source_id,
            sleep_seconds=sleep_seconds,
            skip_existing_months=skip_existing_months,
        )

    if market == "TPEX":
        return backfill_tpex_trading_stock(
            db=db,
            stock_id=stock_id,
            start_date=start_date,
            end_date=end_date,
            source_id=tpex_source_id,
            sleep_seconds=sleep_seconds,
            skip_existing_months=skip_existing_months,
        )

    return {
        "stock_id": stock_id,
        "stock_name": None,
        "source_id": 0,
        "start_date": start_date,
        "end_date": end_date,
        "requested_month_count": 0,
        "fetched_month_count": 0,
        "skipped_existing_month_count": 0,
        "parsed_count": 0,
        "inserted_count": 0,
        "skipped_count": 0,
        "status": "skipped",
        "message": f"History backfill is not configured for market='{market}'.",
        "months": [],
    }


def backfill_watchlist_group_twse(
    db: Session,
    group_id: int,
    start_date: date,
    end_date: date,
    source_id: int | None = None,
    tpex_source_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    sleep_seconds: float = 0.8,
    skip_existing_months: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    """
    Backfill all enabled watchlist items under a group.

    This function intentionally calls the existing single-stock TWSE/TPEx backfill
    pipelines, so the raw/result/quality/clean-table traceability remains consistent.
    """
    unique_items = _list_unique_watchlist_items(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
    )

    results: list[dict] = []

    success_count = 0
    warning_count = 0
    error_count = 0
    skipped_count = 0
    total_count = len(unique_items)

    if progress_callback is not None:
        progress_callback(0, total_count, "Watchlist backfill started.")

    for index, item in enumerate(unique_items, start=1):
        stock_id = item["stock_id"]
        stock_name = item.get("stock_name")
        market = _get_stock_market(db=db, stock_id=stock_id)

        try:
            result = _backfill_stock_by_market(
                db=db,
                stock_id=stock_id,
                market=market,
                start_date=start_date,
                end_date=end_date,
                twse_source_id=source_id,
                tpex_source_id=tpex_source_id,
                sleep_seconds=sleep_seconds,
                skip_existing_months=skip_existing_months,
            )

            status = _normalize_status(_get_result_field(result, "status"))

            parsed_count = int(_get_result_field(result, "parsed_count", 0) or 0)
            inserted_count = int(_get_result_field(result, "inserted_count", 0) or 0)
            skipped = int(_get_result_field(result, "skipped_count", 0) or 0)

            if status == "success":
                success_count += 1
            elif status in {"warning", "partial_success"}:
                warning_count += 1
            elif status == "skipped":
                skipped_count += 1
            else:
                error_count += 1

            results.append(
                {
                    "stock_id": stock_id,
                    "stock_name": stock_name,
                    "market": market,
                    "status": status,
                    "parsed_count": parsed_count,
                    "inserted_count": inserted_count,
                    "skipped_count": skipped,
                    "message": _get_result_field(result, "message"),
                    "error_message": _get_result_field(result, "error_message"),
                }
            )

            if progress_callback is not None:
                progress_callback(
                    index,
                    total_count,
                    f"Backfilled {stock_id} ({index}/{total_count}).",
                )

        except Exception as exc:
            error_count += 1

            results.append(
                {
                    "stock_id": stock_id,
                    "stock_name": stock_name,
                    "market": market,
                    "status": "error",
                    "parsed_count": 0,
                    "inserted_count": 0,
                    "skipped_count": 0,
                    "message": None,
                    "error_message": str(exc),
                }
            )

            if progress_callback is not None:
                progress_callback(
                    index,
                    total_count,
                    f"Backfill failed for {stock_id} ({index}/{total_count}).",
                )

    return {
        "group_id": group_id,
        "include_children": include_children,
        "start_date": start_date,
        "end_date": end_date,
        "requested_stock_count": total_count,
        "success_count": success_count,
        "warning_count": warning_count,
        "error_count": error_count,
        "skipped_count": skipped_count,
        "results": results,
    }


def refresh_watchlist_group_daily_prices(
    db: Session,
    group_id: int,
    to_date: date | None = None,
    lookback_days: int = 14,
    include_today: bool = False,
    source_id: int | None = None,
    tpex_source_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    sleep_seconds: float = 0.8,
    skip_existing_months: bool = True,
    progress_callback: ProgressCallback | None = None,
    should_cancel: CancellationCheck | None = None,
) -> dict:
    target_date = _expected_latest_trade_date(to_date=to_date, include_today=include_today)
    unique_items = _list_unique_watchlist_items(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
    )

    results: list[dict] = []
    current_count = 0
    success_count = 0
    warning_count = 0
    error_count = 0
    skipped_count = 0
    total_count = len(unique_items)

    if progress_callback is not None:
        progress_callback(0, total_count, "Watchlist freshness check started.")

    cancelled = False
    for index, item in enumerate(unique_items, start=1):
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        stock_id = item["stock_id"]
        stock_name = item.get("stock_name")
        market = _get_stock_market(db=db, stock_id=stock_id)
        latest_trade_date = _get_latest_trade_date(db=db, stock_id=stock_id)
        current_month_start = date(target_date.year, target_date.month, 1)

        if (
            latest_trade_date is not None
            and latest_trade_date >= target_date
            and _has_complete_daily_price_range(
                db=db,
                stock_id=stock_id,
                start_date=current_month_start,
                end_date=target_date,
            )
        ):
            current_count += 1
            results.append(
                {
                    "stock_id": stock_id,
                    "stock_name": stock_name,
                    "market": market,
                    "latest_trade_date": latest_trade_date,
                    "target_date": target_date,
                    "start_date": None,
                    "status": "current",
                    "parsed_count": 0,
                    "inserted_count": 0,
                    "skipped_count": 0,
                    "message": "Daily prices are already current.",
                    "error_message": None,
                }
            )

            if progress_callback is not None:
                progress_callback(index, total_count, f"Checked {stock_id} ({index}/{total_count}).")

            continue

        if latest_trade_date is not None and latest_trade_date < target_date:
            start_date = latest_trade_date + timedelta(days=1)
        elif latest_trade_date is not None:
            start_date = current_month_start
        else:
            start_date = target_date - timedelta(days=lookback_days)

        if start_date > target_date:
            current_count += 1
            results.append(
                {
                    "stock_id": stock_id,
                    "stock_name": stock_name,
                    "market": market,
                    "latest_trade_date": latest_trade_date,
                    "target_date": target_date,
                    "start_date": start_date,
                    "status": "current",
                    "parsed_count": 0,
                    "inserted_count": 0,
                    "skipped_count": 0,
                    "message": "No daily price gap was found.",
                    "error_message": None,
                }
            )

            if progress_callback is not None:
                progress_callback(index, total_count, f"Checked {stock_id} ({index}/{total_count}).")

            continue

        try:
            result = _backfill_stock_by_market(
                db=db,
                stock_id=stock_id,
                market=market,
                start_date=start_date,
                end_date=target_date,
                twse_source_id=source_id,
                tpex_source_id=tpex_source_id,
                sleep_seconds=sleep_seconds,
                skip_existing_months=skip_existing_months,
            )

            status = _normalize_status(_get_result_field(result, "status"))
            parsed_count = int(_get_result_field(result, "parsed_count", 0) or 0)
            inserted_count = int(_get_result_field(result, "inserted_count", 0) or 0)
            skipped = int(_get_result_field(result, "skipped_count", 0) or 0)
            refreshed_latest_trade_date = _get_latest_trade_date(
                db=db,
                stock_id=stock_id,
            )

            if status == "success":
                success_count += 1
            elif status in {"warning", "partial_success"}:
                warning_count += 1
            elif status == "skipped":
                skipped_count += 1
            else:
                error_count += 1

            results.append(
                {
                    "stock_id": stock_id,
                    "stock_name": stock_name,
                    "market": market,
                    "latest_trade_date": refreshed_latest_trade_date,
                    "target_date": target_date,
                    "start_date": start_date,
                    "status": status,
                    "parsed_count": parsed_count,
                    "inserted_count": inserted_count,
                    "skipped_count": skipped,
                    "message": _get_result_field(result, "message"),
                    "error_message": _get_result_field(result, "error_message"),
                }
            )

            if progress_callback is not None:
                progress_callback(index, total_count, f"Refreshed {stock_id} ({index}/{total_count}).")

        except Exception as exc:
            error_count += 1
            results.append(
                {
                    "stock_id": stock_id,
                    "stock_name": stock_name,
                    "market": market,
                    "latest_trade_date": latest_trade_date,
                    "target_date": target_date,
                    "start_date": start_date,
                    "status": "error",
                    "parsed_count": 0,
                    "inserted_count": 0,
                    "skipped_count": 0,
                    "message": None,
                    "error_message": str(exc),
                }
            )

            if progress_callback is not None:
                progress_callback(index, total_count, f"Refresh failed for {stock_id} ({index}/{total_count}).")

        if should_cancel is not None and should_cancel():
            cancelled = True
            break

    completed_count = current_count + success_count + warning_count + skipped_count
    if cancelled:
        result_status = "timeout"
    elif error_count > 0:
        result_status = "partial_success" if completed_count > 0 else "error"
    elif warning_count > 0:
        result_status = "partial_success"
    else:
        result_status = "success"

    return {
        "status": result_status,
        "message": (
            f"Target {target_date}: current {current_count}/{total_count}, "
            f"refreshed {success_count}, warnings {warning_count}, errors {error_count}."
        ),
        "group_id": group_id,
        "include_children": include_children,
        "enabled_only": enabled_only,
        "target_date": target_date,
        "lookback_days": lookback_days,
        "requested_stock_count": total_count,
        "current_count": current_count,
        "success_count": success_count,
        "warning_count": warning_count,
        "error_count": error_count,
        "skipped_count": skipped_count,
        "cancelled": cancelled,
        "results": results,
    }
