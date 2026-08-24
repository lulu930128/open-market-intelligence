from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
import time

from sqlalchemy.orm import Session

from app.db.models import USStockMaster, USWatchlistItem
from app.us_market import watchlist_metrics, watchlist_store
from app.us_market.errors import USMarketConfigurationError
from app.us_market.sources import normalize_us_symbol


ProgressCallback = Callable[[int | None, int | None, str | None], None]


@dataclass(frozen=True)
class USWatchlistWorkflowDependencies:
    expected_daily_price_date: Callable[[], date]
    resolved_daily_batch_loader: Callable[..., dict[str, dict]]
    intraday_overlay_loader: Callable[..., dict | None]
    refresh_daily_prices: Callable[..., dict]
    ensure_stock: Callable[..., USStockMaster]
    refresh_sec_facts: Callable[..., dict]
    refresh_company_profile: Callable[..., dict]
    refresh_corporate_actions: Callable[..., dict]


_close_value = watchlist_metrics._close_value
_latest_distinct_us_daily_rows = watchlist_metrics._latest_distinct_us_daily_rows
_parse_us_row_trade_date = watchlist_metrics._parse_us_row_trade_date
_us_row_trade_date = watchlist_metrics._us_row_trade_date
get_us_watchlist_group = watchlist_store.get_us_watchlist_group
_get_us_descendant_group_ids = watchlist_store._get_us_descendant_group_ids
list_us_watchlist_symbols = watchlist_store.list_us_watchlist_symbols


def _finite_float(value) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and parsed not in {float("inf"), float("-inf")} else None


def _resolved_daily_bars(payload: dict) -> list[dict]:
    bars = payload.get("bars")
    if not isinstance(bars, list):
        return []
    return [bar for bar in bars if isinstance(bar, dict)]

def _us_ranking_freshness(
    rows: list[dict],
    requested_symbol_count: int,
    *,
    dependencies: USWatchlistWorkflowDependencies,
) -> dict:
    target_trade_date = dependencies.expected_daily_price_date()
    row_dates = [_us_row_trade_date(row) for row in rows]
    latest_trade_date = max(
        (row_date for row_date in row_dates if row_date is not None),
        default=None,
    )
    current_symbol_count = sum(
        1
        for row_date in row_dates
        if row_date is not None and row_date >= target_trade_date
    )
    stale_symbol_count = max(requested_symbol_count - current_symbol_count, 0)

    return {
        "trade_date": latest_trade_date,
        "target_trade_date": target_trade_date,
        "is_current": requested_symbol_count == 0 or stale_symbol_count == 0,
        "current_symbol_count": current_symbol_count,
        "stale_symbol_count": stale_symbol_count,
    }


