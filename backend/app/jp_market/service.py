from __future__ import annotations

from collections.abc import Callable
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
import time
from types import SimpleNamespace

import requests
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
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
from app.jp_market.schemas import (
    JPWatchlistGroupCreate,
    JPWatchlistGroupUpdate,
    JPWatchlistItemCreate,
    JPWatchlistItemUpdate,
)
from app.jp_market.sources import (
    JPCompanyFundamentalRecord,
    JPDailyPriceRecord,
    JPInvestorTypeRecord,
    JPMarginInterestRecord,
    JPMarketDataFetchError,
    JPStockRecord,
    fetch_jquants_id_token,
    fetch_jquants_investor_types_payload,
    fetch_jquants_margin_interest_payload,
    fetch_jquants_refresh_token,
    fetch_jquants_statements_payload,
    fetch_jquants_summary_payload,
    fetch_jpx_listed_issues_workbook,
    fetch_yahoo_chart_payload,
    fetch_yahoo_quote_summary_payload,
    local_code_from_symbol,
    normalize_jp_symbol,
    parse_jpx_listed_issues_workbook,
    parse_jquants_company_fundamental,
    parse_jquants_investor_type_records,
    parse_jquants_margin_interest_records,
    parse_yahoo_company_fundamental,
    parse_yahoo_daily_prices,
    parse_yahoo_stock_record,
)
from app.market.technical_radar import (
    TechnicalRadarBar,
    build_technical_watchlist_radar,
)


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
JP_PLANNED_RESOURCE_KEYS = ("disclosures",)
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


def _jp_ranking_freshness(rows: list[dict], requested_symbol_count: int) -> dict:
    row_dates = [
        row.get("trade_date")
        for row in rows
        if isinstance(row.get("trade_date"), date)
    ]
    latest_trade_date = max(row_dates, default=None)
    current_symbol_count = sum(
        1 for row_date in row_dates if row_date == latest_trade_date
    )
    stale_symbol_count = max(requested_symbol_count - current_symbol_count, 0)

    return {
        "trade_date": latest_trade_date,
        "target_trade_date": latest_trade_date,
        "is_current": requested_symbol_count == 0 or stale_symbol_count == 0,
        "current_symbol_count": current_symbol_count,
        "stale_symbol_count": stale_symbol_count,
    }


