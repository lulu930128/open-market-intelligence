from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.watchlists import backfill_service, indicator_service, service
from app.db.session import get_db
from app.watchlists.schemas import (
    WatchlistGroupBackfillResultRead,
    WatchlistGroupCreate,
    WatchlistGroupLatestIndicatorsRead,
    WatchlistGroupRead,
    WatchlistGroupTreeRead,
    WatchlistGroupUpdate,
    WatchlistItemCreate,
    WatchlistItemRead,
    WatchlistItemUpdate,
)

router = APIRouter()


def _handle_group_error(exc: Exception) -> HTTPException:
    if isinstance(exc, service.WatchlistGroupNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    if isinstance(exc, service.WatchlistInvalidTreeError):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/groups", response_model=WatchlistGroupRead, status_code=status.HTTP_201_CREATED)
def create_watchlist_group(
    payload: WatchlistGroupCreate,
    db: Session = Depends(get_db),
):
    try:
        return service.create_group(db=db, payload=payload)
    except Exception as exc:
        raise _handle_group_error(exc) from exc


@router.get("/groups", response_model=list[WatchlistGroupRead])
def list_watchlist_groups(
    is_active: bool | None = None,
    db: Session = Depends(get_db),
):
    return service.list_groups(db=db, is_active=is_active)


@router.get("/tree", response_model=list[WatchlistGroupTreeRead])
def get_watchlist_tree(
    is_active: bool | None = True,
    db: Session = Depends(get_db),
):
    return service.get_group_tree(db=db, is_active=is_active)


@router.patch("/groups/{group_id}", response_model=WatchlistGroupRead)
def update_watchlist_group(
    group_id: int,
    payload: WatchlistGroupUpdate,
    db: Session = Depends(get_db),
):
    try:
        return service.update_group(db=db, group_id=group_id, payload=payload)
    except Exception as exc:
        raise _handle_group_error(exc) from exc


@router.post("/items", response_model=WatchlistItemRead, status_code=status.HTTP_201_CREATED)
def create_watchlist_item(
    payload: WatchlistItemCreate,
    db: Session = Depends(get_db),
):
    try:
        return service.create_item(db=db, payload=payload)
    except service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.WatchlistStockNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.WatchlistDuplicateItemError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/items", response_model=list[WatchlistItemRead])
def list_watchlist_items(
    group_id: int | None = None,
    stock_id: str | None = None,
    enabled: bool | None = None,
    include_children: bool = False,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        return service.list_items(
            db=db,
            group_id=group_id,
            stock_id=stock_id,
            enabled=enabled,
            include_children=include_children,
            limit=limit,
            offset=offset,
        )
    except service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/groups/{group_id}/items", response_model=list[WatchlistItemRead])
def list_watchlist_group_items(
    group_id: int,
    include_children: bool = False,
    enabled: bool | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        return service.list_items(
            db=db,
            group_id=group_id,
            enabled=enabled,
            include_children=include_children,
            limit=limit,
            offset=offset,
        )
    except service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc



@router.post(
    "/groups/{group_id}/backfill/twse",
    response_model=WatchlistGroupBackfillResultRead,
)
def backfill_watchlist_group_twse(
    group_id: int,
    start_date: date,
    end_date: date,
    source_id: int = 1,
    include_children: bool = True,
    enabled_only: bool = True,
    sleep_seconds: float = Query(default=0.8, ge=0.2, le=10.0),
    db: Session = Depends(get_db),
):
    try:
        return backfill_service.backfill_watchlist_group_twse(
            db=db,
            group_id=group_id,
            start_date=start_date,
            end_date=end_date,
            source_id=source_id,
            include_children=include_children,
            enabled_only=enabled_only,
            sleep_seconds=sleep_seconds,
        )
    except service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/items/{item_id}", response_model=WatchlistItemRead)
def update_watchlist_item(
    item_id: int,
    payload: WatchlistItemUpdate,
    db: Session = Depends(get_db),
):
    try:
        return service.update_item(db=db, item_id=item_id, payload=payload)
    except service.WatchlistItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.WatchlistStockNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.WatchlistDuplicateItemError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watchlist_item(
    item_id: int,
    db: Session = Depends(get_db),
):
    try:
        service.delete_item(db=db, item_id=item_id)
    except service.WatchlistItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return None


@router.get(
    "/groups/{group_id}/indicators/latest",
    response_model=WatchlistGroupLatestIndicatorsRead,
)
def get_watchlist_group_latest_indicators(
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    ma_windows: str = "5,20,60",
    volume_ma_windows: str = "5,20",
    db: Session = Depends(get_db),
):
    try:
        return indicator_service.get_watchlist_group_latest_indicators(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            ma_windows=ma_windows,
            volume_ma_windows=volume_ma_windows,
        )
    except service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc