from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import StockMaster, WatchlistGroup, WatchlistItem
from app.watchlists.schemas import (
    WatchlistGroupCreate,
    WatchlistGroupMove,
    WatchlistGroupUpdate,
    WatchlistItemCreate,
    WatchlistItemMove,
    WatchlistItemUpdate,
)


class WatchlistGroupNotEmptyError(Exception):
    pass


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


def _list_group_siblings(
    db: Session,
    parent_id: int | None,
    exclude_group_id: int | None = None,
) -> list[WatchlistGroup]:
    query = db.query(WatchlistGroup)

    if parent_id is None:
        query = query.filter(WatchlistGroup.parent_id.is_(None))
    else:
        query = query.filter(WatchlistGroup.parent_id == parent_id)

    if exclude_group_id is not None:
        query = query.filter(WatchlistGroup.id != exclude_group_id)

    return query.order_by(WatchlistGroup.sort_order.asc(), WatchlistGroup.id.asc()).all()


def _normalize_group_sort_order(groups: list[WatchlistGroup]) -> None:
    for index, group in enumerate(groups, start=1):
        group.sort_order = index * 100


def move_group(
    db: Session,
    group_id: int,
    payload: WatchlistGroupMove,
) -> WatchlistGroup:
    group = get_group(db, group_id)
    parent_id = payload.parent_id

    _validate_parent(db=db, group_id=group_id, parent_id=parent_id)

    if payload.before_group_id is not None:
        before_group = get_group(db, payload.before_group_id)
        if before_group.id == group_id:
            return group
        if before_group.parent_id != parent_id:
            raise WatchlistInvalidTreeError(
                "before_group_id must belong to the target parent group."
            )

    siblings = _list_group_siblings(
        db=db,
        parent_id=parent_id,
        exclude_group_id=group_id,
    )

    group.parent_id = parent_id

    if payload.before_group_id is None:
        ordered_groups = [*siblings, group]
    else:
        ordered_groups = []
        inserted = False
        for sibling in siblings:
            if sibling.id == payload.before_group_id:
                ordered_groups.append(group)
                inserted = True
            ordered_groups.append(sibling)
        if not inserted:
            ordered_groups.append(group)

    _normalize_group_sort_order(ordered_groups)

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


def _list_item_siblings(
    db: Session,
    group_id: int,
    exclude_item_id: int | None = None,
) -> list[WatchlistItem]:
    query = db.query(WatchlistItem).filter(WatchlistItem.group_id == group_id)

    if exclude_item_id is not None:
        query = query.filter(WatchlistItem.id != exclude_item_id)

    return query.order_by(WatchlistItem.priority.asc(), WatchlistItem.id.asc()).all()


def _normalize_item_priority(items: list[WatchlistItem]) -> None:
    for index, item in enumerate(items, start=1):
        item.priority = index * 100


def move_item(
    db: Session,
    item_id: int,
    payload: WatchlistItemMove,
) -> dict:
    item = get_item(db, item_id)
    get_group(db, payload.group_id)

    duplicate = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.group_id == payload.group_id)
        .filter(WatchlistItem.stock_id == item.stock_id)
        .filter(WatchlistItem.id != item.id)
        .first()
    )

    if duplicate is not None:
        raise WatchlistDuplicateItemError(
            f"Stock id='{item.stock_id}' already exists in group id={payload.group_id}."
        )

    if payload.before_item_id is not None:
        before_item = get_item(db, payload.before_item_id)
        if before_item.id == item_id:
            return _item_to_dict(db, item)
        if before_item.group_id != payload.group_id:
            raise WatchlistItemNotFoundError(
                "before_item_id must belong to the target watchlist group."
            )

    siblings = _list_item_siblings(
        db=db,
        group_id=payload.group_id,
        exclude_item_id=item_id,
    )

    item.group_id = payload.group_id

    if payload.before_item_id is None:
        ordered_items = [*siblings, item]
    else:
        ordered_items = []
        inserted = False
        for sibling in siblings:
            if sibling.id == payload.before_item_id:
                ordered_items.append(item)
                inserted = True
            ordered_items.append(sibling)
        if not inserted:
            ordered_items.append(item)

    _normalize_item_priority(ordered_items)

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


def delete_group(
    db: Session,
    group_id: int,
    recursive: bool = False,
) -> dict:
    """
    Delete a watchlist group.

    If recursive=True:
    - delete the selected group
    - delete all descendant groups
    - delete all watchlist items under those groups

    If recursive=False:
    - only allow deleting an empty group
    """
    get_group(db, group_id)

    descendant_group_ids = _get_descendant_group_ids(db=db, group_id=group_id)

    direct_child_count = (
        db.query(WatchlistGroup)
        .filter(WatchlistGroup.parent_id == group_id)
        .count()
    )

    direct_item_count = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.group_id == group_id)
        .count()
    )

    if not recursive and (direct_child_count > 0 or direct_item_count > 0):
        raise WatchlistGroupNotEmptyError(
            "Watchlist group is not empty. Use recursive=true to delete children and items."
        )

    deleted_item_count = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.group_id.in_(descendant_group_ids))
        .count()
    )

    db.query(WatchlistItem).filter(
        WatchlistItem.group_id.in_(descendant_group_ids)
    ).delete(synchronize_session=False)

    # Delete child groups before parent group.
    for current_group_id in reversed(descendant_group_ids):
        db.query(WatchlistGroup).filter(
            WatchlistGroup.id == current_group_id
        ).delete(synchronize_session=False)

    db.commit()

    return {
        "group_id": group_id,
        "recursive": recursive,
        "deleted_group_count": len(descendant_group_ids),
        "deleted_item_count": deleted_item_count,
    }
