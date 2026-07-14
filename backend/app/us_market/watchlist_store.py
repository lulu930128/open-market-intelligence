from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import USStockMaster, USWatchlistGroup, USWatchlistItem
from app.us_market.errors import (
    USWatchlistGroupNotEmptyError,
    USWatchlistGroupNotFoundError,
    USWatchlistInvalidTreeError,
    USWatchlistItemNotFoundError,
)
from app.us_market.schemas import USWatchlistGroupCreate, USWatchlistGroupUpdate
from app.us_market.sources import normalize_us_symbol

def get_us_watchlist_group(db: Session, group_id: int) -> USWatchlistGroup:
    group = (
        db.query(USWatchlistGroup)
        .filter(USWatchlistGroup.id == group_id)
        .first()
    )

    if group is None:
        raise USWatchlistGroupNotFoundError(f"US watchlist group id={group_id} not found.")

    return group


def _validate_us_watchlist_parent(
    db: Session,
    group_id: int | None,
    parent_id: int | None,
) -> None:
    if parent_id is None:
        return

    parent = (
        db.query(USWatchlistGroup)
        .filter(USWatchlistGroup.id == parent_id)
        .first()
    )

    if parent is None:
        raise USWatchlistGroupNotFoundError(f"Parent US watchlist group id={parent_id} not found.")

    if group_id is not None and parent_id == group_id:
        raise USWatchlistInvalidTreeError("A US watchlist group cannot be its own parent.")

    current = parent
    while current is not None:
        if group_id is not None and current.id == group_id:
            raise USWatchlistInvalidTreeError("Cannot move a US watchlist group under its descendant.")

        if current.parent_id is None:
            break

        current = (
            db.query(USWatchlistGroup)
            .filter(USWatchlistGroup.id == current.parent_id)
            .first()
        )


def create_us_watchlist_group(
    db: Session,
    payload: USWatchlistGroupCreate,
) -> USWatchlistGroup:
    _validate_us_watchlist_parent(db=db, group_id=None, parent_id=payload.parent_id)

    group = USWatchlistGroup(**payload.model_dump())
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def list_us_watchlist_groups(
    db: Session,
    *,
    is_active: bool | None = None,
) -> list[USWatchlistGroup]:
    query = db.query(USWatchlistGroup)

    if is_active is not None:
        query = query.filter(USWatchlistGroup.is_active.is_(is_active))

    return (
        query.order_by(
            USWatchlistGroup.parent_id.asc().nullsfirst(),
            USWatchlistGroup.sort_order.asc(),
            USWatchlistGroup.id.asc(),
        )
        .all()
    )