def get_us_watchlist_ranking(
    db: Session,
    *,
    dependencies: USWatchlistWorkflowDependencies,
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = "none",
    sort_order: str = "asc",
    use_intraday: bool = False,
    intraday_limit: int = 30,
    intraday_session_scope: str = "regular",
) -> dict:
    if rank_by not in {"none", "change_pct", "volume", "close"}:
        raise ValueError("rank_by must be one of: none, change_pct, volume, close.")

    if sort_order not in {"asc", "desc"}:
        raise ValueError("sort_order must be one of: asc, desc.")

    if intraday_session_scope not in {"regular", "extended", "all"}:
        raise ValueError("intraday_session_scope must be one of: regular, extended, all.")

    query = db.query(USWatchlistItem)

    if group_id is not None:
        get_us_watchlist_group(db, group_id)
        group_ids = (
            _get_us_descendant_group_ids(db, group_id)
            if include_children
            else [group_id]
        )
        query = query.filter(USWatchlistItem.group_id.in_(group_ids))

    if enabled_only:
        query = query.filter(USWatchlistItem.enabled.is_(True))

    items = (
        query.order_by(
            USWatchlistItem.priority.asc(),
            USWatchlistItem.id.asc(),
        )
        .all()
    )
    unique_items: list[USWatchlistItem] = []
    seen_symbols: set[str] = set()

    for item in items:
        symbol = normalize_us_symbol(item.symbol)
        if not symbol or symbol in seen_symbols:
            continue

        unique_items.append(item)
        seen_symbols.add(symbol)

    symbols = [normalize_us_symbol(item.symbol) for item in unique_items]
    stocks_by_symbol = {
        stock.symbol: stock
        for stock in db.query(USStockMaster)
        .filter(USStockMaster.symbol.in_(symbols))
        .all()
    } if symbols else {}
    rows: list[dict] = []
    intraday_overlay_attempts = 0
    resolved_daily_by_symbol = dependencies.resolved_daily_batch_loader(
        db=db,
        symbols=symbols,
        bars=2,
    )

    for item in unique_items:
        symbol = normalize_us_symbol(item.symbol)
        stock = stocks_by_symbol.get(symbol)
        resolved_daily = resolved_daily_by_symbol.get(symbol, {})
        price_bars = _resolved_daily_bars(resolved_daily)
        latest = price_bars[-1] if price_bars else None
        previous = price_bars[-2] if len(price_bars) > 1 else None
        close = _finite_float(latest.get("close_price")) if latest else None
        previous_close = (
            _finite_float(previous.get("close_price")) if previous else None
        )
        volume_value = _finite_float(latest.get("volume")) if latest else None
        volume = (
            int(volume_value)
            if volume_value is not None and volume_value >= 0
            else None
        )
        change = (
            close - previous_close
            if close is not None and previous_close is not None
            else None
        )
        change_pct = (
            (change / previous_close) * 100
            if change is not None and previous_close not in {None, 0}
            else None
        )

        row = {
            "rank": 0,
            "symbol": symbol,
            "security_name": (
                stock.security_name
                if stock is not None
                else None
            ),
            "exchange": stock.exchange if stock is not None else None,
            "asset_type": stock.asset_type if stock is not None else None,
            "group_id": item.group_id,
            "trade_date": (
                _parse_us_row_trade_date(latest.get("start_at"))
                if latest is not None
                else None
            ),
            "time": None,
            "session": resolved_daily.get("selected_session"),
            "close": close,
            "previous_close": previous_close,
            "change": change,
            "change_pct": change_pct,
            "volume": volume,
            "status": "ready" if close is not None else "no_data",
            "source": resolved_daily.get("selected_source"),
            "selected_provider": resolved_daily.get("selected_provider"),
            "selected_source": resolved_daily.get("selected_source"),
            "selected_session": resolved_daily.get("selected_session"),
            "selection_reason": resolved_daily.get("selection_reason"),
            "fallback_used": bool(resolved_daily.get("fallback_used")),
            "price_basis": "raw_unadjusted",
            "has_extended_hours": False,
            "intraday_previous_close": None,
            "intraday_points": [],
            "error_message": None,
        }

        if use_intraday and intraday_overlay_attempts < intraday_limit:
            intraday_overlay_attempts += 1
            overlay = dependencies.intraday_overlay_loader(
                symbol=symbol,
                db=db,
                session_scope=intraday_session_scope,
            )

            if overlay is not None:
                row["intraday_overlay_applied"] = True
                row["time"] = overlay["time"]
                row["session"] = overlay["session"]
                row["close"] = overlay["close"]
                row["previous_close"] = overlay["previous_close"]
                row["change"] = overlay["change"]
                row["change_pct"] = overlay["change_pct"]
                row["source"] = overlay["source"]
                row["selected_provider"] = overlay.get("provider")
                row["selected_source"] = overlay.get("source")
                row["selected_session"] = overlay.get("session")
                row["selection_reason"] = "INTRADAY_OVERLAY_SELECTED"
                row["fallback_used"] = False
                row["has_extended_hours"] = overlay["has_extended_hours"]
                row["intraday_previous_close"] = overlay["previous_close"]
                row["intraday_points"] = overlay["points"]

                if overlay["volume"] is not None:
                    row["volume"] = overlay["volume"]

                row["status"] = (
                    "intraday"
                    if overlay.get("session") == "regular"
                    else "extended_hours"
                )

        rows.append(row)

    if rank_by != "none":
        ranked_rows = [
            row
            for row in rows
            if row.get(rank_by) is not None
        ]
        no_value_rows = [
            row
            for row in rows
            if row.get(rank_by) is None
        ]
        ranked_rows.sort(
            key=lambda row: row[rank_by],
            reverse=sort_order == "desc",
        )
        rows = ranked_rows + no_value_rows

    for index, row in enumerate(rows, start=1):
        row["rank"] = index

    no_data_count = sum(1 for row in rows if row["status"] == "no_data")
    freshness = _us_ranking_freshness(
        rows=rows,
        dependencies=dependencies,
        requested_symbol_count=len(unique_items),
    )
    requested_symbol_count = len(rows)
    ranked_count = len(rows) - no_data_count
    is_live = bool(
        use_intraday
        and any(row.get("intraday_overlay_applied") for row in rows)
    )

    return {
        "group_id": group_id,
        "include_children": include_children,
        "rank_by": rank_by,
        "sort_order": sort_order,
        "requested_symbol_count": requested_symbol_count,
        "ranked_count": ranked_count,
        "no_data_count": no_data_count,
        "error_count": 0,
        **freshness,
        "underlying_trade_date": freshness.get("trade_date"),
        "coverage_ratio": (
            ranked_count / requested_symbol_count
            if requested_symbol_count
            else 1.0
        ),
        "is_live": is_live,
        "is_full": (
            ranked_count == requested_symbol_count and no_data_count == 0
        ),
        "ranking_semantics": (
            "live_intraday_rows"
            if is_live
            else "resolved_completed_daily_bars"
        ),
        "results": rows,
    }


