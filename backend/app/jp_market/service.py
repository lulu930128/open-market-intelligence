from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
import math
import time
from types import SimpleNamespace

import requests
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    JPCompanyFundamental,
    JPDailyPrice,
    JPInvestorType,
    JPMarginInterest,
    JPStockMaster,
    JPWatchlistGroup,
    JPWatchlistItem,
    utc_now,
)
from app.observability.provider_http import translate_provider_http_errors
from app.jp_market.chart_projection import (
    aggregate_daily_rows as _aggregate_jp_daily_rows,
    daily_canonical_sort_key as _jp_daily_canonical_sort_key,
    daily_row_completeness_score as _jp_daily_row_completeness_score,
    datetime_sort_value as _datetime_sort_value,
    dedupe_daily_rows_by_trade_date as _dedupe_jp_daily_rows_by_trade_date,
    ohlc_point as _jp_ohlc_point,
    sum_nullable as _sum_nullable,
)
from app.jp_market.errors import JPMarketDataFetchError
from app.jp_market.schemas import (
    JPWatchlistGroupCreate,
    JPWatchlistGroupUpdate,
    JPWatchlistItemCreate,
    JPWatchlistItemUpdate,
)
from app.jp_market.providers.jpx import fetch_jpx_listed_issues_workbook
from app.jp_market.providers.jquants import (
    fetch_jquants_id_token,
    fetch_jquants_investor_types_payload,
    fetch_jquants_margin_interest_payload,
    fetch_jquants_refresh_token,
    fetch_jquants_statements_payload,
    fetch_jquants_summary_payload,
)
from app.jp_market.providers.yahoo import (
    fetch_yahoo_chart_payload,
    fetch_yahoo_quote_summary_payload,
)
from app.jp_market.sources import (
    JPCompanyFundamentalRecord,
    JPDailyPriceRecord,
    JPInvestorTypeRecord,
    JPMarginInterestRecord,
    JPStockRecord,
    local_code_from_symbol,
    normalize_jp_symbol,
    parse_jpx_listed_issues_workbook,
    parse_jquants_company_fundamental,
    parse_jquants_investor_type_records,
    parse_jquants_margin_interest_records,
    parse_yahoo_company_fundamental,
    parse_yahoo_daily_prices,
    parse_yahoo_intraday_prices,
    parse_yahoo_stock_record,
)
from app.jp_market.trading_calendar import (
    JP_MARKET_TIMEZONE,
    expected_jp_daily_price_date,
    previous_jp_trading_day,
)
from app.jp_market.source_health import build_jp_source_health
from app.market.calendar_status import build_jp_calendar_status
from app.market.stock_volume_pace import (
    build_stock_volume_pace,
    intraday_history_needs_bootstrap,
    latest_market_trade_date_points,
    load_persisted_market_intraday_history,
    mutate_market_intraday_history,
    previous_regular_close_from_history,
)
from app.market.technical_radar import (
    TechnicalRadarBar,
    build_technical_watchlist_radar,
)


_translate_jp_provider_errors = translate_provider_http_errors(JPMarketDataFetchError)


class JPStockNotFoundError(Exception):
    pass


class JPWatchlistGroupNotFoundError(Exception):
    pass


class JPWatchlistGroupNotEmptyError(Exception):
    pass


class JPWatchlistInvalidTreeError(Exception):
    pass


class JPWatchlistItemNotFoundError(Exception):
    pass


class JPWatchlistDuplicateItemError(Exception):
    pass


JP_CHART_LOOKBACK_MULTIPLIER = {
    "daily": 2,
    "weekly": 8,
    "monthly": 31,
}
JP_FUNDAMENTAL_PRIMARY_PROVIDER = "jquants_statements"
JP_FUNDAMENTAL_SUPPLEMENTAL_PROVIDER = "yahoo_quote_summary"
JP_MARGIN_INTEREST_PROVIDER = "jquants_margin_interest"
JP_INVESTOR_TYPES_PROVIDER = "jquants_investor_types"
JP_FUNDAMENTAL_PROVIDER_PRIORITY = (
    JP_FUNDAMENTAL_PRIMARY_PROVIDER,
    JP_FUNDAMENTAL_SUPPLEMENTAL_PROVIDER,
)
JP_FUNDAMENTAL_PROVIDER_SET = {"auto", *JP_FUNDAMENTAL_PROVIDER_PRIORITY}
JP_COMPANY_FUNDAMENTAL_FIELDS = tuple(
    column.name for column in JPCompanyFundamental.__table__.columns
)
_jquants_id_token_cache: dict[str, str | float] | None = None
MAX_JP_CHART_BARS = 5000
YAHOO_CHART_COMPACT_RANGE = "1y"
YAHOO_CHART_FULL_RANGE = "10y"
JP_INTRADAY_CACHE_SECONDS = 60
_jp_intraday_cache: dict[str, tuple[float, dict]] = {}
JP_DAILY_REFRESH_ATTEMPT_COOLDOWN_SECONDS = 300
_jp_daily_refresh_attempts: dict[str, float] = {}
ProgressCallback = Callable[[int | None, int | None, str | None], None]


def _valid_symbol(symbol: str) -> str:
    normalized_symbol = normalize_jp_symbol(symbol)
    if not normalized_symbol:
        raise ValueError("symbol is required.")

    return normalized_symbol


def get_jp_stock(db: Session, *, symbol: str) -> JPStockMaster:
    normalized_symbol = _valid_symbol(symbol)
    stock = (
        db.query(JPStockMaster)
        .filter(JPStockMaster.symbol == normalized_symbol)
        .first()
    )
    if stock is None:
        raise JPStockNotFoundError(f"JP symbol='{normalized_symbol}' was not found.")

    return stock