def _us_group_to_tree_node(
    group: USWatchlistGroup,
    children_by_parent: dict[int | None, list[USWatchlistGroup]],
) -> dict:
    children = [
        _us_group_to_tree_node(child, children_by_parent)
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


def get_us_watchlist_tree(
    db: Session,
    *,
    is_active: bool | None = True,
) -> list[dict]:
    groups = list_us_watchlist_groups(db=db, is_active=is_active)
    children_by_parent: dict[int | None, list[USWatchlistGroup]] = {}

    for group in groups:
        children_by_parent.setdefault(group.parent_id, []).append(group)

    return [
        _us_group_to_tree_node(group, children_by_parent)
        for group in children_by_parent.get(None, [])
    ]


def update_us_watchlist_group(
    db: Session,
    group_id: int,
    payload: USWatchlistGroupUpdate,
) -> USWatchlistGroup:
    group = get_us_watchlist_group(db, group_id)
    update_data = payload.model_dump(exclude_unset=True)

    if "parent_id" in update_data:
        _validate_us_watchlist_parent(
            db=db,
            group_id=group_id,
            parent_id=update_data["parent_id"],
        )

    for key, value in update_data.items():
        setattr(group, key, value)

    db.commit()
    db.refresh(group)
    return group


def _get_us_descendant_group_ids(db: Session, group_id: int) -> list[int]:
    groups = db.query(USWatchlistGroup).all()
    children_by_parent: dict[int | None, list[USWatchlistGroup]] = {}

    for group in groups:
        children_by_parent.setdefault(group.parent_id, []).append(group)

    result: list[int] = []

    def walk(current_id: int) -> None:
        result.append(current_id)

        for child in children_by_parent.get(current_id, []):
            walk(child.id)

    walk(group_id)
    return result


def delete_us_watchlist_group(
    db: Session,
    group_id: int,
    *,
    recursive: bool = False,
) -> dict:
    get_us_watchlist_group(db, group_id)
    group_ids = _get_us_descendant_group_ids(db, group_id)

    if not recursive and len(group_ids) > 1:
        raise USWatchlistGroupNotEmptyError(
            f"US watchlist group id={group_id} has child groups."
        )

    item_count = (
        db.query(USWatchlistItem)
        .filter(USWatchlistItem.group_id.in_(group_ids))
        .count()
    )
    if not recursive and item_count > 0:
        raise USWatchlistGroupNotEmptyError(
            f"US watchlist group id={group_id} has watchlist items."
        )

    (
        db.query(USWatchlistItem)
        .filter(USWatchlistItem.group_id.in_(group_ids))
        .delete(synchronize_session=False)
    )
    (
        db.query(USWatchlistGroup)
        .filter(USWatchlistGroup.id.in_(group_ids))
        .delete(synchronize_session=False)
    )
    db.commit()

    return {
        "deleted_group_id": group_id,
        "deleted_item_count": item_count,
        "deleted_group_count": len(group_ids),
    }


def _us_watchlist_item_to_dict(
    db: Session,
    item: USWatchlistItem,
) -> dict:
    stock = (
        db.query(USStockMaster)
        .filter(USStockMaster.symbol == item.symbol)
        .first()
    )

    return {
        "id": item.id,
        "group_id": item.group_id,
        "symbol": item.symbol,
        "security_name": stock.security_name if stock else None,
        "exchange": stock.exchange if stock else None,
        "asset_type": stock.asset_type if stock else None,
        "note": item.note,
        "priority": item.priority,
        "tags": item.tags,
        "enabled": item.enabled,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def get_us_watchlist_item(db: Session, item_id: int) -> USWatchlistItem:
    item = (
        db.query(USWatchlistItem)
        .filter(USWatchlistItem.id == item_id)
        .first()
    )

    if item is None:
        raise USWatchlistItemNotFoundError(f"US watchlist item id={item_id} not found.")

    return item


def list_us_watchlist_items(
    db: Session,
    *,
    group_id: int | None = None,
    symbol: str | None = None,
    enabled: bool | None = None,
    include_children: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    query = db.query(USWatchlistItem)

    if group_id is not None:
        get_us_watchlist_group(db, group_id)

        if include_children:
            group_ids = _get_us_descendant_group_ids(db, group_id)
            query = query.filter(USWatchlistItem.group_id.in_(group_ids))
        else:
            query = query.filter(USWatchlistItem.group_id == group_id)

    if symbol is not None:
        query = query.filter(USWatchlistItem.symbol == normalize_us_symbol(symbol))

    if enabled is not None:
        query = query.filter(USWatchlistItem.enabled.is_(enabled))

    items = (
        query.order_by(
            USWatchlistItem.priority.asc(),
            USWatchlistItem.id.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [_us_watchlist_item_to_dict(db, item) for item in items]


def list_us_watchlist_symbols(
    db: Session,
    *,
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
) -> list[str]:
    query = db.query(USWatchlistItem)

    if group_id is not None:
        get_us_watchlist_group(db, group_id)

        if include_children:
            group_ids = _get_us_descendant_group_ids(db, group_id)
            query = query.filter(USWatchlistItem.group_id.in_(group_ids))
        else:
            query = query.filter(USWatchlistItem.group_id == group_id)

    if enabled_only:
        query = query.filter(USWatchlistItem.enabled.is_(True))

    rows = (
        query.order_by(
            USWatchlistItem.priority.asc(),
            USWatchlistItem.id.asc(),
        )
        .all()
    )
    symbols: list[str] = []
    seen: set[str] = set()

    for row in rows:
        symbol = normalize_us_symbol(row.symbol)
        if not symbol or symbol in seen:
            continue

        symbols.append(symbol)
        seen.add(symbol)

    return symbols


def delete_us_watchlist_item(db: Session, item_id: int) -> None:
    item = get_us_watchlist_item(db, item_id)
    db.delete(item)
    db.commit()


__all__ = [
    "USMarketConfigurationError",
    "USMarketDataFetchError",
    "USStockNotFoundError",
    "USWatchlistDuplicateItemError",
    "USWatchlistGroupNotEmptyError",
    "USWatchlistGroupNotFoundError",
    "USWatchlistInvalidTreeError",
    "USWatchlistItemNotFoundError",
    "create_us_watchlist_group",
    "create_us_watchlist_item",
    "delete_us_watchlist_group",
    "delete_us_watchlist_item",
    "discover_us_stock_master_from_yahoo_chart",
    "ensure_us_stock_master",
    "build_us_source_health",
    "get_us_company_profile",
    "get_us_intraday_trend",
    "get_us_sec_fundamental_summary",
    "get_us_stock",
    "get_us_watchlist_group",
    "get_us_watchlist_item",
    "get_us_watchlist_technical_radar",
    "get_us_watchlist_tree",
    "get_us_watchlist_ranking",
    "list_macro_series_observations",
    "list_us_company_profiles",
    "list_us_corporate_actions",
    "list_us_daily_prices",
    "list_us_ohlc_chart_data",
    "list_us_sec_company_facts",
    "list_us_short_volumes",
    "list_us_stocks",
    "list_us_watchlist_groups",
    "list_us_watchlist_items",
    "list_us_watchlist_symbols",
    "refresh_fred_macro_series",
    "repair_us_daily_price_quality",
    "refresh_us_company_profile_from_alphavantage",
    "refresh_us_corporate_actions_from_alphavantage",
    "refresh_us_daily_prices",
    "refresh_us_daily_prices_from_alphavantage",
    "refresh_us_daily_prices_from_yahoo_chart",
    "refresh_us_sec_companyfacts",
    "refresh_us_short_volume_from_finra",
    "refresh_us_watchlist_daily_prices",
    "refresh_us_watchlist_resources",
    "search_us_stocks",
    "sync_us_sec_company_data",
    "sync_us_symbol_master",
    "update_us_watchlist_group",
    "update_us_watchlist_item",
    "upsert_macro_series_observation_records",
    "upsert_us_company_profile_records",
    "upsert_us_corporate_action_records",
    "upsert_us_daily_price_records",
    "upsert_us_sec_fact_records",
    "upsert_us_short_volume_records",
    "upsert_us_symbol_records",
]