def refresh_us_watchlist_daily_prices(
    db: Session,
    *,
    dependencies: USWatchlistWorkflowDependencies,
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    outputsize: str = "compact",
    adjusted: bool = False,
    sleep_seconds: float = 12.0,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    symbols = list_us_watchlist_symbols(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
    )
    total = len(symbols)

    if progress_callback is not None:
        progress_callback(0, max(total, 1), "Refreshing US watchlist daily prices.")

    if not symbols:
        return {
            "status": "empty",
            "group_id": group_id,
            "symbol_count": 0,
            "fetched_count": 0,
            "eligible_count": 0,
            "skipped_count": 0,
            "partial_symbol_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "errors": [],
        }

    fetched_count = 0
    eligible_count = 0
    skipped_count = 0
    partial_symbol_count = 0
    inserted_count = 0
    updated_count = 0
    errors: list[dict[str, str]] = []

    for index, symbol in enumerate(symbols, start=1):
        try:
            result = dependencies.refresh_daily_prices(
                db=db,
                symbol=symbol,
                outputsize=outputsize,
                adjusted=adjusted,
            )
            fetched_count += result["fetched_count"]
            eligible_count += int(result.get("eligible_count", result["fetched_count"]))
            skipped_count += int(result.get("skipped_count", 0))
            if result.get("status") == "partial_success":
                partial_symbol_count += 1
            inserted_count += result["inserted_count"]
            updated_count += result["updated_count"]
        except USMarketConfigurationError:
            raise
        except Exception as exc:
            errors.append(
                {
                    "symbol": symbol,
                    "message": str(exc),
                }
            )

        if progress_callback is not None:
            progress_callback(index, total, f"Refreshed {index}/{total} US symbols.")

        if index < total and sleep_seconds > 0:
            time.sleep(sleep_seconds)

    return {
        "status": (
            "partial_success"
            if errors or partial_symbol_count
            else "success"
        ),
        "group_id": group_id,
        "symbol_count": total,
        "fetched_count": fetched_count,
        "eligible_count": eligible_count,
        "skipped_count": skipped_count,
        "partial_symbol_count": partial_symbol_count,
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "errors": errors,
    }


def _compact_us_resource_result(result: dict) -> dict:
    return {
        "status": result.get("status", "success"),
        "fetched_count": int(result.get("fetched_count") or 0),
        "inserted_count": int(result.get("inserted_count") or 0),
        "updated_count": int(result.get("updated_count") or 0),
        "message": result.get("message"),
    }


def _refresh_us_symbol_resources(
    db: Session,
    *,
    dependencies: USWatchlistWorkflowDependencies,
    symbol: str,
    include_daily: bool,
    include_sec_facts: bool,
    include_profile: bool,
    include_actions: bool,
    outputsize: str,
    adjusted: bool,
) -> dict:
    normalized_symbol = normalize_us_symbol(symbol)
    stock = dependencies.ensure_stock(db, normalized_symbol)
    resources: dict[str, dict] = {}
    errors: list[dict[str, str]] = []

    def run_resource(resource: str, callback: Callable[[], dict]) -> None:
        try:
            resources[resource] = _compact_us_resource_result(callback())
        except Exception as exc:
            db.rollback()
            message = str(exc)
            resources[resource] = {
                "status": "error",
                "fetched_count": 0,
                "inserted_count": 0,
                "updated_count": 0,
                "message": message,
            }
            errors.append(
                {
                    "symbol": normalized_symbol,
                    "resource": resource,
                    "message": message,
                }
            )

    if include_daily:
        run_resource(
            "daily",
            lambda: dependencies.refresh_daily_prices(
                db=db,
                symbol=normalized_symbol,
                outputsize=outputsize,
                adjusted=adjusted,
            ),
        )

    if include_sec_facts:
        is_sec_company = not stock.is_etf and (stock.asset_type or "").upper() != "ETF"
        if is_sec_company:
            run_resource(
                "sec_facts",
                lambda: dependencies.refresh_sec_facts(db=db, symbol=normalized_symbol),
            )
        else:
            resources["sec_facts"] = {
                "status": "skipped",
                "fetched_count": 0,
                "inserted_count": 0,
                "updated_count": 0,
                "message": "SEC company facts skipped for ETF/non-company asset.",
            }

    if include_profile:
        run_resource(
            "profile",
            lambda: dependencies.refresh_company_profile(
                db=db,
                symbol=normalized_symbol,
            ),
        )

    if include_actions:
        run_resource(
            "actions",
            lambda: dependencies.refresh_corporate_actions(
                db=db,
                symbol=normalized_symbol,
            ),
        )

    success_count = sum(1 for item in resources.values() if item["status"] == "success")
    skipped_count = sum(1 for item in resources.values() if item["status"] == "skipped")

    if errors:
        symbol_status = "error" if success_count == 0 else "partial_success"
    elif resources and skipped_count == len(resources):
        symbol_status = "skipped"
    else:
        symbol_status = "success"

    return {
        "symbol": normalized_symbol,
        "asset_type": stock.asset_type,
        "exchange": stock.exchange,
        "status": symbol_status,
        "resource_count": len(resources),
        "success_count": success_count,
        "skipped_count": skipped_count,
        "error_count": len(errors),
        "fetched_count": sum(item["fetched_count"] for item in resources.values()),
        "inserted_count": sum(item["inserted_count"] for item in resources.values()),
        "updated_count": sum(item["updated_count"] for item in resources.values()),
        "resources": resources,
        "errors": errors,
    }


def refresh_us_watchlist_resources(
    db: Session,
    *,
    dependencies: USWatchlistWorkflowDependencies,
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    include_daily: bool = True,
    include_sec_facts: bool = True,
    include_profile: bool = True,
    include_actions: bool = False,
    outputsize: str = "compact",
    adjusted: bool = False,
    sleep_seconds: float = 12.0,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    symbols = list_us_watchlist_symbols(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
    )
    total = len(symbols)

    if progress_callback is not None:
        progress_callback(0, max(total, 1), "Refreshing US watchlist resources.")

    if not symbols:
        return {
            "status": "empty",
            "group_id": group_id,
            "symbol_count": 0,
            "success_count": 0,
            "partial_success_count": 0,
            "skipped_count": 0,
            "error_count": 0,
            "symbol_error_count": 0,
            "fetched_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "results": [],
            "errors": [],
        }

    results: list[dict] = []
    errors: list[dict[str, str]] = []

    for index, symbol in enumerate(symbols, start=1):
        result = _refresh_us_symbol_resources(
            db=db,
            dependencies=dependencies,
            symbol=symbol,
            include_daily=include_daily,
            include_sec_facts=include_sec_facts,
            include_profile=include_profile,
            include_actions=include_actions,
            outputsize=outputsize,
            adjusted=adjusted,
        )
        results.append(result)
        errors.extend(result["errors"])

        if progress_callback is not None:
            progress_callback(index, total, f"Refreshed {index}/{total} US symbols.")

        if index < total and sleep_seconds > 0:
            time.sleep(sleep_seconds)

    success_count = sum(1 for result in results if result["status"] == "success")
    partial_success_count = sum(1 for result in results if result["status"] == "partial_success")
    skipped_count = sum(1 for result in results if result["status"] == "skipped")
    symbol_error_count = sum(1 for result in results if result["status"] == "error")

    if symbol_error_count and success_count == 0 and partial_success_count == 0:
        status_value = "error"
    elif errors:
        status_value = "partial_success"
    else:
        status_value = "success"

    return {
        "status": status_value,
        "group_id": group_id,
        "symbol_count": total,
        "success_count": success_count,
        "partial_success_count": partial_success_count,
        "skipped_count": skipped_count,
        "error_count": len(errors),
        "symbol_error_count": symbol_error_count,
        "fetched_count": sum(result["fetched_count"] for result in results),
        "inserted_count": sum(result["inserted_count"] for result in results),
        "updated_count": sum(result["updated_count"] for result in results),
        "results": results,
        "errors": errors,
    }
