from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.crypto_market.assets import (
    CRYPTO_PRIORITY_CORE,
    CRYPTO_PRIORITY_MAJOR,
    get_crypto_asset,
    list_crypto_assets,
)
from app.crypto_market.schemas import (
    CryptoWatchlistGroupCreate,
    CryptoWatchlistGroupUpdate,
    CryptoWatchlistItemCreate,
    CryptoWatchlistItemUpdate,
)
from app.settings.store import get_setting_payload, save_setting_payload


CRYPTO_WATCHLIST_SETTING_KEY = "crypto_watchlist"
CRYPTO_WATCHLIST_SETTING_VERSION = "crypto_watchlist.v1"
DEFAULT_CRYPTO_WATCHLIST_GROUP_NAME = "主流幣"
DEFAULT_CRYPTO_WATCHLIST_PRIORITIES = frozenset(
    {CRYPTO_PRIORITY_CORE, CRYPTO_PRIORITY_MAJOR}
)
DEFAULT_CRYPTO_WATCHLIST_EXCLUDED_ASSETS = frozenset({"USDT"})


class CryptoWatchlistError(Exception):
    pass


class CryptoWatchlistGroupNotFoundError(CryptoWatchlistError):
    pass


class CryptoWatchlistItemNotFoundError(CryptoWatchlistError):
    pass


class CryptoWatchlistGroupNotEmptyError(CryptoWatchlistError):
    pass


class CryptoWatchlistDuplicateItemError(CryptoWatchlistError):
    pass


class CryptoWatchlistInvalidTreeError(CryptoWatchlistError):
    pass