def list_jp_stocks(
    db: Session,
    *,
    exchange: str | None = None,
    asset_type: str | None = None,
    is_active: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[JPStockMaster]:
    query = db.query(JPStockMaster)

    if exchange is not None:
        query = query.filter(JPStockMaster.exchange == exchange)

    if asset_type is not None:
        query = query.filter(JPStockMaster.asset_type == asset_type)

    if is_active is not None:
        query = query.filter(JPStockMaster.is_active.is_(is_active))

    return (
        query.order_by(JPStockMaster.symbol.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def search_jp_stocks(
    db: Session,
    *,
    keyword: str,
    limit: int = 50,
) -> list[JPStockMaster]:
    normalized_keyword = (keyword or "").strip()
    if not normalized_keyword:
        return []

    normalized_symbol = normalize_jp_symbol(normalized_keyword)
    local_code = normalized_symbol.split(".", maxsplit=1)[0]
    pattern = f"%{normalized_keyword}%"

    return (
        db.query(JPStockMaster)
        .filter(
            or_(
                JPStockMaster.symbol == normalized_symbol,
                JPStockMaster.local_code == local_code,
                JPStockMaster.security_name.ilike(pattern),
                JPStockMaster.market_segment.ilike(pattern),
                JPStockMaster.sector_33_name.ilike(pattern),
                JPStockMaster.sector_17_name.ilike(pattern),
            )
        )
        .order_by(JPStockMaster.symbol.asc())
        .limit(limit)
        .all()
    )


def upsert_jp_stock_record(db: Session, record: JPStockRecord) -> JPStockMaster:
    existing = (
        db.query(JPStockMaster)
        .filter(JPStockMaster.symbol == record.symbol)
        .first()
    )

    if existing is None:
        existing = JPStockMaster(
            symbol=record.symbol,
            local_code=record.local_code,
            security_name=record.security_name,
            exchange=record.exchange,
            market_segment=record.market_segment,
            sector_33_code=record.sector_33_code,
            sector_33_name=record.sector_33_name,
            sector_17_code=record.sector_17_code,
            sector_17_name=record.sector_17_name,
            size_code=record.size_code,
            size_name=record.size_name,
            asset_type=record.asset_type,
            listing_source=record.listing_source,
            currency=record.currency,
            exchange_timezone_name=record.exchange_timezone_name,
            is_active=True,
            first_seen_at=utc_now(),
            last_seen_at=utc_now(),
        )
        db.add(existing)
        return existing

    existing.local_code = record.local_code or existing.local_code
    existing.security_name = record.security_name or existing.security_name
    existing.exchange = record.exchange or existing.exchange
    existing.market_segment = record.market_segment or existing.market_segment
    existing.sector_33_code = record.sector_33_code or existing.sector_33_code
    existing.sector_33_name = record.sector_33_name or existing.sector_33_name
    existing.sector_17_code = record.sector_17_code or existing.sector_17_code
    existing.sector_17_name = record.sector_17_name or existing.sector_17_name
    existing.size_code = record.size_code or existing.size_code
    existing.size_name = record.size_name or existing.size_name
    existing.asset_type = record.asset_type or existing.asset_type
    existing.listing_source = record.listing_source or existing.listing_source
    existing.currency = record.currency or existing.currency
    existing.exchange_timezone_name = record.exchange_timezone_name or existing.exchange_timezone_name
    existing.is_active = True
    existing.last_seen_at = utc_now()
    existing.updated_at = utc_now()
    return existing


def upsert_jp_stock_records(db: Session, records: list[JPStockRecord]) -> dict:
    created_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(JPStockMaster)
            .filter(JPStockMaster.symbol == record.symbol)
            .first()
        )
        upsert_jp_stock_record(db, record)

        if existing is None:
            created_count += 1
        else:
            updated_count += 1

    db.commit()

    return {
        "created_count": created_count,
        "updated_count": updated_count,
    }


@_translate_jp_provider_errors
def sync_jp_symbol_master(
    db: Session,
    *,
    deactivate_missing: bool = False,
) -> dict:
    content, source_url = fetch_jpx_listed_issues_workbook(
        timeout_seconds=settings.jp_market_http_timeout_seconds,
    )
    records = parse_jpx_listed_issues_workbook(content)
    result = upsert_jp_stock_records(db, records)
    scanned_symbols = {record.symbol for record in records}
    deactivated_count = 0

    if deactivate_missing and scanned_symbols:
        stale_rows = (
            db.query(JPStockMaster)
            .filter(JPStockMaster.is_active.is_(True))
            .filter(~JPStockMaster.symbol.in_(scanned_symbols))
            .all()
        )
        for row in stale_rows:
            row.is_active = False
            row.updated_at = utc_now()
            deactivated_count += 1
        db.commit()

    return {
        "status": "success",
        "provider": "jpx_listed_issues",
        "source_url": source_url,
        "scanned_count": len(records),
        "created_count": result["created_count"],
        "updated_count": result["updated_count"],
        "deactivated_count": deactivated_count,
        "message": "JP stock master synced from JPX listed issues.",
    }


def get_jp_watchlist_group(db: Session, group_id: int) -> JPWatchlistGroup:
    group = (
        db.query(JPWatchlistGroup)
        .filter(JPWatchlistGroup.id == group_id)
        .first()
    )

    if group is None:
        raise JPWatchlistGroupNotFoundError(f"JP watchlist group id={group_id} not found.")

    return group


def _validate_jp_watchlist_parent(
    db: Session,
    group_id: int | None,
    parent_id: int | None,
) -> None:
    if parent_id is None:
        return

    parent = (
        db.query(JPWatchlistGroup)
        .filter(JPWatchlistGroup.id == parent_id)
        .first()
    )

    if parent is None:
        raise JPWatchlistGroupNotFoundError(f"Parent JP watchlist group id={parent_id} not found.")

    if group_id is not None and parent_id == group_id:
        raise JPWatchlistInvalidTreeError("A JP watchlist group cannot be its own parent.")

    current = parent
    while current is not None:
        if group_id is not None and current.id == group_id:
            raise JPWatchlistInvalidTreeError("Cannot move a JP watchlist group under its descendant.")

        if current.parent_id is None:
            break

        current = (
            db.query(JPWatchlistGroup)
            .filter(JPWatchlistGroup.id == current.parent_id)
            .first()
        )


def create_jp_watchlist_group(
    db: Session,
    payload: JPWatchlistGroupCreate,
) -> JPWatchlistGroup:
    _validate_jp_watchlist_parent(db=db, group_id=None, parent_id=payload.parent_id)

    group = JPWatchlistGroup(**payload.model_dump())
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def list_jp_watchlist_groups(
    db: Session,
    *,
    is_active: bool | None = None,
) -> list[JPWatchlistGroup]:
    query = db.query(JPWatchlistGroup)

    if is_active is not None:
        query = query.filter(JPWatchlistGroup.is_active.is_(is_active))

    return (
        query.order_by(
            JPWatchlistGroup.parent_id.asc().nullsfirst(),
            JPWatchlistGroup.sort_order.asc(),
            JPWatchlistGroup.id.asc(),
        )
        .all()
    )


def _jp_group_to_tree_node(
    group: JPWatchlistGroup,
    children_by_parent: dict[int | None, list[JPWatchlistGroup]],
) -> dict:
    children = [
        _jp_group_to_tree_node(child, children_by_parent)
        for child in children_by_parent.get(group.id, [])
    ]

    return {
        "id": group.id,
        "parent_id": group.parent_id,
        "group_name": group.group_name,
        "description": group.description,
        "sort_order": group.sort_order,
        "is_active": group.is_active,
        "children": children,
    }


def get_jp_watchlist_tree(
    db: Session,
    *,
    is_active: bool | None = True,
) -> list[dict]:
    groups = list_jp_watchlist_groups(db=db, is_active=is_active)
    children_by_parent: dict[int | None, list[JPWatchlistGroup]] = {}

    for group in groups:
        children_by_parent.setdefault(group.parent_id, []).append(group)

    return [
        _jp_group_to_tree_node(group, children_by_parent)
        for group in children_by_parent.get(None, [])
    ]


def update_jp_watchlist_group(
    db: Session,
    group_id: int,
    payload: JPWatchlistGroupUpdate,
) -> JPWatchlistGroup:
    group = get_jp_watchlist_group(db, group_id)
    update_data = payload.model_dump(exclude_unset=True)

    if "parent_id" in update_data:
        _validate_jp_watchlist_parent(
            db=db,
            group_id=group_id,
            parent_id=update_data["parent_id"],
        )

    for key, value in update_data.items():
        setattr(group, key, value)

    db.commit()
    db.refresh(group)
    return group


def _get_jp_descendant_group_ids(db: Session, group_id: int) -> list[int]:
    groups = db.query(JPWatchlistGroup).all()
    children_by_parent: dict[int | None, list[JPWatchlistGroup]] = {}

    for group in groups:
        children_by_parent.setdefault(group.parent_id, []).append(group)

    result: list[int] = []

    def walk(current_id: int) -> None:
        result.append(current_id)

        for child in children_by_parent.get(current_id, []):
            walk(child.id)

    walk(group_id)
    return result


def delete_jp_watchlist_group(
    db: Session,
    group_id: int,
    *,
    recursive: bool = False,
) -> dict:
    get_jp_watchlist_group(db, group_id)
    group_ids = _get_jp_descendant_group_ids(db, group_id)

    if not recursive and len(group_ids) > 1:
        raise JPWatchlistGroupNotEmptyError(
            f"JP watchlist group id={group_id} has child groups."
        )

    item_count = (
        db.query(JPWatchlistItem)
        .filter(JPWatchlistItem.group_id.in_(group_ids))
        .count()
    )
    if not recursive and item_count > 0:
        raise JPWatchlistGroupNotEmptyError(
            f"JP watchlist group id={group_id} has watchlist items."
        )

    (
        db.query(JPWatchlistItem)
        .filter(JPWatchlistItem.group_id.in_(group_ids))
        .delete(synchronize_session=False)
    )
    (
        db.query(JPWatchlistGroup)
        .filter(JPWatchlistGroup.id.in_(group_ids))
        .delete(synchronize_session=False)
    )
    db.commit()

    return {
        "deleted_group_id": group_id,
        "deleted_item_count": item_count,
        "deleted_group_count": len(group_ids),
    }


def _jp_watchlist_item_to_dict(
    db: Session,
    item: JPWatchlistItem,
) -> dict:
    stock = (
        db.query(JPStockMaster)
        .filter(JPStockMaster.symbol == item.symbol)
        .first()
    )

    return {
        "id": item.id,
        "group_id": item.group_id,
        "symbol": item.symbol,
        "local_code": stock.local_code if stock else None,
        "security_name": stock.security_name if stock else None,
        "exchange": stock.exchange if stock else None,
        "market_segment": stock.market_segment if stock else None,
        "sector_33_name": stock.sector_33_name if stock else None,
        "asset_type": stock.asset_type if stock else None,
        "note": item.note,
        "priority": item.priority,
        "tags": item.tags,
        "enabled": item.enabled,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def create_jp_watchlist_item(
    db: Session,
    payload: JPWatchlistItemCreate,
) -> dict:
    get_jp_watchlist_group(db, payload.group_id)
    stock = get_jp_stock(db=db, symbol=payload.symbol)
    payload_data = payload.model_dump()
    payload_data["symbol"] = stock.symbol

    item = JPWatchlistItem(**payload_data)
    db.add(item)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise JPWatchlistDuplicateItemError(
            f"JP symbol='{stock.symbol}' already exists in group id={payload.group_id}."
        ) from exc

    db.refresh(item)
    return _jp_watchlist_item_to_dict(db, item)


def get_jp_watchlist_item(db: Session, item_id: int) -> JPWatchlistItem:
    item = (
        db.query(JPWatchlistItem)
        .filter(JPWatchlistItem.id == item_id)
        .first()
    )

    if item is None:
        raise JPWatchlistItemNotFoundError(f"JP watchlist item id={item_id} not found.")

    return item


def list_jp_watchlist_items(
    db: Session,
    *,
    group_id: int | None = None,
    symbol: str | None = None,
    enabled: bool | None = None,
    include_children: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    query = db.query(JPWatchlistItem)

    if group_id is not None:
        get_jp_watchlist_group(db, group_id)

        if include_children:
            group_ids = _get_jp_descendant_group_ids(db, group_id)
            query = query.filter(JPWatchlistItem.group_id.in_(group_ids))
        else:
            query = query.filter(JPWatchlistItem.group_id == group_id)

    if symbol is not None:
        query = query.filter(JPWatchlistItem.symbol == _valid_symbol(symbol))

    if enabled is not None:
        query = query.filter(JPWatchlistItem.enabled.is_(enabled))

    items = (
        query.order_by(
            JPWatchlistItem.priority.asc(),
            JPWatchlistItem.id.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [_jp_watchlist_item_to_dict(db, item) for item in items]


def update_jp_watchlist_item(
    db: Session,
    item_id: int,
    payload: JPWatchlistItemUpdate,
) -> dict:
    item = get_jp_watchlist_item(db, item_id)
    update_data = payload.model_dump(exclude_unset=True)

    if "group_id" in update_data and update_data["group_id"] is not None:
        get_jp_watchlist_group(db, update_data["group_id"])

    if "symbol" in update_data and update_data["symbol"] is not None:
        stock = get_jp_stock(db=db, symbol=update_data["symbol"])
        update_data["symbol"] = stock.symbol

    for key, value in update_data.items():
        setattr(item, key, value)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise JPWatchlistDuplicateItemError(
            f"JP symbol='{item.symbol}' already exists in group id={item.group_id}."
        ) from exc

    db.refresh(item)
    return _jp_watchlist_item_to_dict(db, item)


def delete_jp_watchlist_item(db: Session, item_id: int) -> None:
    item = get_jp_watchlist_item(db, item_id)
    db.delete(item)
    db.commit()


def list_jp_watchlist_symbols(
    db: Session,
    *,
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
) -> list[str]:
    query = db.query(JPWatchlistItem)

    if group_id is not None:
        get_jp_watchlist_group(db, group_id)

        if include_children:
            group_ids = _get_jp_descendant_group_ids(db, group_id)
            query = query.filter(JPWatchlistItem.group_id.in_(group_ids))
        else:
            query = query.filter(JPWatchlistItem.group_id == group_id)

    if enabled_only:
        query = query.filter(JPWatchlistItem.enabled.is_(True))

    rows = (
        query.order_by(
            JPWatchlistItem.priority.asc(),
            JPWatchlistItem.id.asc(),
        )
        .all()
    )
    symbols: list[str] = []
    seen: set[str] = set()

    for row in rows:
        symbol = normalize_jp_symbol(row.symbol)
        if not symbol or symbol in seen:
            continue

        symbols.append(symbol)
        seen.add(symbol)

    return symbols


def _jp_close_value(row: JPDailyPrice | None) -> float | None:
    if row is None:
        return None

    return row.adjusted_close if row.adjusted_close is not None else row.close_price


def _latest_distinct_jp_daily_rows(
    db: Session,
    *,
    symbol: str,
    limit: int = 2,
) -> list[JPDailyPrice]:
    rows = (
        db.query(JPDailyPrice)
        .filter(JPDailyPrice.symbol == symbol)
        .order_by(
            JPDailyPrice.trade_date.desc(),
            JPDailyPrice.fetched_at.desc(),
            JPDailyPrice.id.desc(),
        )
        .limit(max(limit * 4, limit))
        .all()
    )
    selected_rows: list[JPDailyPrice] = []
    seen_dates: set[date] = set()

    for row in rows:
        if row.trade_date in seen_dates:
            continue

        selected_rows.append(row)
        seen_dates.add(row.trade_date)

        if len(selected_rows) >= limit:
            break

    return selected_rows


def _jp_ranking_freshness(
    rows: list[dict],
    requested_symbol_count: int,
    *,
    expected_trade_date: date,
) -> dict:
    row_dates = [
        row.get("trade_date")
        for row in rows
        if isinstance(row.get("trade_date"), date)
    ]
    latest_trade_date = max(row_dates, default=None)
    current_symbol_count = sum(1 for row_date in row_dates if row_date == expected_trade_date)
    stale_symbol_count = sum(1 for row_date in row_dates if row_date < expected_trade_date)
    future_symbol_count = sum(1 for row_date in row_dates if row_date > expected_trade_date)
    missing_symbol_count = max(requested_symbol_count - len(row_dates), 0)
    if requested_symbol_count == 0 or current_symbol_count == requested_symbol_count:
        coverage_status = "current"
    elif current_symbol_count > 0:
        coverage_status = "partial"
    elif row_dates:
        coverage_status = "stale"
    else:
        coverage_status = "missing"

    return {
        "trade_date": latest_trade_date,
        "target_trade_date": expected_trade_date,
        "is_current": requested_symbol_count == 0 or current_symbol_count == requested_symbol_count,
        "current_symbol_count": current_symbol_count,
        "stale_symbol_count": stale_symbol_count,
        "missing_symbol_count": missing_symbol_count,
        "future_symbol_count": future_symbol_count,
        "coverage_status": coverage_status,
        "refresh_recommended": stale_symbol_count > 0 or missing_symbol_count > 0,
    }


def get_jp_watchlist_ranking(
    db: Session,
    *,
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = "none",
    sort_order: str = "asc",
    expected_trade_date: date | None = None,
    now: datetime | None = None,
) -> dict:
    if rank_by not in {"none", "change_pct", "volume", "close"}:
        raise ValueError("rank_by must be one of: none, change_pct, volume, close.")

    if sort_order not in {"asc", "desc"}:
        raise ValueError("sort_order must be one of: asc, desc.")

    resolved_expected_trade_date = expected_trade_date or expected_jp_daily_price_date(now=now)
    query = db.query(JPWatchlistItem)

    if group_id is not None:
        get_jp_watchlist_group(db, group_id)
        group_ids = (
            _get_jp_descendant_group_ids(db, group_id)
            if include_children
            else [group_id]
        )
        query = query.filter(JPWatchlistItem.group_id.in_(group_ids))

    if enabled_only:
        query = query.filter(JPWatchlistItem.enabled.is_(True))

    items = (
        query.order_by(
            JPWatchlistItem.priority.asc(),
            JPWatchlistItem.id.asc(),
        )
        .all()
    )
    unique_items: list[JPWatchlistItem] = []
    seen_symbols: set[str] = set()

    for item in items:
        symbol = normalize_jp_symbol(item.symbol)
        if not symbol or symbol in seen_symbols:
            continue

        unique_items.append(item)
        seen_symbols.add(symbol)

    symbols = [normalize_jp_symbol(item.symbol) for item in unique_items]
    stocks_by_symbol = {
        stock.symbol: stock
        for stock in db.query(JPStockMaster)
        .filter(JPStockMaster.symbol.in_(symbols))
        .all()
    } if symbols else {}
    rows: list[dict] = []

    for item in unique_items:
        symbol = normalize_jp_symbol(item.symbol)
        stock = stocks_by_symbol.get(symbol)
        price_rows = _latest_distinct_jp_daily_rows(
            db=db,
            symbol=symbol,
            limit=2,
        )
        latest = price_rows[0] if price_rows else None
        previous = price_rows[1] if len(price_rows) > 1 else None
        close = _jp_close_value(latest)
        previous_close = _jp_close_value(previous)
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

        rows.append(
            {
                "rank": 0,
                "symbol": symbol,
                "security_name": stock.security_name if stock is not None else None,
                "exchange": stock.exchange if stock is not None else None,
                "market_segment": stock.market_segment if stock is not None else None,
                "sector_33_name": stock.sector_33_name if stock is not None else None,
                "asset_type": stock.asset_type if stock is not None else None,
                "group_id": item.group_id,
                "trade_date": latest.trade_date if latest is not None else None,
                "close": close,
                "previous_close": previous_close,
                "change": change,
                "change_pct": change_pct,
                "volume": latest.trade_volume if latest is not None else None,
                "status": (
                    "no_data"
                    if close is None
                    else "stale"
                    if latest is not None and latest.trade_date < resolved_expected_trade_date
                    else "ready"
                ),
                "source": latest.provider if latest is not None else None,
                "error_message": None,
                "latest_fetched_at": latest.fetched_at if latest is not None else None,
                "freshness_status": (
                    "missing"
                    if latest is None
                    else "stale"
                    if latest.trade_date < resolved_expected_trade_date
                    else "future"
                    if latest.trade_date > resolved_expected_trade_date
                    else "current"
                ),
            }
        )

    if rank_by != "none":
        ranked_rows = [row for row in rows if row.get(rank_by) is not None]
        no_value_rows = [row for row in rows if row.get(rank_by) is None]
        ranked_rows.sort(
            key=lambda row: row[rank_by],
            reverse=sort_order == "desc",
        )
        rows = ranked_rows + no_value_rows

    for index, row in enumerate(rows, start=1):
        row["rank"] = index

    no_data_count = sum(1 for row in rows if row["status"] == "no_data")
    freshness = _jp_ranking_freshness(
        rows=rows,
        requested_symbol_count=len(unique_items),
        expected_trade_date=resolved_expected_trade_date,
    )
    requested_symbol_count = len(rows)
    ranked_count = len(rows) - no_data_count

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
        "is_live": False,
        "is_full": (
            ranked_count == requested_symbol_count and no_data_count == 0
        ),
        "ranking_semantics": "latest_completed_daily_rows",
        "results": rows,
    }


def _jp_market_overview_recent_rows(
    db: Session,
    *,
    expected_trade_date: date,
) -> dict[str, list[dict]]:
    provider_ranked = (
        db.query(
            JPDailyPrice.id.label("price_id"),
            JPDailyPrice.symbol.label("symbol"),
            JPDailyPrice.trade_date.label("trade_date"),
            JPDailyPrice.close_price.label("close_price"),
            JPDailyPrice.adjusted_close.label("adjusted_close"),
            JPDailyPrice.trade_volume.label("trade_volume"),
            JPDailyPrice.provider.label("provider"),
            JPDailyPrice.fetched_at.label("fetched_at"),
            JPStockMaster.security_name.label("security_name"),
            JPStockMaster.sector_33_name.label("sector_33_name"),
            func.row_number()
            .over(
                partition_by=(JPDailyPrice.symbol, JPDailyPrice.trade_date),
                order_by=(JPDailyPrice.fetched_at.desc(), JPDailyPrice.id.desc()),
            )
            .label("provider_rank"),
        )
        .join(JPStockMaster, JPStockMaster.symbol == JPDailyPrice.symbol)
        .filter(
            JPStockMaster.is_active.is_(True),
            JPStockMaster.asset_type == "stock",
            JPDailyPrice.trade_date <= expected_trade_date,
        )
        .subquery()
    )
    canonical = (
        db.query(
            provider_ranked.c.price_id,
            provider_ranked.c.symbol,
            provider_ranked.c.trade_date,
            provider_ranked.c.close_price,
            provider_ranked.c.adjusted_close,
            provider_ranked.c.trade_volume,
            provider_ranked.c.provider,
            provider_ranked.c.fetched_at,
            provider_ranked.c.security_name,
            provider_ranked.c.sector_33_name,
        )
        .filter(provider_ranked.c.provider_rank == 1)
        .subquery()
    )
    recent = (
        db.query(
            canonical,
            func.row_number()
            .over(
                partition_by=canonical.c.symbol,
                order_by=(canonical.c.trade_date.desc(), canonical.c.price_id.desc()),
            )
            .label("date_rank"),
        )
        .subquery()
    )
    rows = db.query(recent).filter(recent.c.date_rank <= 2).all()
    by_symbol: dict[str, list[dict]] = {}
    for row in rows:
        payload = dict(row._mapping)
        by_symbol.setdefault(str(payload["symbol"]), []).append(payload)
    for symbol_rows in by_symbol.values():
        symbol_rows.sort(key=lambda item: item["date_rank"])
    return by_symbol


def _jp_market_index_snapshots(
    db: Session,
    *,
    expected_trade_date: date,
) -> list[dict]:
    snapshots: list[dict] = []
    for symbol, label, role in (
        ("^N225", "Nikkei 225", "primary_benchmark"),
        ("1306.T", "TOPIX ETF", "topix_proxy"),
    ):
        rows = _latest_distinct_jp_daily_rows(db=db, symbol=symbol, limit=60)
        latest = rows[0] if rows else None
        previous = rows[1] if len(rows) > 1 else None
        close = _jp_close_value(latest)
        previous_close = _jp_close_value(previous)
        change = (
            close - previous_close
            if close is not None and previous_close is not None
            else None
        )
        change_pct = (
            change / previous_close * 100
            if change is not None and previous_close not in {None, 0}
            else None
        )
        latest_date = latest.trade_date if latest is not None else None
        freshness_status = (
            "missing"
            if latest_date is None
            else "stale"
            if latest_date < expected_trade_date
            else "future"
            if latest_date > expected_trade_date
            else "current"
        )
        snapshots.append(
            {
                "symbol": symbol,
                "label": label,
                "role": role,
                "latest_data_date": latest_date,
                "expected_data_date": expected_trade_date,
                "freshness_status": freshness_status,
                "is_current": freshness_status == "current",
                "close": close,
                "previous_close": previous_close,
                "change": change,
                "change_pct": change_pct,
                "volume": latest.trade_volume if latest is not None else None,
                "provider": latest.provider if latest is not None else None,
                "point_count": len(rows),
            }
        )
    return snapshots


def get_jp_market_overview(
    db: Session,
    *,
    now: datetime | None = None,
    sector_limit: int = 10,
    mover_limit: int = 5,
) -> dict:
    resolved_sector_limit = max(1, min(sector_limit, 33))
    resolved_mover_limit = max(1, min(mover_limit, 20))
    expected_trade_date = expected_jp_daily_price_date(now=now)
    calendar_status = build_jp_calendar_status(now=now)
    active_stock_count = (
        db.query(JPStockMaster)
        .filter(
            JPStockMaster.is_active.is_(True),
            JPStockMaster.asset_type == "stock",
        )
        .count()
    )
    recent_by_symbol = _jp_market_overview_recent_rows(
        db,
        expected_trade_date=expected_trade_date,
    )
    observed_symbol_count = len(recent_by_symbol)
    current_rows: list[dict] = []
    stale_symbol_count = 0
    mover_rows: list[dict] = []
    sector_totals: dict[str, dict[str, float | int]] = {}
    breadth = {
        "advance_count": 0,
        "decline_count": 0,
        "unchanged_count": 0,
        "no_comparison_count": 0,
    }

    for rows in recent_by_symbol.values():
        latest = rows[0]
        if latest["trade_date"] != expected_trade_date:
            stale_symbol_count += 1
            continue
        current_rows.append(latest)
        previous = rows[1] if len(rows) > 1 else None
        close = latest["close_price"]
        if close is None:
            close = latest["adjusted_close"]
        previous_close = None
        if previous is not None:
            previous_close = previous["close_price"]
            if previous_close is None:
                previous_close = previous["adjusted_close"]
        sector = str(latest["sector_33_name"] or "Unclassified")
        sector_total = sector_totals.setdefault(
            sector,
            {
                "covered_count": 0,
                "advance_count": 0,
                "decline_count": 0,
                "unchanged_count": 0,
                "change_pct_sum": 0.0,
                "change_pct_count": 0,
            },
        )
        sector_total["covered_count"] += 1
        if close is None or previous_close in {None, 0}:
            breadth["no_comparison_count"] += 1
            continue

        change = float(close) - float(previous_close)
        change_pct = change / float(previous_close) * 100
        direction = (
            "advance_count"
            if change > 0
            else "decline_count"
            if change < 0
            else "unchanged_count"
        )
        breadth[direction] += 1
        sector_total[direction] += 1
        sector_total["change_pct_sum"] += change_pct
        sector_total["change_pct_count"] += 1
        mover_rows.append(
            {
                "symbol": latest["symbol"],
                "security_name": latest["security_name"],
                "sector": latest["sector_33_name"],
                "trade_date": latest["trade_date"],
                "close": float(close),
                "previous_close": float(previous_close),
                "change": change,
                "change_pct": change_pct,
                "volume": latest["trade_volume"],
                "provider": latest["provider"],
            }
        )

    current_symbol_count = len(current_rows)
    missing_symbol_count = max(active_stock_count - observed_symbol_count, 0)
    coverage_status = (
        "current"
        if active_stock_count > 0 and current_symbol_count == active_stock_count
        else "partial"
        if current_symbol_count > 0
        else "missing"
    )
    sectors = []
    for sector, totals in sector_totals.items():
        change_count = int(totals["change_pct_count"])
        sectors.append(
            {
                "sector": sector,
                "covered_count": int(totals["covered_count"]),
                "advance_count": int(totals["advance_count"]),
                "decline_count": int(totals["decline_count"]),
                "unchanged_count": int(totals["unchanged_count"]),
                "average_change_pct": (
                    float(totals["change_pct_sum"]) / change_count
                    if change_count
                    else None
                ),
            }
        )
    sectors.sort(key=lambda item: (-item["covered_count"], item["sector"]))

    watchlist_ranking = get_jp_watchlist_ranking(
        db=db,
        group_id=None,
        include_children=True,
        enabled_only=True,
        rank_by="none",
        sort_order="asc",
        expected_trade_date=expected_trade_date,
        now=now,
    )
    watchlist_coverage = {
        key: watchlist_ranking.get(key)
        for key in (
            "requested_symbol_count",
            "ranked_count",
            "no_data_count",
            "target_trade_date",
            "is_current",
            "current_symbol_count",
            "stale_symbol_count",
            "missing_symbol_count",
            "future_symbol_count",
            "coverage_status",
            "refresh_recommended",
        )
    }
    indices = _jp_market_index_snapshots(
        db,
        expected_trade_date=expected_trade_date,
    )
    source_health = build_jp_source_health(
        db,
        expected_daily_price_date=expected_trade_date,
        use_expected_date=True,
    )
    warnings = [
        "JP breadth is computed from active stock-master symbols with local daily-price coverage; it is not full-exchange breadth."
    ]
    if missing_symbol_count or stale_symbol_count:
        warnings.append(
            "JP active-master coverage is partial: "
            f"current={current_symbol_count}, stale={stale_symbol_count}, "
            f"missing={missing_symbol_count}, active={active_stock_count}."
        )
    stale_indices = [
        item["symbol"] for item in indices if not item["is_current"]
    ]
    if stale_indices:
        warnings.append(
            "JP benchmark data is not current: " + ", ".join(stale_indices)
        )

    mover_rows.sort(key=lambda item: item["change_pct"], reverse=True)
    refresh_recommended = bool(
        watchlist_coverage.get("refresh_recommended") or stale_indices
    )
    return {
        "kind": "jp_market_overview",
        "generated_at": utc_now(),
        "expected_trade_date": expected_trade_date,
        "calendar_status": calendar_status,
        "coverage": {
            "scope": "active_jp_stock_master_with_local_daily_prices",
            "universe_type": "active_local_stock_master",
            "is_full_market": False,
            "coverage_limitation": (
                "local_active_master_and_cached_daily_prices_not_official_"
                "full_exchange_breadth"
            ),
            "active_stock_count": active_stock_count,
            "observed_symbol_count": observed_symbol_count,
            "current_symbol_count": current_symbol_count,
            "stale_symbol_count": stale_symbol_count,
            "missing_symbol_count": missing_symbol_count,
            "active_coverage_ratio": (
                current_symbol_count / active_stock_count
                if active_stock_count
                else 0.0
            ),
            "observed_current_ratio": (
                current_symbol_count / observed_symbol_count
                if observed_symbol_count
                else 0.0
            ),
            "status": coverage_status,
            "is_partial": coverage_status != "current",
        },
        "watchlist_coverage": watchlist_coverage,
        "breadth": {
            "trade_date": expected_trade_date if current_symbol_count else None,
            **breadth,
            "total_count": sum(breadth.values()),
            "coverage_count": current_symbol_count,
            "universe_count": active_stock_count,
            "coverage_ratio": (
                current_symbol_count / active_stock_count
                if active_stock_count
                else None
            ),
            "classified_count": (
                breadth["advance_count"]
                + breadth["decline_count"]
                + breadth["unchanged_count"]
            ),
            "unknown_count": max(
                active_stock_count
                - breadth["advance_count"]
                - breadth["decline_count"]
                - breadth["unchanged_count"],
                0,
            ),
            "reconciliation_status": (
                "balanced"
                if coverage_status == "current"
                and breadth["no_comparison_count"] == 0
                else "partial"
            ),
            "reconciliation_formula": (
                "advance_count+decline_count+unchanged_count+unknown_count=universe_count"
            ),
            "market": "JP",
            "scope": "active_stock_master_local_daily_coverage",
            "status": (
                "ready"
                if coverage_status == "current"
                and breadth["no_comparison_count"] == 0
                else "partial"
                if current_symbol_count
                else "missing"
            ),
            "source": "omi_local_jp_daily_price_partial",
            "is_partial": coverage_status != "current",
            "direct_market_breadth": True,
            "proxy_used": False,
            "is_full_market": False,
            "universe_type": "active_local_stock_master",
            "coverage_limitation": (
                "local_active_master_and_cached_daily_prices_not_official_"
                "full_exchange_breadth"
            ),
        },
        "sectors": sectors[:resolved_sector_limit],
        "indices": indices,
        "top_gainers": mover_rows[:resolved_mover_limit],
        "top_losers": list(reversed(mover_rows[-resolved_mover_limit:])),
        "source_health": source_health,
        "refresh_recommended": refresh_recommended,
        "refresh_scope": "configured_watchlists_and_index_proxies",
        "warnings": warnings,
    }


def get_jp_watchlist_technical_radar(
    db: Session,
    *,
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    mode: str = "action",
    max_results: int = 30,
    calculation_limit: int = 100,
) -> dict:
    ranking = get_jp_watchlist_ranking(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
        rank_by="none",
        sort_order="asc",
    )
    symbols = [
        normalize_jp_symbol(row.get("symbol"))
        for row in ranking.get("results", [])
        if normalize_jp_symbol(row.get("symbol"))
    ]
    histories: dict[str, list[TechnicalRadarBar]] = {}

    for symbol in symbols:
        daily_rows = _latest_distinct_jp_daily_rows(
            db=db,
            symbol=symbol,
            limit=calculation_limit,
        )
        histories[symbol] = [
            TechnicalRadarBar(
                trade_date=row.trade_date,
                open=row.open_price,
                high=row.high_price,
                low=row.low_price,
                close=_jp_close_value(row),
                volume=row.trade_volume,
            )
            for row in daily_rows
        ]

    radar = build_technical_watchlist_radar(
        ranking=ranking,
        histories=histories,
        market="JP",
        include_children=include_children,
        mode=mode,
        max_results=max_results,
    )
    radar["group_id"] = radar.get("group_id") or group_id
    return radar


def upsert_jp_daily_price_records(
    db: Session,
    records: list[JPDailyPriceRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(JPDailyPrice)
            .filter(JPDailyPrice.provider == record.provider)
            .filter(JPDailyPrice.symbol == record.symbol)
            .filter(JPDailyPrice.trade_date == record.trade_date)
            .first()
        )

        if existing is None:
            db.add(
                JPDailyPrice(
                    provider=record.provider,
                    symbol=record.symbol,
                    trade_date=record.trade_date,
                    currency=record.currency,
                    open_price=record.open_price,
                    high_price=record.high_price,
                    low_price=record.low_price,
                    close_price=record.close_price,
                    adjusted_close=record.adjusted_close,
                    trade_volume=record.trade_volume,
                    source_url=record.source_url,
                    raw_payload_hash=record.raw_payload_hash,
                    fetched_at=utc_now(),
                )
            )
            inserted_count += 1
            continue

        existing.currency = record.currency
        existing.open_price = record.open_price
        existing.high_price = record.high_price
        existing.low_price = record.low_price
        existing.close_price = record.close_price
        existing.adjusted_close = record.adjusted_close
        existing.trade_volume = record.trade_volume
        existing.source_url = record.source_url
        existing.raw_payload_hash = record.raw_payload_hash
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
    }


def _yahoo_daily_range_for_outputsize(outputsize: str) -> str:
    if outputsize == "compact":
        return YAHOO_CHART_COMPACT_RANGE

    return YAHOO_CHART_FULL_RANGE


def refresh_jp_daily_prices_from_yahoo_chart(
    db: Session,
    *,
    symbol: str,
    outputsize: str = "compact",
) -> dict:
    if outputsize not in {"compact", "full"}:
        raise ValueError("outputsize must be one of: compact, full.")

    normalized_symbol = _valid_symbol(symbol)
    payload, source_url = fetch_yahoo_chart_payload(
        symbol=normalized_symbol,
        range_value=_yahoo_daily_range_for_outputsize(outputsize),
        interval="1d",
        timeout_seconds=settings.jp_market_http_timeout_seconds,
    )
    upsert_jp_stock_record(
        db,
        parse_yahoo_stock_record(payload, symbol=normalized_symbol),
    )
    records = parse_yahoo_daily_prices(
        payload,
        symbol=normalized_symbol,
        source_url=source_url,
    )
    result = upsert_jp_daily_price_records(db, records)

    return {
        "status": "success",
        "provider": "yahoo_chart",
        "symbol": normalized_symbol,
        "fetched_count": len(records),
        "inserted_count": result["inserted_count"],
        "updated_count": result["updated_count"],
        "message": "JP daily prices refreshed from Yahoo chart.",
    }


@_translate_jp_provider_errors
def refresh_jp_daily_prices(
    db: Session,
    *,
    symbol: str,
    outputsize: str = "compact",
    provider: str = "auto",
) -> dict:
    normalized_provider = provider.strip().lower()
    if normalized_provider not in {"auto", "yahoo_chart"}:
        raise ValueError("provider must be one of: auto, yahoo_chart.")

    return refresh_jp_daily_prices_from_yahoo_chart(
        db=db,
        symbol=symbol,
        outputsize=outputsize,
    )


def upsert_jp_company_fundamental_records(
    db: Session,
    records: list[JPCompanyFundamentalRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(JPCompanyFundamental)
            .filter(JPCompanyFundamental.provider == record.provider)
            .filter(JPCompanyFundamental.symbol == record.symbol)
            .first()
        )

        if existing is None:
            db.add(
                JPCompanyFundamental(
                    provider=record.provider,
                    symbol=record.symbol,
                    company_name=record.company_name,
                    exchange=record.exchange,
                    sector=record.sector,
                    industry=record.industry,
                    currency=record.currency,
                    market_cap=record.market_cap,
                    enterprise_value=record.enterprise_value,
                    trailing_pe=record.trailing_pe,
                    forward_pe=record.forward_pe,
                    price_to_book=record.price_to_book,
                    dividend_yield=record.dividend_yield,
                    beta=record.beta,
                    disclosed_date=record.disclosed_date,
                    fiscal_period=record.fiscal_period,
                    fiscal_year_end=record.fiscal_year_end,
                    document_type=record.document_type,
                    eps_ttm=record.eps_ttm,
                    forward_eps=record.forward_eps,
                    revenue_ttm=record.revenue_ttm,
                    net_sales=record.net_sales,
                    operating_profit=record.operating_profit,
                    ordinary_profit=record.ordinary_profit,
                    profit=record.profit,
                    forecast_net_sales=record.forecast_net_sales,
                    forecast_operating_profit=record.forecast_operating_profit,
                    forecast_ordinary_profit=record.forecast_ordinary_profit,
                    forecast_profit=record.forecast_profit,
                    gross_margin=record.gross_margin,
                    operating_margin=record.operating_margin,
                    profit_margin=record.profit_margin,
                    return_on_equity=record.return_on_equity,
                    return_on_assets=record.return_on_assets,
                    revenue_growth=record.revenue_growth,
                    earnings_growth=record.earnings_growth,
                    total_assets=record.total_assets,
                    equity=record.equity,
                    equity_to_asset_ratio=record.equity_to_asset_ratio,
                    total_cash=record.total_cash,
                    total_debt=record.total_debt,
                    operating_cash_flow=record.operating_cash_flow,
                    investing_cash_flow=record.investing_cash_flow,
                    financing_cash_flow=record.financing_cash_flow,
                    debt_to_equity=record.debt_to_equity,
                    current_ratio=record.current_ratio,
                    quick_ratio=record.quick_ratio,
                    shares_outstanding=record.shares_outstanding,
                    book_value=record.book_value,
                    earnings_date=record.earnings_date,
                    ex_dividend_date=record.ex_dividend_date,
                    source_url=record.source_url,
                    raw_payload_hash=record.raw_payload_hash,
                    fetched_at=utc_now(),
                )
            )
            inserted_count += 1
            continue

        existing.company_name = record.company_name
        existing.exchange = record.exchange
        existing.sector = record.sector
        existing.industry = record.industry
        existing.currency = record.currency
        existing.market_cap = record.market_cap
        existing.enterprise_value = record.enterprise_value
        existing.trailing_pe = record.trailing_pe
        existing.forward_pe = record.forward_pe
        existing.price_to_book = record.price_to_book
        existing.dividend_yield = record.dividend_yield
        existing.beta = record.beta
        existing.disclosed_date = record.disclosed_date
        existing.fiscal_period = record.fiscal_period
        existing.fiscal_year_end = record.fiscal_year_end
        existing.document_type = record.document_type
        existing.eps_ttm = record.eps_ttm
        existing.forward_eps = record.forward_eps
        existing.revenue_ttm = record.revenue_ttm
        existing.net_sales = record.net_sales
        existing.operating_profit = record.operating_profit
        existing.ordinary_profit = record.ordinary_profit
        existing.profit = record.profit
        existing.forecast_net_sales = record.forecast_net_sales
        existing.forecast_operating_profit = record.forecast_operating_profit
        existing.forecast_ordinary_profit = record.forecast_ordinary_profit
        existing.forecast_profit = record.forecast_profit
        existing.gross_margin = record.gross_margin
        existing.operating_margin = record.operating_margin
        existing.profit_margin = record.profit_margin
        existing.return_on_equity = record.return_on_equity
        existing.return_on_assets = record.return_on_assets
        existing.revenue_growth = record.revenue_growth
        existing.earnings_growth = record.earnings_growth
        existing.total_assets = record.total_assets
        existing.equity = record.equity
        existing.equity_to_asset_ratio = record.equity_to_asset_ratio
        existing.total_cash = record.total_cash
        existing.total_debt = record.total_debt
        existing.operating_cash_flow = record.operating_cash_flow
        existing.investing_cash_flow = record.investing_cash_flow
        existing.financing_cash_flow = record.financing_cash_flow
        existing.debt_to_equity = record.debt_to_equity
        existing.current_ratio = record.current_ratio
        existing.quick_ratio = record.quick_ratio
        existing.shares_outstanding = record.shares_outstanding
        existing.book_value = record.book_value
        existing.earnings_date = record.earnings_date
        existing.ex_dividend_date = record.ex_dividend_date
        existing.source_url = record.source_url
        existing.raw_payload_hash = record.raw_payload_hash
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    db.commit()

    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
    }


def upsert_jp_margin_interest_records(
    db: Session,
    records: list[JPMarginInterestRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(JPMarginInterest)
            .filter(JPMarginInterest.provider == record.provider)
            .filter(JPMarginInterest.symbol == record.symbol)
            .filter(JPMarginInterest.report_date == record.report_date)
            .first()
        )

        if existing is None:
            db.add(
                JPMarginInterest(
                    provider=record.provider,
                    symbol=record.symbol,
                    report_date=record.report_date,
                    short_volume=record.short_volume,
                    long_volume=record.long_volume,
                    short_negotiable_volume=record.short_negotiable_volume,
                    long_negotiable_volume=record.long_negotiable_volume,
                    short_standardized_volume=record.short_standardized_volume,
                    long_standardized_volume=record.long_standardized_volume,
                    issue_type=record.issue_type,
                    source_url=record.source_url,
                    raw_payload_hash=record.raw_payload_hash,
                    fetched_at=utc_now(),
                )
            )
            inserted_count += 1
            continue

        existing.short_volume = record.short_volume
        existing.long_volume = record.long_volume
        existing.short_negotiable_volume = record.short_negotiable_volume
        existing.long_negotiable_volume = record.long_negotiable_volume
        existing.short_standardized_volume = record.short_standardized_volume
        existing.long_standardized_volume = record.long_standardized_volume
        existing.issue_type = record.issue_type
        existing.source_url = record.source_url
        existing.raw_payload_hash = record.raw_payload_hash
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    db.commit()

    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
    }


def upsert_jp_investor_type_records(
    db: Session,
    records: list[JPInvestorTypeRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(JPInvestorType)
            .filter(JPInvestorType.provider == record.provider)
            .filter(JPInvestorType.section == record.section)
            .filter(JPInvestorType.published_date == record.published_date)
            .filter(JPInvestorType.start_date == record.start_date)
            .filter(JPInvestorType.end_date == record.end_date)
            .first()
        )

        values = {
            "proprietary_sell": record.proprietary_sell,
            "proprietary_buy": record.proprietary_buy,
            "proprietary_total": record.proprietary_total,
            "proprietary_balance": record.proprietary_balance,
            "broker_sell": record.broker_sell,
            "broker_buy": record.broker_buy,
            "broker_total": record.broker_total,
            "broker_balance": record.broker_balance,
            "total_sell": record.total_sell,
            "total_buy": record.total_buy,
            "total_traded": record.total_traded,
            "total_balance": record.total_balance,
            "individual_sell": record.individual_sell,
            "individual_buy": record.individual_buy,
            "individual_total": record.individual_total,
            "individual_balance": record.individual_balance,
            "foreign_sell": record.foreign_sell,
            "foreign_buy": record.foreign_buy,
            "foreign_total": record.foreign_total,
            "foreign_balance": record.foreign_balance,
            "investment_trust_sell": record.investment_trust_sell,
            "investment_trust_buy": record.investment_trust_buy,
            "investment_trust_total": record.investment_trust_total,
            "investment_trust_balance": record.investment_trust_balance,
            "trust_bank_sell": record.trust_bank_sell,
            "trust_bank_buy": record.trust_bank_buy,
            "trust_bank_total": record.trust_bank_total,
            "trust_bank_balance": record.trust_bank_balance,
            "source_url": record.source_url,
            "raw_payload_hash": record.raw_payload_hash,
        }

        if existing is None:
            db.add(
                JPInvestorType(
                    provider=record.provider,
                    section=record.section,
                    published_date=record.published_date,
                    start_date=record.start_date,
                    end_date=record.end_date,
                    fetched_at=utc_now(),
                    **values,
                )
            )
            inserted_count += 1
            continue

        for field, value in values.items():
            setattr(existing, field, value)
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    db.commit()

    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
    }


def refresh_jp_company_fundamental_from_yahoo_quote_summary(
    db: Session,
    *,
    symbol: str,
) -> dict:
    normalized_symbol = _valid_symbol(symbol)
    payload, source_url = fetch_yahoo_quote_summary_payload(
        symbol=normalized_symbol,
        timeout_seconds=settings.jp_market_http_timeout_seconds,
    )
    record = parse_yahoo_company_fundamental(
        payload,
        symbol=normalized_symbol,
        source_url=source_url,
    )
    result = upsert_jp_company_fundamental_records(db, [record])

    return {
        "status": "success",
        "provider": "yahoo_quote_summary",
        "symbol": record.symbol,
        "fetched_count": 1,
        "inserted_count": result["inserted_count"],
        "updated_count": result["updated_count"],
        "message": "JP company fundamentals refreshed from Yahoo quote summary.",
    }


def _cached_jquants_id_token(*, refresh_token: str) -> str:
    global _jquants_id_token_cache

    now = time.monotonic()
    cache = _jquants_id_token_cache
    if (
        cache
        and cache.get("refresh_token") == refresh_token
        and isinstance(cache.get("expires_at"), float)
        and now < float(cache["expires_at"])
    ):
        cached_token = str(cache.get("id_token") or "")
        if cached_token:
            return cached_token

    id_token = fetch_jquants_id_token(
        base_url=settings.jquants_api_base_url,
        refresh_token=refresh_token,
        timeout_seconds=settings.jp_market_http_timeout_seconds,
    )
    ttl_seconds = max(int(settings.jquants_id_token_cache_seconds or 0), 0)
    if ttl_seconds > 0:
        _jquants_id_token_cache = {
            "refresh_token": refresh_token,
            "id_token": id_token,
            "expires_at": now + ttl_seconds,
        }
    else:
        _jquants_id_token_cache = None

    return id_token


def _configured_jquants_id_token() -> str | None:
    configured_id_token = (settings.jquants_id_token or "").strip()
    if configured_id_token:
        return configured_id_token

    configured_refresh_token = (settings.jquants_refresh_token or "").strip()
    if not configured_refresh_token:
        mail_address = (settings.jquants_mail_address or "").strip()
        password = (settings.jquants_password or "").strip()
        if not mail_address or not password:
            return None

        configured_refresh_token = fetch_jquants_refresh_token(
            base_url=settings.jquants_api_base_url,
            mail_address=mail_address,
            password=password,
            timeout_seconds=settings.jp_market_http_timeout_seconds,
        )

    return _cached_jquants_id_token(refresh_token=configured_refresh_token)


def _configured_jquants_api_key() -> str | None:
    configured_api_key = (settings.jquants_api_key or "").strip()
    if configured_api_key:
        return configured_api_key

    if settings.jquants_api_base_url.rstrip("/").endswith("/v2"):
        legacy_refresh_token_slot = (settings.jquants_refresh_token or "").strip()
        if legacy_refresh_token_slot:
            return legacy_refresh_token_slot

    return None


def _jquants_data_count(payload: dict) -> int:
    rows = payload.get("data")
    return len(rows) if isinstance(rows, list) else 0


def _jquants_resource_error_result(
    *,
    exc: JPMarketDataFetchError,
    provider: str,
    symbol: str,
) -> dict | None:
    message = str(exc)
    if "HTTP 429" in message:
        return {
            "status": "rate_limited",
            "provider": provider,
            "symbol": symbol,
            "fetched_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "message": "J-Quants API rate limit reached. Please wait before updating again.",
        }

    if "HTTP 403" in message:
        return {
            "status": "skipped",
            "provider": provider,
            "symbol": symbol,
            "fetched_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "message": "J-Quants plan or API key does not allow this Japan market resource.",
        }

    return None


def _jp_investor_section_for_stock(stock: JPStockMaster | None) -> str | None:
    segment = (stock.market_segment or "").lower() if stock is not None else ""
    if "prime" in segment:
        return "TSEPrime"
    if "standard" in segment:
        return "TSEStandard"
    if "growth" in segment or "mothers" in segment:
        return "TSEGrowth"

    return None


def refresh_jp_margin_interest_from_jquants(
    db: Session,
    *,
    symbol: str,
) -> dict:
    normalized_symbol = _valid_symbol(symbol)
    api_key = _configured_jquants_api_key()
    if api_key is None:
        return {
            "status": "skipped",
            "provider": JP_MARGIN_INTEREST_PROVIDER,
            "symbol": normalized_symbol,
            "fetched_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "message": "J-Quants API key is not configured.",
        }

    to_date = utc_now().date()
    from_date = to_date - timedelta(days=180)
    try:
        payload, source_url = fetch_jquants_margin_interest_payload(
            base_url=settings.jquants_api_base_url,
            api_key=api_key,
            local_code=local_code_from_symbol(normalized_symbol),
            from_date=from_date,
            to_date=to_date,
            timeout_seconds=settings.jp_market_http_timeout_seconds,
        )
    except JPMarketDataFetchError as exc:
        result = _jquants_resource_error_result(
            exc=exc,
            provider=JP_MARGIN_INTEREST_PROVIDER,
            symbol=normalized_symbol,
        )
        if result is not None:
            return result
        raise

    records = parse_jquants_margin_interest_records(
        payload,
        symbol=normalized_symbol,
        source_url=source_url,
    )
    if not records:
        return {
            "status": "empty",
            "provider": JP_MARGIN_INTEREST_PROVIDER,
            "symbol": normalized_symbol,
            "fetched_count": _jquants_data_count(payload),
            "inserted_count": 0,
            "updated_count": 0,
            "message": "J-Quants margin-interest returned no rows for this symbol.",
        }

    result = upsert_jp_margin_interest_records(db, records)
    return {
        "status": "success",
        "provider": JP_MARGIN_INTEREST_PROVIDER,
        "symbol": normalized_symbol,
        "fetched_count": len(records),
        "inserted_count": result["inserted_count"],
        "updated_count": result["updated_count"],
        "message": "JP margin interest refreshed from J-Quants.",
    }


def refresh_jp_investor_types_from_jquants(
    db: Session,
    *,
    symbol: str,
) -> dict:
    normalized_symbol = _valid_symbol(symbol)
    api_key = _configured_jquants_api_key()
    if api_key is None:
        return {
            "status": "skipped",
            "provider": JP_INVESTOR_TYPES_PROVIDER,
            "symbol": normalized_symbol,
            "fetched_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "message": "J-Quants API key is not configured.",
        }

    stock = (
        db.query(JPStockMaster)
        .filter(JPStockMaster.symbol == normalized_symbol)
        .first()
    )
    section = _jp_investor_section_for_stock(stock)
    if section is None:
        return {
            "status": "skipped",
            "provider": JP_INVESTOR_TYPES_PROVIDER,
            "symbol": normalized_symbol,
            "fetched_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "message": "JP investor-types requires a known market segment for the selected symbol.",
        }

    to_date = utc_now().date()
    from_date = to_date - timedelta(days=180)
    try:
        payload, source_url = fetch_jquants_investor_types_payload(
            base_url=settings.jquants_api_base_url,
            api_key=api_key,
            section=section,
            from_date=from_date,
            to_date=to_date,
            timeout_seconds=settings.jp_market_http_timeout_seconds,
        )
    except JPMarketDataFetchError as exc:
        result = _jquants_resource_error_result(
            exc=exc,
            provider=JP_INVESTOR_TYPES_PROVIDER,
            symbol=normalized_symbol,
        )
        if result is not None:
            return result
        raise

    records = parse_jquants_investor_type_records(
        payload,
        source_url=source_url,
    )
    if not records:
        return {
            "status": "empty",
            "provider": JP_INVESTOR_TYPES_PROVIDER,
            "symbol": normalized_symbol,
            "fetched_count": _jquants_data_count(payload),
            "inserted_count": 0,
            "updated_count": 0,
            "message": "J-Quants investor-types returned no rows for this section.",
        }

    result = upsert_jp_investor_type_records(db, records)
    return {
        "status": "success",
        "provider": JP_INVESTOR_TYPES_PROVIDER,
        "symbol": normalized_symbol,
        "fetched_count": len(records),
        "inserted_count": result["inserted_count"],
        "updated_count": result["updated_count"],
        "message": "JP investor types refreshed from J-Quants.",
    }


@_translate_jp_provider_errors
def refresh_jp_market_resource(
    db: Session,
    *,
    symbol: str,
    resource: str,
) -> dict:
    normalized_resource = resource.strip().lower()
    if normalized_resource == "demand":
        return refresh_jp_margin_interest_from_jquants(db=db, symbol=symbol)
    if normalized_resource == "investors":
        return refresh_jp_investor_types_from_jquants(db=db, symbol=symbol)
    if normalized_resource == "performance" or normalized_resource == "financials":
        return refresh_jp_company_fundamental(db=db, symbol=symbol, provider="auto")
    if normalized_resource == "disclosures":
        normalized_symbol = _valid_symbol(symbol)
        return {
            "status": "skipped",
            "provider": "jquants_tdnet",
            "symbol": normalized_symbol,
            "fetched_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "message": "TDnet disclosures require a J-Quants add-on plan and are not refreshed in the base pipeline.",
        }

    raise ValueError("resource must be one of: demand, investors, disclosures, performance, financials.")


def _jquants_statement_count(payload: dict) -> int:
    rows = payload.get("statements")
    if rows is None:
        rows = payload.get("data")

    return len(rows) if isinstance(rows, list) else 0


def refresh_jp_company_fundamental_from_jquants_statements(
    db: Session,
    *,
    symbol: str,
) -> dict:
    normalized_symbol = _valid_symbol(symbol)
    api_key = _configured_jquants_api_key()
    id_token = None if api_key else _configured_jquants_id_token()
    if api_key is None and id_token is None:
        return {
            "status": "skipped",
            "provider": "jquants_statements",
            "symbol": normalized_symbol,
            "fetched_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "message": "J-Quants credentials are not configured.",
        }

    stock = (
        db.query(JPStockMaster)
        .filter(JPStockMaster.symbol == normalized_symbol)
        .first()
    )
    local_code = normalized_symbol.split(".", maxsplit=1)[0]
    if api_key:
        payload, source_url = fetch_jquants_summary_payload(
            base_url=settings.jquants_api_base_url,
            api_key=api_key,
            local_code=local_code,
            timeout_seconds=settings.jp_market_http_timeout_seconds,
        )
    else:
        assert id_token is not None
        payload, source_url = fetch_jquants_statements_payload(
            base_url=settings.jquants_api_base_url,
            id_token=id_token,
            local_code=local_code,
            timeout_seconds=settings.jp_market_http_timeout_seconds,
        )
    record = parse_jquants_company_fundamental(
        payload,
        symbol=normalized_symbol,
        source_url=source_url,
        company_name=stock.security_name if stock else None,
        exchange=stock.exchange if stock else None,
        sector=stock.sector_33_name if stock else None,
        industry=stock.sector_17_name if stock else None,
    )
    if record is None:
        return {
            "status": "empty",
            "provider": "jquants_statements",
            "symbol": normalized_symbol,
            "fetched_count": _jquants_statement_count(payload),
            "inserted_count": 0,
            "updated_count": 0,
            "message": "J-Quants statements returned no financial statement rows.",
        }

    result = upsert_jp_company_fundamental_records(db, [record])

    return {
        "status": "success",
        "provider": "jquants_statements",
        "symbol": record.symbol,
        "fetched_count": _jquants_statement_count(payload),
        "inserted_count": result["inserted_count"],
        "updated_count": result["updated_count"],
        "message": "JP company fundamentals refreshed from J-Quants summary.",
    }


def _combine_jp_fundamental_refresh_results(
    *,
    symbol: str,
    results: list[dict],
    failures: list[tuple[str, str]],
) -> dict:
    successful_results = [result for result in results if result.get("status") == "success"]
    non_success_results = [result for result in results if result.get("status") != "success"]
    provider_values = [
        str(result.get("provider"))
        for result in successful_results or results
        if result.get("provider")
    ]
    provider = "+".join(dict.fromkeys(provider_values)) or "auto"

    if successful_results and failures:
        status_value = "partial_success"
    elif successful_results and non_success_results:
        status_value = "partial_success"
    elif successful_results:
        status_value = "success"
    elif failures:
        status_value = "error"
    elif any(result.get("status") == "empty" for result in results):
        status_value = "empty"
    else:
        status_value = "skipped"

    message_parts = [
        str(result.get("message"))
        for result in results
        if result.get("message")
    ]
    message_parts.extend(
        f"{provider_name} failed: {message}"
        for provider_name, message in failures
    )

    return {
        "status": status_value,
        "provider": provider,
        "symbol": symbol,
        "fetched_count": sum(int(result.get("fetched_count") or 0) for result in results),
        "inserted_count": sum(int(result.get("inserted_count") or 0) for result in results),
        "updated_count": sum(int(result.get("updated_count") or 0) for result in results),
        "message": " ".join(message_parts) or "JP company fundamental refresh completed.",
    }


def _run_jp_fundamental_provider_refresh(
    callback: Callable[[], dict],
) -> tuple[dict | None, str | None]:
    try:
        return callback(), None
    except (JPMarketDataFetchError, requests.RequestException) as exc:
        return None, str(exc)


@_translate_jp_provider_errors
def refresh_jp_company_fundamental(
    db: Session,
    *,
    symbol: str,
    provider: str = "auto",
) -> dict:
    normalized_symbol = _valid_symbol(symbol)
    normalized_provider = provider.strip().lower()
    if normalized_provider not in JP_FUNDAMENTAL_PROVIDER_SET:
        raise ValueError("provider must be one of: auto, jquants_statements, yahoo_quote_summary.")

    if normalized_provider == JP_FUNDAMENTAL_PRIMARY_PROVIDER:
        return refresh_jp_company_fundamental_from_jquants_statements(
            db=db,
            symbol=normalized_symbol,
        )

    if normalized_provider == JP_FUNDAMENTAL_SUPPLEMENTAL_PROVIDER:
        return refresh_jp_company_fundamental_from_yahoo_quote_summary(
            db=db,
            symbol=normalized_symbol,
        )

    results: list[dict] = []
    failures: list[tuple[str, str]] = []

    jquants_result, jquants_error = _run_jp_fundamental_provider_refresh(
        lambda: refresh_jp_company_fundamental_from_jquants_statements(
            db=db,
            symbol=normalized_symbol,
        )
    )
    if jquants_result is not None:
        results.append(jquants_result)
    if jquants_error:
        db.rollback()
        failures.append((JP_FUNDAMENTAL_PRIMARY_PROVIDER, jquants_error))

    if jquants_result is None or jquants_result.get("status") != "success":
        yahoo_result, yahoo_error = _run_jp_fundamental_provider_refresh(
            lambda: refresh_jp_company_fundamental_from_yahoo_quote_summary(
                db=db,
                symbol=normalized_symbol,
            )
        )
        if yahoo_result is not None:
            results.append(yahoo_result)
        if yahoo_error:
            db.rollback()
            failures.append((JP_FUNDAMENTAL_SUPPLEMENTAL_PROVIDER, yahoo_error))

    return _combine_jp_fundamental_refresh_results(
        symbol=normalized_symbol,
        results=results,
        failures=failures,
    )


def _jp_fundamental_provider_rank(provider: str | None) -> int:
    if provider in JP_FUNDAMENTAL_PROVIDER_PRIORITY:
        return JP_FUNDAMENTAL_PROVIDER_PRIORITY.index(provider)
    return len(JP_FUNDAMENTAL_PROVIDER_PRIORITY)


def _datetime_score(value: object) -> float:
    if isinstance(value, datetime):
        return value.timestamp()
    return -1


def _jp_fundamental_sort_key(row: JPCompanyFundamental) -> tuple[int, float, int]:
    return (
        _jp_fundamental_provider_rank(row.provider),
        -_datetime_score(row.fetched_at),
        -(row.id or 0),
    )


def _first_non_null_attr(rows: list[JPCompanyFundamental], field: str):
    for row in rows:
        value = getattr(row, field)
        if value is not None:
            return value
    return None


def _latest_datetime_attr(rows: list[JPCompanyFundamental], field: str):
    candidates = [
        (score, getattr(row, field))
        for row in rows
        if (score := _datetime_score(getattr(row, field))) >= 0
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _merge_jp_company_fundamental_rows(
    rows: list[JPCompanyFundamental],
) -> JPCompanyFundamental | SimpleNamespace | None:
    if not rows:
        return None
    if len(rows) == 1:
        return rows[0]

    ordered_rows = sorted(rows, key=_jp_fundamental_sort_key)
    provider_label = "+".join(dict.fromkeys(row.provider for row in ordered_rows if row.provider))
    values = {}
    for field in JP_COMPANY_FUNDAMENTAL_FIELDS:
        if field == "provider":
            values[field] = provider_label
        elif field == "id":
            values[field] = ordered_rows[0].id
        elif field in {"fetched_at", "created_at", "updated_at"}:
            values[field] = _latest_datetime_attr(ordered_rows, field)
        else:
            values[field] = _first_non_null_attr(ordered_rows, field)

    return SimpleNamespace(**values)


def get_jp_company_fundamental(
    db: Session,
    *,
    symbol: str,
    provider: str | None = None,
) -> JPCompanyFundamental | SimpleNamespace | None:
    normalized_symbol = _valid_symbol(symbol)
    query = db.query(JPCompanyFundamental).filter(JPCompanyFundamental.symbol == normalized_symbol)

    if provider is not None:
        query = query.filter(JPCompanyFundamental.provider == provider)
        return query.order_by(
            JPCompanyFundamental.fetched_at.desc(),
            JPCompanyFundamental.id.desc(),
        ).first()

    rows = query.order_by(
        JPCompanyFundamental.fetched_at.desc(),
        JPCompanyFundamental.id.desc(),
    ).all()
    return _merge_jp_company_fundamental_rows(rows)


def list_jp_company_fundamentals(
    db: Session,
    *,
    provider: str | None = None,
    sector: str | None = None,
    industry: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[JPCompanyFundamental]:
    query = db.query(JPCompanyFundamental)

    if provider is not None:
        query = query.filter(JPCompanyFundamental.provider == provider)

    if sector is not None:
        query = query.filter(JPCompanyFundamental.sector == sector)

    if industry is not None:
        query = query.filter(JPCompanyFundamental.industry == industry)

    return (
        query.order_by(JPCompanyFundamental.symbol.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def _compact_jp_resource_result(result: dict) -> dict:
    return {
        "status": result.get("status", "success"),
        "fetched_count": int(result.get("fetched_count") or 0),
        "inserted_count": int(result.get("inserted_count") or 0),
        "updated_count": int(result.get("updated_count") or 0),
        "message": result.get("message"),
    }


def _refresh_jp_symbol_resources(
    db: Session,
    *,
    symbol: str,
    include_daily: bool,
    include_fundamentals: bool,
    outputsize: str,
    provider: str,
) -> dict:
    normalized_symbol = _valid_symbol(symbol)
    resources: dict[str, dict] = {}
    errors: list[dict[str, str]] = []

    def run_resource(resource: str, callback: Callable[[], dict]) -> None:
        try:
            resource_result = _compact_jp_resource_result(callback())
            resources[resource] = resource_result
            if resource_result["status"] == "error":
                errors.append(
                    {
                        "symbol": normalized_symbol,
                        "resource": resource,
                        "message": str(resource_result.get("message") or "Resource refresh failed."),
                    }
                )
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
            lambda: refresh_jp_daily_prices(
                db=db,
                symbol=normalized_symbol,
                outputsize=outputsize,
                provider=provider,
            ),
        )

    if include_fundamentals:
        run_resource(
            "fundamentals",
            lambda: refresh_jp_company_fundamental(
                db=db,
                symbol=normalized_symbol,
                provider="auto",
            ),
        )

    success_count = sum(1 for item in resources.values() if item["status"] == "success")
    partial_success_count = sum(1 for item in resources.values() if item["status"] == "partial_success")
    skipped_count = sum(1 for item in resources.values() if item["status"] == "skipped")
    resource_error_count = sum(1 for item in resources.values() if item["status"] == "error")

    if resource_error_count:
        symbol_status = "error" if success_count == 0 and partial_success_count == 0 else "partial_success"
    elif partial_success_count:
        symbol_status = "partial_success"
    elif not resources or skipped_count == len(resources):
        symbol_status = "skipped"
    else:
        symbol_status = "success"

    return {
        "symbol": normalized_symbol,
        "status": symbol_status,
        "resource_count": len(resources),
        "success_count": success_count,
        "partial_success_count": partial_success_count,
        "skipped_count": skipped_count,
        "error_count": len(errors),
        "fetched_count": sum(item["fetched_count"] for item in resources.values()),
        "inserted_count": sum(item["inserted_count"] for item in resources.values()),
        "updated_count": sum(item["updated_count"] for item in resources.values()),
        "resources": resources,
        "errors": errors,
    }


def refresh_jp_watchlist_resources(
    db: Session,
    *,
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    include_daily: bool = True,
    include_fundamentals: bool = False,
    outputsize: str = "compact",
    provider: str = "auto",
    sleep_seconds: float = 15.0,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    if not include_daily and not include_fundamentals:
        raise ValueError("At least one JP resource must be selected.")

    symbols = list_jp_watchlist_symbols(
        db=db,
        group_id=group_id,
        include_children=include_children,
        enabled_only=enabled_only,
    )
    total = len(symbols)

    if progress_callback is not None:
        progress_callback(0, max(total, 1), "Refreshing JP watchlist resources.")

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
            "message": "No JP watchlist symbols to refresh.",
        }

    results: list[dict] = []
    errors: list[dict[str, str]] = []

    for index, symbol in enumerate(symbols, start=1):
        result = _refresh_jp_symbol_resources(
            db=db,
            symbol=symbol,
            include_daily=include_daily,
            include_fundamentals=include_fundamentals,
            outputsize=outputsize,
            provider=provider,
        )
        results.append(result)
        errors.extend(result["errors"])

        if progress_callback is not None:
            progress_callback(index, total, f"Refreshed {index}/{total} JP symbols.")

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
    elif partial_success_count:
        status_value = "partial_success"
    elif skipped_count == total:
        status_value = "skipped"
    elif skipped_count:
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
        "message": f"JP watchlist resources refreshed for {total} symbols.",
    }


def list_jp_daily_prices(
    db: Session,
    *,
    symbol: str,
    provider: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[JPDailyPrice]:
    normalized_symbol = _valid_symbol(symbol)
    query = db.query(JPDailyPrice).filter(JPDailyPrice.symbol == normalized_symbol)

    if provider is not None:
        query = query.filter(JPDailyPrice.provider == provider)

    if from_date is not None:
        query = query.filter(JPDailyPrice.trade_date >= from_date)

    if to_date is not None:
        query = query.filter(JPDailyPrice.trade_date <= to_date)

    return (
        query.order_by(JPDailyPrice.trade_date.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def _jp_daily_price_resource_slot(db: Session, symbol: str) -> dict:
    query = db.query(JPDailyPrice).filter(JPDailyPrice.symbol == symbol)
    row_count = query.count()
    latest_row = query.order_by(JPDailyPrice.trade_date.desc()).first()

    return {
        "key": "daily_price",
        "status": "available" if row_count > 0 else "empty",
        "available": row_count > 0,
        "source": latest_row.provider if latest_row else "yahoo_chart",
        "latest_date": latest_row.trade_date if latest_row else None,
        "row_count": row_count,
        "metrics": {},
    }


def _jp_margin_interest_resource_slot(db: Session, symbol: str) -> dict:
    query = db.query(JPMarginInterest).filter(JPMarginInterest.symbol == symbol)
    row_count = query.count()
    latest_row = query.order_by(JPMarginInterest.report_date.desc()).first()

    metrics: dict[str, int | str | None] = {}
    if latest_row is not None:
        long_volume = latest_row.long_volume
        short_volume = latest_row.short_volume
        metrics = {
            "margin_long_balance": long_volume,
            "margin_short_balance": short_volume,
            "margin_net_balance": (
                long_volume - short_volume
                if long_volume is not None and short_volume is not None
                else None
            ),
            "margin_long_standardized": latest_row.long_standardized_volume,
            "margin_short_standardized": latest_row.short_standardized_volume,
            "margin_issue_type": latest_row.issue_type,
        }

    return {
        "key": "demand",
        "status": "available" if row_count > 0 else "empty",
        "available": row_count > 0,
        "source": latest_row.provider if latest_row else JP_MARGIN_INTEREST_PROVIDER,
        "latest_date": latest_row.report_date if latest_row else None,
        "row_count": row_count,
        "metrics": metrics,
    }


def _jp_investor_type_resource_slot(db: Session, symbol: str) -> dict:
    stock = (
        db.query(JPStockMaster)
        .filter(JPStockMaster.symbol == symbol)
        .first()
    )
    section = _jp_investor_section_for_stock(stock)
    query = db.query(JPInvestorType)
    if section is not None:
        query = query.filter(JPInvestorType.section == section)

    row_count = query.count()
    latest_row = (
        query.order_by(
            JPInvestorType.published_date.desc(),
            JPInvestorType.end_date.desc(),
            JPInvestorType.start_date.desc(),
        )
        .first()
    )

    latest_date = None
    metrics: dict[str, int | str | None] = {}
    if latest_row is not None:
        latest_date = latest_row.published_date or latest_row.end_date or latest_row.start_date
        metrics = {
            "investor_section": latest_row.section,
            "foreign_balance": latest_row.foreign_balance,
            "trust_bank_balance": latest_row.trust_bank_balance,
            "individual_balance": latest_row.individual_balance,
            "proprietary_balance": latest_row.proprietary_balance,
            "investment_trust_balance": latest_row.investment_trust_balance,
            "total_balance": latest_row.total_balance,
        }
    elif section is not None:
        metrics = {"investor_section": section}

    return {
        "key": "investors",
        "status": "available" if row_count > 0 else "empty",
        "available": row_count > 0,
        "source": latest_row.provider if latest_row else JP_INVESTOR_TYPES_PROVIDER,
        "latest_date": latest_date,
        "row_count": row_count,
        "metrics": metrics,
    }


def _has_any_jp_fundamental_value(
    row: JPCompanyFundamental | SimpleNamespace | None,
    fields: tuple[str, ...],
) -> bool:
    if row is None:
        return False

    return any(getattr(row, field) is not None for field in fields)


def _jp_fundamental_resource_slot(
    fundamental: JPCompanyFundamental | SimpleNamespace | None,
    *,
    key: str,
    fields: tuple[str, ...],
) -> dict:
    available = _has_any_jp_fundamental_value(fundamental, fields)
    latest_date = None
    if fundamental is not None:
        latest_date = fundamental.fetched_at.date()

    return {
        "key": key,
        "status": "available" if available else "empty",
        "available": available,
        "source": fundamental.provider if fundamental else None,
        "latest_date": latest_date,
        "row_count": 1 if available else 0,
        "metrics": {},
    }


def _jp_disclosure_resource_slot(
    fundamental: JPCompanyFundamental | SimpleNamespace | None,
) -> dict:
    available = _has_any_jp_fundamental_value(
        fundamental,
        (
            "disclosed_date",
            "document_type",
            "fiscal_period",
            "fiscal_year_end",
            "earnings_date",
        ),
    )
    latest_date = None
    metrics: dict[str, int | float | str | None] = {
        "coverage": "company_statement_metadata_only",
    }
    if fundamental is not None:
        latest_date = (
            fundamental.disclosed_date
            or fundamental.earnings_date
            or fundamental.fetched_at.date()
        )
        metrics.update(
            {
                "disclosed_date": fundamental.disclosed_date.isoformat()
                if fundamental.disclosed_date
                else None,
                "document_type": fundamental.document_type,
                "fiscal_period": fundamental.fiscal_period,
                "fiscal_year_end": fundamental.fiscal_year_end.isoformat()
                if fundamental.fiscal_year_end
                else None,
                "earnings_date": fundamental.earnings_date.isoformat()
                if fundamental.earnings_date
                else None,
            }
        )

    return {
        "key": "disclosures",
        "status": "partial" if available else "empty",
        "available": available,
        "source": fundamental.provider if fundamental else None,
        "latest_date": latest_date,
        "row_count": 1 if available else 0,
        "metrics": metrics,
    }


def get_jp_resource_summary(db: Session, *, symbol: str) -> dict:
    normalized_symbol = _valid_symbol(symbol)
    fundamental = get_jp_company_fundamental(db=db, symbol=normalized_symbol)

    return {
        "symbol": normalized_symbol,
        "slots": [
            _jp_daily_price_resource_slot(db, normalized_symbol),
            _jp_margin_interest_resource_slot(db, normalized_symbol),
            _jp_investor_type_resource_slot(db, normalized_symbol),
            _jp_disclosure_resource_slot(fundamental),
            _jp_fundamental_resource_slot(
                fundamental,
                key="performance",
                fields=(
                    "net_sales",
                    "operating_profit",
                    "ordinary_profit",
                    "profit",
                    "forecast_net_sales",
                    "forecast_operating_profit",
                    "forecast_profit",
                    "revenue_growth",
                    "operating_margin",
                    "earnings_growth",
                    "disclosed_date",
                    "earnings_date",
                ),
            ),
            _jp_fundamental_resource_slot(
                fundamental,
                key="financials",
                fields=(
                    "eps_ttm",
                    "forward_eps",
                    "trailing_pe",
                    "price_to_book",
                    "dividend_yield",
                    "return_on_equity",
                    "return_on_assets",
                    "profit_margin",
                    "total_assets",
                    "equity",
                    "equity_to_asset_ratio",
                    "debt_to_equity",
                    "current_ratio",
                    "book_value",
                ),
            ),
        ],
    }


def _list_jp_ohlc_source_rows(
    db: Session,
    *,
    symbol: str,
    from_date: date,
    to_date: date,
) -> list[JPDailyPrice]:
    rows = list_jp_daily_prices(
        db=db,
        symbol=symbol,
        from_date=from_date,
        to_date=to_date,
        limit=5000,
        offset=0,
    )
    return sorted(rows, key=lambda row: row.trade_date)


def _refresh_jp_ohlc_history_if_needed(
    db: Session,
    *,
    symbol: str,
    timeframe: str,
    bars: int,
    points: list[dict],
    ensure_history: bool,
    outputsize: str,
    provider: str,
    latest_data_date: date | None,
    expected_data_date: date | None,
) -> dict | None:
    if not ensure_history:
        return None

    refresh_reasons: list[str] = []
    if len(points) < bars:
        refresh_reasons.append("insufficient_history")
    if expected_data_date is not None and (
        latest_data_date is None or latest_data_date < expected_data_date
    ):
        refresh_reasons.append("stale_latest_date")
    if not refresh_reasons:
        return None

    attempted_at = _jp_daily_refresh_attempts.get(symbol)
    now_monotonic = time.time()
    if (
        attempted_at is not None
        and now_monotonic - attempted_at < JP_DAILY_REFRESH_ATTEMPT_COOLDOWN_SECONDS
    ):
        return {
            "status": "skipped",
            "provider": provider,
            "symbol": symbol,
            "fetched_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "refresh_reasons": refresh_reasons,
            "message": "JP daily refresh skipped during the per-symbol cooldown window.",
        }
    _jp_daily_refresh_attempts[symbol] = now_monotonic

    refresh_outputsize = "full" if timeframe in {"weekly", "monthly"} else outputsize
    try:
        result = refresh_jp_daily_prices(
            db=db,
            symbol=symbol,
            outputsize=refresh_outputsize,
            provider=provider,
        )
        return {**result, "refresh_reasons": refresh_reasons}
    except (JPMarketDataFetchError, requests.RequestException, ValueError) as exc:
        if not points:
            raise

        return {
            "status": "error",
            "provider": provider,
            "symbol": symbol,
            "fetched_count": 0,
            "inserted_count": 0,
            "updated_count": 0,
            "refresh_reasons": refresh_reasons,
            "message": f"JP daily refresh failed; using cached rows: {exc}",
        }


@_translate_jp_provider_errors
def list_jp_ohlc_chart_data(
    db: Session,
    *,
    symbol: str,
    timeframe: str = "daily",
    bars: int = 90,
    ensure_history: bool = False,
    outputsize: str = "compact",
    provider: str = "auto",
    to_date: date | None = None,
    expected_data_date: date | None = None,
) -> dict:
    if timeframe not in JP_CHART_LOOKBACK_MULTIPLIER:
        raise ValueError("timeframe must be one of: daily, weekly, monthly.")

    if bars <= 0:
        raise ValueError("bars must be greater than 0.")

    if bars > MAX_JP_CHART_BARS:
        raise ValueError(f"bars must be less than or equal to {MAX_JP_CHART_BARS}.")

    normalized_symbol = _valid_symbol(symbol)
    end_date = to_date or datetime.now(JP_MARKET_TIMEZONE).date()
    resolved_expected_data_date = expected_data_date
    if resolved_expected_data_date is None:
        resolved_expected_data_date = (
            previous_jp_trading_day(end_date, include_value=True)
            if to_date is not None
            else expected_jp_daily_price_date()
        )
    lookback_days = bars * JP_CHART_LOOKBACK_MULTIPLIER[timeframe]
    start_date = end_date - timedelta(days=lookback_days)

    rows = _list_jp_ohlc_source_rows(
        db=db,
        symbol=normalized_symbol,
        from_date=start_date,
        to_date=end_date,
    )
    points = _aggregate_jp_daily_rows(rows=rows, timeframe=timeframe)[-bars:]
    latest_data_date = points[-1].get("time") if points else None
    backfill_result = _refresh_jp_ohlc_history_if_needed(
        db=db,
        symbol=normalized_symbol,
        timeframe=timeframe,
        bars=bars,
        points=points,
        ensure_history=ensure_history,
        outputsize=outputsize,
        provider=provider,
        latest_data_date=latest_data_date,
        expected_data_date=resolved_expected_data_date,
    )

    if backfill_result is not None:
        rows = _list_jp_ohlc_source_rows(
            db=db,
            symbol=normalized_symbol,
            from_date=start_date,
            to_date=end_date,
        )
        points = _aggregate_jp_daily_rows(rows=rows, timeframe=timeframe)[-bars:]
        latest_data_date = points[-1].get("time") if points else None

    freshness_status = (
        "missing"
        if latest_data_date is None
        else "stale"
        if resolved_expected_data_date is not None and latest_data_date < resolved_expected_data_date
        else "future"
        if resolved_expected_data_date is not None and latest_data_date > resolved_expected_data_date
        else "current"
    )
    has_volume = any(point.get("volume") is not None for point in points)
    is_index = normalized_symbol.startswith("^")

    return {
        "symbol": normalized_symbol,
        "timeframe": timeframe,
        "bars": bars,
        "lookback_days": lookback_days,
        "from_date": start_date,
        "to_date": end_date,
        "point_count": len(points),
        "points": points,
        "volume_unit": "shares" if has_volume and not is_index else None,
        "volume_semantics": (
            f"{timeframe}_traded_shares"
            if has_volume and not is_index
            else "index_volume_not_equivalent_to_market_volume"
            if is_index
            else None
        ),
        "volume_status": (
            "available"
            if has_volume and not is_index
            else "not_applicable"
            if is_index
            else "not_provided"
        ),
        "backfill": backfill_result,
        "latest_data_date": latest_data_date,
        "expected_data_date": resolved_expected_data_date,
        "freshness_status": freshness_status,
        "is_current": freshness_status in {"current", "future"},
        "refresh_recommended": freshness_status in {"missing", "stale"},
    }


def _valid_float(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _copy_jp_intraday_payload(payload: dict) -> dict:
    copied = dict(payload)
    copied["points"] = [dict(point) for point in payload.get("points") or []]
    copied["warnings"] = list(payload.get("warnings") or [])
    return copied


def _get_fresh_jp_intraday_cache(cache_key: str) -> dict | None:
    cached = _jp_intraday_cache.get(cache_key)
    if cached is None:
        return None

    expires_at, payload = cached
    if time.time() >= expires_at:
        return None

    return _copy_jp_intraday_payload(payload)


def _set_jp_intraday_cache(cache_key: str, payload: dict) -> dict:
    _jp_intraday_cache[cache_key] = (
        time.time() + JP_INTRADAY_CACHE_SECONDS,
        _copy_jp_intraday_payload(payload),
    )
    return _copy_jp_intraday_payload(payload)


def _jp_intraday_latest_trade_date(payload: dict) -> date | None:
    for point in reversed(payload.get("points") or []):
        if not isinstance(point, dict):
            continue

        time_value = point.get("time")
        if not isinstance(time_value, str):
            continue

        try:
            return datetime.fromisoformat(time_value).date()
        except ValueError:
            continue

    return None


def _latest_jp_daily_close_reference(
    db: Session,
    *,
    symbol: str,
    before_date: date | None = None,
) -> dict | None:
    rows = list_jp_daily_prices(
        db=db,
        symbol=symbol,
        to_date=before_date - timedelta(days=1) if before_date else None,
        limit=30,
        offset=0,
    )

    for row in rows:
        close = _jp_close_value(row)
        if _valid_float(close):
            return {
                "previous_close": float(close),
                "previous_close_source": "jp_daily_price",
                "previous_close_trade_date": row.trade_date.isoformat(),
                "previous_close_provider": row.provider,
            }

    return None


def _apply_jp_intraday_previous_close_reference(
    payload: dict,
    *,
    db: Session | None,
    symbol: str,
) -> dict:
    result = _copy_jp_intraday_payload(payload)
    result.setdefault(
        "previous_close_source",
        "yahoo_finance_chart" if _valid_float(result.get("previous_close")) else None,
    )
    result.setdefault("previous_close_trade_date", None)
    result.setdefault("previous_close_provider", None)

    latest_trade_date = _jp_intraday_latest_trade_date(result)
    if (
        _valid_float(result.get("previous_close"))
        and not result.get("previous_close_trade_date")
        and latest_trade_date is not None
    ):
        result["previous_close_trade_date"] = previous_jp_trading_day(
            latest_trade_date,
            include_value=False,
        ).isoformat()
        result["previous_close_provider"] = (
            result.get("previous_close_provider")
            or result.get("previous_close_source")
            or "unknown"
        )

    if _valid_float(result.get("previous_close")) or db is None:
        return result

    reference = _latest_jp_daily_close_reference(
        db,
        symbol=symbol,
        before_date=latest_trade_date,
    )
    if reference is not None:
        result.update(reference)

    return result


def _jp_daily_volume_totals(db: Session, *, symbol: str) -> dict[date, int]:
    rows = (
        db.query(JPDailyPrice)
        .filter(JPDailyPrice.symbol == symbol)
        .filter(JPDailyPrice.trade_volume.isnot(None))
        .order_by(JPDailyPrice.trade_date.desc(), JPDailyPrice.id.desc())
        .limit(90)
        .all()
    )
    totals: dict[date, int] = {}
    for row in rows:
        if row.trade_volume is None or row.trade_volume <= 0:
            continue
        totals[row.trade_date] = max(totals.get(row.trade_date, 0), int(row.trade_volume))
    return totals


def _persist_jp_intraday_history(
    db: Session,
    *,
    symbol: str,
    payload: dict,
) -> dict:
    result = _copy_jp_intraday_payload(payload)
    if not result.get("points"):
        return result
    try:
        changed_count = mutate_market_intraday_history(
            db,
            provider="yahoo_finance_chart",
            stock_id=symbol,
            market="JP",
            symbol=symbol,
            interval="1m",
            source=str(result.get("source") or "yahoo_finance_chart"),
            source_url=result.get("source_url"),
            points=result.get("points") or [],
            market_timezone=JP_MARKET_TIMEZONE,
        )
        if changed_count:
            db.commit()
    except SQLAlchemyError:
        db.rollback()
        result.setdefault("warnings", []).append(
            "Japan intraday history persistence failed; same-time volume coverage may be partial."
        )
    return result


def _project_jp_intraday_payload(
    payload: dict,
    *,
    db: Session | None,
    symbol: str,
) -> dict:
    result = _copy_jp_intraday_payload(payload)
    history_points = [
        point for point in result.get("points") or [] if isinstance(point, dict)
    ]
    current_points = latest_market_trade_date_points(
        history_points,
        market_timezone=JP_MARKET_TIMEZONE,
    )
    result["points"] = current_points
    result["point_count"] = len(current_points)
    result["regular_point_count"] = sum(
        1 for point in current_points if point.get("session", "regular") == "regular"
    )
    result["extended_point_count"] = 0
    result["has_extended_hours"] = False
    result["session_phase"] = current_points[-1].get("session") if current_points else None
    regular_points = [
        point for point in current_points if point.get("session", "regular") == "regular"
    ]
    if regular_points:
        result["regular_session_close"] = regular_points[-1].get("price")
        result["regular_session_close_time"] = regular_points[-1].get("time")

    if current_points:
        current_trade_date = datetime.fromisoformat(str(current_points[-1]["time"])).date()
        previous_reference = previous_regular_close_from_history(
            history_points,
            market_timezone=JP_MARKET_TIMEZONE,
            current_trade_date=current_trade_date,
        )
        if previous_reference is not None:
            result.update(previous_reference)

    if db is not None and not symbol.startswith("^"):
        result["volume_pace"] = build_stock_volume_pace(
            db,
            stock_id=symbol,
            market="JP",
            current_points=regular_points,
            market_timezone=JP_MARKET_TIMEZONE,
            daily_totals=_jp_daily_volume_totals(db, symbol=symbol),
            daily_source_name="jp_daily_price",
            history_market="JP",
            complete_day_min_ratio=0.55,
            minimum_history_points_per_day=300,
        )
    else:
        result["volume_pace"] = None
    return result


def get_jp_intraday_trend(
    *,
    symbol: str,
    db: Session | None = None,
    refresh: bool = False,
    external_fetch_allowed: bool = True,
) -> dict:
    normalized_symbol = _valid_symbol(symbol)
    cache_key = f"JP:{normalized_symbol}"

    if not refresh:
        cached = _get_fresh_jp_intraday_cache(cache_key)
        if cached is not None:
            return _apply_jp_intraday_previous_close_reference(
                _project_jp_intraday_payload(
                    cached,
                    db=db,
                    symbol=normalized_symbol,
                ),
                db=db,
                symbol=normalized_symbol,
            )
        if db is not None:
            persisted = load_persisted_market_intraday_history(
                db,
                stock_id=normalized_symbol,
                market="JP",
                market_timezone=JP_MARKET_TIMEZONE,
            )
            if persisted.get("points"):
                persisted["trade_value_unit"] = "JPY"
                cached_persisted = _set_jp_intraday_cache(
                    cache_key,
                    persisted,
                )
                return _apply_jp_intraday_previous_close_reference(
                    _project_jp_intraday_payload(
                        cached_persisted,
                        db=db,
                        symbol=normalized_symbol,
                    ),
                    db=db,
                    symbol=normalized_symbol,
                )

    if not external_fetch_allowed:
        payload = {
            "stock_id": normalized_symbol,
            "symbol": normalized_symbol,
            "source": "unavailable",
            "session_scope": "regular",
            "session_phase": None,
            "has_extended_hours": False,
            "regular_point_count": 0,
            "extended_point_count": 0,
            "previous_close": None,
            "previous_close_source": None,
            "previous_close_trade_date": None,
            "previous_close_provider": None,
            "regular_session_close": None,
            "regular_session_close_time": None,
            "point_count": 0,
            "points": [],
            "source_url": None,
            "cache_status": "persisted_miss",
            "cache_hit": False,
            "fallback_used": False,
            "warnings": [
                "Japan intraday cache-only read found no persisted data; "
                "external fetch was not attempted."
            ],
        }
        return _apply_jp_intraday_previous_close_reference(
            _project_jp_intraday_payload(
                payload,
                db=db,
                symbol=normalized_symbol,
            ),
            db=db,
            symbol=normalized_symbol,
        )

    try:
        range_value = (
            "1d"
            if normalized_symbol.startswith("^")
            or db is None
            or not intraday_history_needs_bootstrap(
                db,
                stock_id=normalized_symbol,
                market="JP",
                market_timezone=JP_MARKET_TIMEZONE,
            )
            else "5d"
        )
        yahoo_payload, source_url = fetch_yahoo_chart_payload(
            symbol=normalized_symbol,
            range_value=range_value,
            interval="1m",
            timeout_seconds=settings.jp_market_http_timeout_seconds,
        )
        payload = parse_yahoo_intraday_prices(
            yahoo_payload,
            symbol=normalized_symbol,
            source_url=source_url,
        )
        if db is not None:
            payload = _persist_jp_intraday_history(
                db,
                symbol=normalized_symbol,
                payload=payload,
            )
    except Exception as exc:
        persisted = (
            load_persisted_market_intraday_history(
                db,
                stock_id=normalized_symbol,
                market="JP",
                market_timezone=JP_MARKET_TIMEZONE,
            )
            if db is not None
            else {}
        )
        if persisted.get("points"):
            payload = persisted
            payload["trade_value_unit"] = "JPY"
            payload["cache_status"] = "refresh_fallback_hit"
            payload["fallback_used"] = True
            payload.setdefault("warnings", []).append(
                f"Japan intraday refresh failed; using persisted cache: {exc}"
            )
        else:
            payload = {
                "stock_id": normalized_symbol,
                "symbol": normalized_symbol,
                "source": "unavailable",
                "session_scope": "regular",
                "session_phase": None,
                "has_extended_hours": False,
                "regular_point_count": 0,
                "extended_point_count": 0,
                "previous_close": None,
                "previous_close_source": None,
                "previous_close_trade_date": None,
                "previous_close_provider": None,
                "regular_session_close": None,
                "regular_session_close_time": None,
                "point_count": 0,
                "points": [],
                "source_url": None,
                "cache_status": "refresh_fallback_miss",
                "cache_hit": False,
                "fallback_used": False,
                "warnings": [f"Japan intraday source is unavailable: {exc}"],
            }

    payload = _set_jp_intraday_cache(cache_key, payload)
    return _apply_jp_intraday_previous_close_reference(
        _project_jp_intraday_payload(
            payload,
            db=db,
            symbol=normalized_symbol,
        ),
        db=db,
        symbol=normalized_symbol,
    )
