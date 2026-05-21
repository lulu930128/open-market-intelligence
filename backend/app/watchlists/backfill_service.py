from datetime import date

from sqlalchemy.orm import Session

from app.db.models import StockMaster
from app.market.backfill import backfill_tpex_trading_stock, backfill_twse_stock_day
from app.watchlists import service as watchlist_service


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


def _backfill_stock_by_market(
    db: Session,
    stock_id: str,
    market: str | None,
    start_date: date,
    end_date: date,
    twse_source_id: int,
    tpex_source_id: int,
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
    source_id: int = 1,
    tpex_source_id: int = 6,
    include_children: bool = True,
    enabled_only: bool = True,
    sleep_seconds: float = 0.8,
    skip_existing_months: bool = True,
) -> dict:
    """
    Backfill all enabled watchlist items under a group.

    This function intentionally calls the existing single-stock TWSE/TPEx backfill
    pipelines, so the raw/result/quality/clean-table traceability remains consistent.
    """
    watchlist_service.get_group(db=db, group_id=group_id)

    items = watchlist_service.list_items(
        db=db,
        group_id=group_id,
        enabled=True if enabled_only else None,
        include_children=include_children,
        limit=1000,
        offset=0,
    )

    # Deduplicate stock_id while keeping first appearance order.
    seen_stock_ids: set[str] = set()
    unique_items: list[dict] = []

    for item in items:
        stock_id = item["stock_id"]

        if stock_id in seen_stock_ids:
            continue

        seen_stock_ids.add(stock_id)
        unique_items.append(item)

    results: list[dict] = []

    success_count = 0
    warning_count = 0
    error_count = 0
    skipped_count = 0

    for item in unique_items:
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

    return {
        "group_id": group_id,
        "include_children": include_children,
        "start_date": start_date,
        "end_date": end_date,
        "requested_stock_count": len(unique_items),
        "success_count": success_count,
        "warning_count": warning_count,
        "error_count": error_count,
        "skipped_count": skipped_count,
        "results": results,
    }