def get_jp_watchlist_ranking(
    db: Session,
    *,
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = "none",
    sort_order: str = "asc",
) -> dict:
    if rank_by not in {"none", "change_pct", "volume", "close"}:
        raise ValueError("rank_by must be one of: none, change_pct, volume, close.")

    if sort_order not in {"asc", "desc"}:
        raise ValueError("sort_order must be one of: asc, desc.")

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
                "status": "ready" if close is not None else "no_data",
                "source": latest.provider if latest is not None else None,
                "error_message": None,
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
    )

    return {
        "group_id": group_id,
        "include_children": include_children,
        "rank_by": rank_by,
        "sort_order": sort_order,
        "requested_symbol_count": len(rows),
        "ranked_count": len(rows) - no_data_count,
        "no_data_count": no_data_count,
        "error_count": 0,
        **freshness,
        "results": rows,
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

    db.commit()

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


def _jp_planned_resource_slot(key: str) -> dict:
    return {
        "key": key,
        "status": "planned",
        "available": False,
        "source": None,
        "latest_date": None,
        "row_count": 0,
        "metrics": {},
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
            *[_jp_planned_resource_slot(key) for key in JP_PLANNED_RESOURCE_KEYS],
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


def _sum_nullable(values: list[int | None]) -> int | None:
    valid_values = [value for value in values if value is not None]
    if not valid_values:
        return None

    return sum(valid_values)


def _jp_ohlc_point(row: JPDailyPrice, time_value: date | None = None) -> dict:
    return {
        "time": time_value or row.trade_date,
        "open": row.open_price,
        "high": row.high_price,
        "low": row.low_price,
        "close": row.close_price,
        "volume": row.trade_volume,
    }


def _datetime_sort_value(value: datetime | None) -> float:
    if value is None:
        return 0.0

    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc).timestamp()


def _jp_daily_row_completeness_score(row: JPDailyPrice) -> int:
    values = (
        row.open_price,
        row.high_price,
        row.low_price,
        row.close_price,
        row.trade_volume,
    )
    return sum(1 for value in values if value is not None)


def _jp_daily_canonical_sort_key(row: JPDailyPrice) -> tuple[int, float, int]:
    return (
        _jp_daily_row_completeness_score(row),
        _datetime_sort_value(row.fetched_at),
        row.id or 0,
    )


def _dedupe_jp_daily_rows_by_trade_date(rows: list[JPDailyPrice]) -> list[JPDailyPrice]:
    canonical_by_date: "OrderedDict[date, JPDailyPrice]" = OrderedDict()

    for row in rows:
        existing = canonical_by_date.get(row.trade_date)
        if existing is None or _jp_daily_canonical_sort_key(row) > _jp_daily_canonical_sort_key(existing):
            canonical_by_date[row.trade_date] = row

    return [canonical_by_date[trade_date] for trade_date in sorted(canonical_by_date)]


def _aggregate_jp_daily_rows(rows: list[JPDailyPrice], timeframe: str) -> list[dict]:
    rows = _dedupe_jp_daily_rows_by_trade_date(rows)

    if timeframe == "daily":
        return [_jp_ohlc_point(row) for row in rows]

    groups: "OrderedDict[date, list[JPDailyPrice]]" = OrderedDict()

    for row in rows:
        if timeframe == "weekly":
            key = row.trade_date - timedelta(days=row.trade_date.weekday())
        else:
            key = date(row.trade_date.year, row.trade_date.month, 1)

        groups.setdefault(key, []).append(row)

    results: list[dict] = []

    for key, grouped_rows in groups.items():
        first = grouped_rows[0]
        last = grouped_rows[-1]
        highs = [
            row.high_price
            for row in grouped_rows
            if row.high_price is not None
        ]
        lows = [
            row.low_price
            for row in grouped_rows
            if row.low_price is not None
        ]

        results.append(
            {
                "time": key,
                "open": first.open_price,
                "high": max(highs) if highs else None,
                "low": min(lows) if lows else None,
                "close": last.close_price,
                "volume": _sum_nullable([row.trade_volume for row in grouped_rows]),
            }
        )

    return results


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
) -> dict | None:
    if not ensure_history or len(points) >= bars:
        return None

    refresh_outputsize = "full" if timeframe in {"weekly", "monthly"} else outputsize
    try:
        return refresh_jp_daily_prices(
            db=db,
            symbol=symbol,
            outputsize=refresh_outputsize,
            provider=provider,
        )
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
            "message": f"JP daily refresh failed; using cached rows: {exc}",
        }


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
) -> dict:
    if timeframe not in JP_CHART_LOOKBACK_MULTIPLIER:
        raise ValueError("timeframe must be one of: daily, weekly, monthly.")

    if bars <= 0:
        raise ValueError("bars must be greater than 0.")

    if bars > MAX_JP_CHART_BARS:
        raise ValueError(f"bars must be less than or equal to {MAX_JP_CHART_BARS}.")

    normalized_symbol = _valid_symbol(symbol)
    end_date = to_date or date.today()
    lookback_days = bars * JP_CHART_LOOKBACK_MULTIPLIER[timeframe]
    start_date = end_date - timedelta(days=lookback_days)

    rows = _list_jp_ohlc_source_rows(
        db=db,
        symbol=normalized_symbol,
        from_date=start_date,
        to_date=end_date,
    )
    points = _aggregate_jp_daily_rows(rows=rows, timeframe=timeframe)[-bars:]
    backfill_result = _refresh_jp_ohlc_history_if_needed(
        db=db,
        symbol=normalized_symbol,
        timeframe=timeframe,
        bars=bars,
        points=points,
        ensure_history=ensure_history,
        outputsize=outputsize,
        provider=provider,
    )

    if backfill_result is not None:
        rows = _list_jp_ohlc_source_rows(
            db=db,
            symbol=normalized_symbol,
            from_date=start_date,
            to_date=end_date,
        )
        points = _aggregate_jp_daily_rows(rows=rows, timeframe=timeframe)[-bars:]

    return {
        "symbol": normalized_symbol,
        "timeframe": timeframe,
        "bars": bars,
        "lookback_days": lookback_days,
        "from_date": start_date,
        "to_date": end_date,
        "point_count": len(points),
        "points": points,
        "backfill": backfill_result,
    }