class CryptoWatchlistAssetNotFoundError(CryptoWatchlistError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base_payload() -> dict[str, Any]:
    now = _now_iso()
    default_assets = [
        definition
        for definition in list_crypto_assets()
        if definition.priority in DEFAULT_CRYPTO_WATCHLIST_PRIORITIES
        and definition.asset not in DEFAULT_CRYPTO_WATCHLIST_EXCLUDED_ASSETS
    ]
    default_items = [
        {
            "id": index + 1,
            "group_id": 1,
            "asset": definition.asset,
            "note": None,
            "priority": (index + 1) * 10,
            "tags": None,
            "enabled": True,
            "created_at": now,
            "updated_at": now,
        }
        for index, definition in enumerate(default_assets)
    ]
    return {
        "version": CRYPTO_WATCHLIST_SETTING_VERSION,
        "next_group_id": 2,
        "next_item_id": len(default_items) + 1,
        "groups": [
            {
                "id": 1,
                "parent_id": None,
                "group_name": DEFAULT_CRYPTO_WATCHLIST_GROUP_NAME,
                "description": "Default major crypto assets from the backend registry.",
                "sort_order": 100,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        ],
        "items": default_items,
    }


def _normalize_payload(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    if payload is None:
        return _base_payload()

    groups = payload.get("groups")
    items = payload.get("items")
    normalized = {
        "version": str(payload.get("version") or CRYPTO_WATCHLIST_SETTING_VERSION),
        "next_group_id": int(payload.get("next_group_id") or 1),
        "next_item_id": int(payload.get("next_item_id") or 1),
        "groups": groups if isinstance(groups, list) else [],
        "items": items if isinstance(items, list) else [],
    }
    max_group_id = max([int(group.get("id") or 0) for group in normalized["groups"] if isinstance(group, Mapping)] or [0])
    max_item_id = max([int(item.get("id") or 0) for item in normalized["items"] if isinstance(item, Mapping)] or [0])
    normalized["next_group_id"] = max(normalized["next_group_id"], max_group_id + 1)
    normalized["next_item_id"] = max(normalized["next_item_id"], max_item_id + 1)
    return normalized


def _load_payload(db: Session | None) -> tuple[dict[str, Any], str]:
    persisted = get_setting_payload(
        CRYPTO_WATCHLIST_SETTING_KEY,
        db=db,
    )
    return _normalize_payload(persisted), "database" if persisted is not None else "backend_config"


def _save_payload(db: Session, payload: dict[str, Any]) -> None:
    save_setting_payload(
        db,
        CRYPTO_WATCHLIST_SETTING_KEY,
        payload,
        source="user",
        description="Crypto user watchlist groups and selected assets.",
    )


def _group_or_raise(payload: dict[str, Any], group_id: int) -> dict[str, Any]:
    group = next((group for group in payload["groups"] if int(group.get("id") or 0) == group_id), None)
    if group is None:
        raise CryptoWatchlistGroupNotFoundError(f"Crypto watchlist group id={group_id} not found.")
    return group


def _item_or_raise(payload: dict[str, Any], item_id: int) -> dict[str, Any]:
    item = next((item for item in payload["items"] if int(item.get("id") or 0) == item_id), None)
    if item is None:
        raise CryptoWatchlistItemNotFoundError(f"Crypto watchlist item id={item_id} not found.")
    return item


def _validate_parent(payload: dict[str, Any], group_id: int | None, parent_id: int | None) -> None:
    if parent_id is None:
        return
    parent = _group_or_raise(payload, parent_id)
    if group_id is not None and parent_id == group_id:
        raise CryptoWatchlistInvalidTreeError("A crypto watchlist group cannot be its own parent.")

    current = parent
    while current is not None:
        if group_id is not None and int(current["id"]) == group_id:
            raise CryptoWatchlistInvalidTreeError("Cannot move a crypto watchlist group under its descendant.")
        current_parent_id = current.get("parent_id")
        if current_parent_id is None:
            break
        current = next(
            (group for group in payload["groups"] if int(group.get("id") or 0) == int(current_parent_id)),
            None,
        )


def _asset_name(asset: str) -> str | None:
    definition = get_crypto_asset(asset)
    return definition.name if definition else None


def _normalize_asset(asset: str) -> str:
    normalized = str(asset or "").strip().upper()
    if not normalized or get_crypto_asset(normalized) is None:
        raise CryptoWatchlistAssetNotFoundError(
            f"Crypto asset '{asset}' is not registered in the backend crypto universe."
        )
    return normalized


def _group_to_tree_node(group: dict[str, Any], children_by_parent: dict[int | None, list[dict[str, Any]]]) -> dict[str, Any]:
    group_id = int(group["id"])
    children = [
        _group_to_tree_node(child, children_by_parent)
        for child in children_by_parent.get(group_id, [])
    ]
    return {
        "id": group_id,
        "parent_id": group.get("parent_id"),
        "group_name": group["group_name"],
        "description": group.get("description"),
        "sort_order": int(group.get("sort_order") or 100),
        "is_active": bool(group.get("is_active", True)),
        "children": children,
    }


def list_crypto_watchlist_groups(db: Session | None = None, *, is_active: bool | None = True) -> list[dict[str, Any]]:
    payload, _source = _load_payload(db)
    groups = [dict(group) for group in payload["groups"]]
    if is_active is not None:
        groups = [group for group in groups if bool(group.get("is_active", True)) is is_active]
    return sorted(
        groups,
        key=lambda group: (
            group.get("parent_id") is not None,
            group.get("parent_id") or 0,
            int(group.get("sort_order") or 100),
            int(group.get("id") or 0),
        ),
    )


def get_crypto_watchlist_tree(db: Session | None = None, *, is_active: bool | None = True) -> list[dict[str, Any]]:
    groups = list_crypto_watchlist_groups(db=db, is_active=is_active)
    children_by_parent: dict[int | None, list[dict[str, Any]]] = {}
    for group in groups:
        children_by_parent.setdefault(group.get("parent_id"), []).append(group)
    return [
        _group_to_tree_node(group, children_by_parent)
        for group in children_by_parent.get(None, [])
    ]


def list_crypto_watchlist_items(
    db: Session | None = None,
    *,
    group_id: int | None = None,
    enabled: bool | None = None,
) -> list[dict[str, Any]]:
    payload, _source = _load_payload(db)
    if group_id is not None:
        _group_or_raise(payload, group_id)
    items = [dict(item) for item in payload["items"]]
    if group_id is not None:
        items = [item for item in items if int(item.get("group_id") or 0) == group_id]
    if enabled is not None:
        items = [item for item in items if bool(item.get("enabled", True)) is enabled]
    rows = []
    for item in sorted(items, key=lambda row: (int(row.get("priority") or 100), int(row.get("id") or 0))):
        asset = str(item["asset"]).strip().upper()
        rows.append(
            {
                "id": int(item["id"]),
                "group_id": int(item["group_id"]),
                "asset": asset,
                "asset_name": _asset_name(asset),
                "note": item.get("note"),
                "priority": int(item.get("priority") or 100),
                "tags": item.get("tags"),
                "enabled": bool(item.get("enabled", True)),
                "created_at": item["created_at"],
                "updated_at": item["updated_at"],
            }
        )
    return rows


def create_crypto_watchlist_group(db: Session, payload: CryptoWatchlistGroupCreate) -> dict[str, Any]:
    state, _source = _load_payload(db)
    _validate_parent(state, None, payload.parent_id)
    group_id = int(state["next_group_id"])
    now = _now_iso()
    group = {
        "id": group_id,
        "parent_id": payload.parent_id,
        "group_name": payload.group_name,
        "description": payload.description,
        "sort_order": payload.sort_order,
        "is_active": payload.is_active,
        "created_at": now,
        "updated_at": now,
    }
    state["next_group_id"] = group_id + 1
    state["groups"].append(group)
    _save_payload(db, state)
    return group


def update_crypto_watchlist_group(
    db: Session,
    group_id: int,
    payload: CryptoWatchlistGroupUpdate,
) -> dict[str, Any]:
    state, _source = _load_payload(db)
    group = _group_or_raise(state, group_id)
    update_data = payload.model_dump(exclude_unset=True)
    if "parent_id" in update_data:
        _validate_parent(state, group_id, update_data["parent_id"])
    for key, value in update_data.items():
        group[key] = value
    group["updated_at"] = _now_iso()
    _save_payload(db, state)
    return group


def delete_crypto_watchlist_group(db: Session, group_id: int, *, recursive: bool = False) -> dict[str, Any]:
    state, _source = _load_payload(db)
    _group_or_raise(state, group_id)
    child_ids = {int(group["id"]) for group in state["groups"] if group.get("parent_id") == group_id}
    item_count = sum(1 for item in state["items"] if int(item.get("group_id") or 0) == group_id)
    if not recursive and (child_ids or item_count):
        raise CryptoWatchlistGroupNotEmptyError(
            "Crypto watchlist group is not empty. Use recursive=true to delete children and items."
        )

    group_ids = {group_id}
    while True:
        discovered = {
            int(group["id"])
            for group in state["groups"]
            if group.get("parent_id") in group_ids and int(group["id"]) not in group_ids
        }
        if not discovered:
            break
        group_ids.update(discovered)

    deleted_item_count = sum(1 for item in state["items"] if int(item.get("group_id") or 0) in group_ids)
    state["items"] = [item for item in state["items"] if int(item.get("group_id") or 0) not in group_ids]
    state["groups"] = [group for group in state["groups"] if int(group.get("id") or 0) not in group_ids]
    _save_payload(db, state)
    return {
        "group_id": group_id,
        "recursive": recursive,
        "deleted_group_count": len(group_ids),
        "deleted_item_count": deleted_item_count,
    }


def create_crypto_watchlist_item(db: Session, payload: CryptoWatchlistItemCreate) -> dict[str, Any]:
    state, _source = _load_payload(db)
    _group_or_raise(state, payload.group_id)
    asset = _normalize_asset(payload.asset)
    if any(
        int(item.get("group_id") or 0) == payload.group_id
        and str(item.get("asset") or "").strip().upper() == asset
        for item in state["items"]
    ):
        raise CryptoWatchlistDuplicateItemError(
            f"Crypto asset '{asset}' already exists in group id={payload.group_id}."
        )
    item_id = int(state["next_item_id"])
    now = _now_iso()
    item = {
        "id": item_id,
        "group_id": payload.group_id,
        "asset": asset,
        "note": payload.note,
        "priority": payload.priority,
        "tags": payload.tags,
        "enabled": payload.enabled,
        "created_at": now,
        "updated_at": now,
    }
    state["next_item_id"] = item_id + 1
    state["items"].append(item)
    _save_payload(db, state)
    return next(row for row in list_crypto_watchlist_items(db, group_id=payload.group_id) if row["id"] == item_id)


def update_crypto_watchlist_item(
    db: Session,
    item_id: int,
    payload: CryptoWatchlistItemUpdate,
) -> dict[str, Any]:
    state, _source = _load_payload(db)
    item = _item_or_raise(state, item_id)
    update_data = payload.model_dump(exclude_unset=True)
    if "group_id" in update_data and update_data["group_id"] is not None:
        _group_or_raise(state, update_data["group_id"])
    if "asset" in update_data and update_data["asset"] is not None:
        update_data["asset"] = _normalize_asset(update_data["asset"])

    next_group_id = int(update_data.get("group_id") or item["group_id"])
    next_asset = str(update_data.get("asset") or item["asset"]).strip().upper()
    if any(
        int(other.get("id") or 0) != item_id
        and int(other.get("group_id") or 0) == next_group_id
        and str(other.get("asset") or "").strip().upper() == next_asset
        for other in state["items"]
    ):
        raise CryptoWatchlistDuplicateItemError(
            f"Crypto asset '{next_asset}' already exists in group id={next_group_id}."
        )

    for key, value in update_data.items():
        item[key] = value
    item["updated_at"] = _now_iso()
    _save_payload(db, state)
    return next(row for row in list_crypto_watchlist_items(db) if row["id"] == item_id)


def delete_crypto_watchlist_item(db: Session, item_id: int) -> None:
    state, _source = _load_payload(db)
    _item_or_raise(state, item_id)
    state["items"] = [item for item in state["items"] if int(item.get("id") or 0) != item_id]
    _save_payload(db, state)
