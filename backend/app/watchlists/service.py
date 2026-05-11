from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import StockMaster, WatchlistGroup, WatchlistItem
from app.watchlists.schemas import (
    WatchlistGroupCreate,
    WatchlistGroupUpdate,
    WatchlistItemCreate,
    WatchlistItemUpdate,
)


class WatchlistGroupNotFoundError(Exception):
    pass


class WatchlistItemNotFoundError(Exception):
    pass


class WatchlistDuplicateItemError(Exception):
    pass


class WatchlistInvalidTreeError(Exception):
    pass


class WatchlistStockNotFoundError(Exception):
    pass


def get_group(db: Session, group_id: int) -> WatchlistGroup:
    group = db.query(WatchlistGroup).filter(WatchlistGroup.id == group_id).first()

    if group is None:
        raise WatchlistGroupNotFoundError(f"Watchlist group id={group_id} not found.")

    return group


def _validate_parent(
    db: Session,
    group_id: int | None,
    parent_id: int | None,
) -> None:
    if parent_id is None:
        return

    parent = db.query(WatchlistGroup).filter(WatchlistGroup.id == parent_id).first()

    if parent is None:
        raise WatchlistGroupNotFoundError(f"Parent group id={parent_id} not found.")

    if group_id is not None and parent_id == group_id:
        raise WatchlistInvalidTreeError("A group cannot be its own parent.")

    # Prevent cycles: walk upward from the new parent.
    current = parent

    while current is not None:
        if group_id is not None and current.id == group_id:
            raise WatchlistInvalidTreeError("Cannot move a group under its own descendant.")

        if current.parent_id is None:
            break

        current = db.query(WatchlistGroup).filter(WatchlistGroup.id == current.parent_id).first()


def create_group(db: Session, payload: WatchlistGroupCreate) -> WatchlistGroup:
    _validate_parent(db=db, group_id=None, parent_id=payload.parent_id)

    group = WatchlistGroup(**payload.model_dump())

    db.add(group)
    db.commit()
    db.refresh(group)

    return group


def update_group(
    db: Session,
    group_id: int,
    payload: WatchlistGroupUpdate,
) -> WatchlistGroup:
    group = get_group(db, group_id)

    update_data = payload.model_dump(exclude_unset=True)

    if "parent_id" in update_data:
        _validate_parent(
            db=db,
            group_id=group_id,
            parent_id=update_data["parent_id"],
        )

    for key, value in update_data.items():
        setattr(group, key, value)

    db.commit()
    db.refresh(group)

    return group


def list_groups(
    db: Session,
    is_active: bool | None = None,
) -> list[WatchlistGroup]:
    query = db.query(WatchlistGroup)

    if is_active is not None:
        query = query.filter(WatchlistGroup.is_active.is_(is_active))

    return (
        query.order_by(
            WatchlistGroup.parent_id.asc().nullsfirst(),
            WatchlistGroup.sort_order.asc(),
            WatchlistGroup.id.asc(),
        )
        .all()
    )


def _group_to_tree_node(
    group: WatchlistGroup,
    children_by_parent: dict[int | None, list[WatchlistGroup]],
) -> dict:
    children = [
        _group_to_tree_node(child, children_by_parent)
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


def get_group_tree(
    db: Session,
    is_active: bool | None = True,
) -> list[dict]:
    groups = list_groups(db=db, is_active=is_active)

    children_by_parent: dict[int | None, list[WatchlistGroup]] = {}

    for group in groups:
        children_by_parent.setdefault(group.parent_id, []).append(group)

    return [
        _group_to_tree_node(group, children_by_parent)
        for group in children_by_parent.get(None, [])
    ]


def _get_descendant_group_ids(db: Session, group_id: int) -> list[int]:
    groups = db.query(WatchlistGroup).all()

    children_by_parent: dict[int | None, list[WatchlistGroup]] = {}

    for group in groups:
        children_by_parent.setdefault(group.parent_id, []).append(group)

    result: list[int] = []

    def walk(current_id: int) -> None:
        result.append(current_id)

        for child in children_by_parent.get(current_id, []):
            walk(child.id)

    walk(group_id)

    return result


def _ensure_stock_exists(db: Session, stock_id: str) -> StockMaster:
    stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()

    if stock is None:
        raise WatchlistStockNotFoundError(
            f"Stock id='{stock_id}' not found in stock_master. "
            "Run /api/stocks/sync-from-market first or check stock_id."
        )

    return stock


def _item_to_dict(
    db: Session,
    item: WatchlistItem,
) -> dict:
    stock = db.query(StockMaster).filter(StockMaster.stock_id == item.stock_id).first()

    return {
        "id": item.id,
        "group_id": item.group_id,
        "stock_id": item.stock_id,
        "stock_name": stock.stock_name if stock else None,
        "note": item.note,
        "priority": item.priority,
        "tags": item.tags,
        "enabled": item.enabled,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def create_item(db: Session, payload: WatchlistItemCreate) -> dict:
    get_group(db, payload.group_id)
    _ensure_stock_exists(db, payload.stock_id)

    item = WatchlistItem(**payload.model_dump())

    db.add(item)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise WatchlistDuplicateItemError(
            f"Stock id='{payload.stock_id}' already exists in group id={payload.group_id}."
        ) from exc

    db.refresh(item)

    return _item_to_dict(db, item)


def get_item(db: Session, item_id: int) -> WatchlistItem:
    item = db.query(WatchlistItem).filter(WatchlistItem.id == item_id).first()

    if item is None:
        raise WatchlistItemNotFoundError(f"Watchlist item id={item_id} not found.")

    return item


def list_items(
    db: Session,
    group_id: int | None = None,
    stock_id: str | None = None,
    enabled: bool | None = None,
    include_children: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    query = db.query(WatchlistItem)

    if group_id is not None:
        get_group(db, group_id)

        if include_children:
            group_ids = _get_descendant_group_ids(db, group_id)
            query = query.filter(WatchlistItem.group_id.in_(group_ids))
        else:
            query = query.filter(WatchlistItem.group_id == group_id)

    if stock_id is not None:
        query = query.filter(WatchlistItem.stock_id == stock_id)

    if enabled is not None:
        query = query.filter(WatchlistItem.enabled.is_(enabled))

    items = (
        query.order_by(
            WatchlistItem.priority.asc(),
            WatchlistItem.id.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [_item_to_dict(db, item) for item in items]


def update_item(
    db: Session,
    item_id: int,
    payload: WatchlistItemUpdate,
) -> dict:
    item = get_item(db, item_id)

    update_data = payload.model_dump(exclude_unset=True)

    if "group_id" in update_data:
        get_group(db, update_data["group_id"])

    if "stock_id" in update_data:
        _ensure_stock_exists(db, update_data["stock_id"])

    for key, value in update_data.items():
        setattr(item, key, value)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise WatchlistDuplicateItemError(
            "Duplicate stock in the same watchlist group."
        ) from exc

    db.refresh(item)

    return _item_to_dict(db, item)


def delete_item(db: Session, item_id: int) -> None:
    item = get_item(db, item_id)

    db.delete(item)
    db.commit()