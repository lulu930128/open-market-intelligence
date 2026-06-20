from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone

import requests
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import JPDailyPrice, JPStockMaster, JPWatchlistGroup, JPWatchlistItem, utc_now
from app.jp_market.schemas import (
    JPWatchlistGroupCreate,
    JPWatchlistGroupUpdate,
    JPWatchlistItemCreate,
    JPWatchlistItemUpdate,
)
from app.jp_market.sources import (
    JPDailyPriceRecord,
    JPMarketDataFetchError,
    JPStockRecord,
    fetch_jpx_listed_issues_workbook,
    fetch_yahoo_chart_payload,
    normalize_jp_symbol,
    parse_jpx_listed_issues_workbook,
    parse_yahoo_daily_prices,
    parse_yahoo_stock_record,
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
JP_PLANNED_RESOURCE_KEYS = ("chips", "institutional", "branch", "revenue", "earnings")
MAX_JP_CHART_BARS = 5000
YAHOO_CHART_COMPACT_RANGE = "1y"
YAHOO_CHART_FULL_RANGE = "10y"


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
    }


def _jp_planned_resource_slot(key: str) -> dict:
    return {
        "key": key,
        "status": "planned",
        "available": False,
        "source": None,
        "latest_date": None,
        "row_count": 0,
    }


def get_jp_resource_summary(db: Session, *, symbol: str) -> dict:
    normalized_symbol = _valid_symbol(symbol)

    return {
        "symbol": normalized_symbol,
        "slots": [
            _jp_daily_price_resource_slot(db, normalized_symbol),
            *[_jp_planned_resource_slot(key) for key in JP_PLANNED_RESOURCE_KEYS],
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
