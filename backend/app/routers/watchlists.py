from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.watchlists import indicator_service, radar_service, ranking_service, service, signal_service
from app.db.session import get_db
from app.jobs import backfill_tasks, service as job_service
from app.jobs.schemas import JobRunRead
from app.watchlists.schemas import (
    WatchlistGroupCreate,
    WatchlistGroupDeleteResultRead,
    WatchlistGroupLatestIndicatorsRead,
    WatchlistGroupLatestSignalsRead,
    WatchlistGroupMove,
    WatchlistGroupRadarRead,
    WatchlistGroupRankingBatchRead,
    WatchlistGroupRankingRead,
    WatchlistGroupRead,
    WatchlistGroupTreeRead,
    WatchlistGroupUpdate,
    WatchlistItemCreate,
    WatchlistItemMove,
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


def _queue_group_backfill_job(
    *,
    db: Session,
    background_tasks: BackgroundTasks,
    group_id: int,
    start_date: date,
    end_date: date,
    source_id: int | None,
    tpex_source_id: int | None,
    include_children: bool,
    enabled_only: bool,
    sleep_seconds: float,
    skip_existing_months: bool,
):
    del background_tasks

    request = {
        "group_id": group_id,
        "start_date": start_date,
        "end_date": end_date,
        "source_id": source_id,
        "tpex_source_id": tpex_source_id,
        "include_children": include_children,
        "enabled_only": enabled_only,
        "sleep_seconds": sleep_seconds,
        "skip_existing_months": skip_existing_months,
    }
    job, _created = job_service.enqueue_job(
        db=db,
        job_type="watchlist.group_daily_price_backfill",
        target=str(group_id),
        request=request,
        progress_total=1,
        message="Queued.",
        task=backfill_tasks.run_watchlist_group_backfill_job,
        task_args=(
            group_id,
            start_date,
            end_date,
            source_id,
            tpex_source_id,
            include_children,
            enabled_only,
            sleep_seconds,
            skip_existing_months,
        ),
    )
    return job_service.serialize_job(job)


def _queue_group_refresh_latest_job(
    *,
    db: Session,
    background_tasks: BackgroundTasks,
    group_id: int,
    to_date: date | None,
    lookback_days: int,
    include_today: bool,
    source_id: int | None,
    tpex_source_id: int | None,
    include_children: bool,
    enabled_only: bool,
    sleep_seconds: float,
    skip_existing_months: bool,
):
    del background_tasks

    request = {
        "group_id": group_id,
        "to_date": to_date,
        "lookback_days": lookback_days,
        "include_today": include_today,
        "source_id": source_id,
        "tpex_source_id": tpex_source_id,
        "include_children": include_children,
        "enabled_only": enabled_only,
        "sleep_seconds": sleep_seconds,
        "skip_existing_months": skip_existing_months,
    }
    job, _created = job_service.enqueue_job(
        db=db,
        job_type="watchlist.group_daily_price_refresh_latest",
        target=str(group_id),
        request=request,
        progress_total=1,
        message="Queued.",
        task=backfill_tasks.run_watchlist_group_refresh_latest_job,
        task_args=(
            group_id,
            to_date,
            lookback_days,
            include_today,
            source_id,
            tpex_source_id,
            include_children,
            enabled_only,
            sleep_seconds,
            skip_existing_months,
        ),
    )
    return job_service.serialize_job(job)


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


@router.post("/groups/{group_id}/move", response_model=WatchlistGroupRead)
def move_watchlist_group(
    group_id: int,
    payload: WatchlistGroupMove,
    db: Session = Depends(get_db),
):
    try:
        return service.move_group(db=db, group_id=group_id, payload=payload)
    except Exception as exc:
        raise _handle_group_error(exc) from exc



@router.delete(
    "/groups/{group_id}",
    response_model=WatchlistGroupDeleteResultRead,
)
def delete_watchlist_group(
    group_id: int,
    recursive: bool = False,
    db: Session = Depends(get_db),
):
    try:
        return service.delete_group(
            db=db,
            group_id=group_id,
            recursive=recursive,
        )
    except service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.WatchlistGroupNotEmptyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    

    
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
    limit: int = Query(default=100, ge=1, le=10000),
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
    limit: int = Query(default=100, ge=1, le=10000),
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
    "/groups/{group_id}/backfill",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def backfill_watchlist_group(
    group_id: int,
    start_date: date,
    end_date: date,
    background_tasks: BackgroundTasks,
    source_id: int | None = None,
    tpex_source_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    sleep_seconds: float = Query(default=0.8, ge=0.2, le=10.0),
    skip_existing_months: bool = True,
    db: Session = Depends(get_db),
):
    return _queue_group_backfill_job(
        db=db,
        background_tasks=background_tasks,
        group_id=group_id,
        start_date=start_date,
        end_date=end_date,
        source_id=source_id,
        tpex_source_id=tpex_source_id,
        include_children=include_children,
        enabled_only=enabled_only,
        sleep_seconds=sleep_seconds,
        skip_existing_months=skip_existing_months,
    )


@router.post(
    "/groups/{group_id}/backfill/twse",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def backfill_watchlist_group_twse(
    group_id: int,
    start_date: date,
    end_date: date,
    background_tasks: BackgroundTasks,
    source_id: int | None = None,
    tpex_source_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    sleep_seconds: float = Query(default=0.8, ge=0.2, le=10.0),
    skip_existing_months: bool = True,
    db: Session = Depends(get_db),
):
    return _queue_group_backfill_job(
        db=db,
        background_tasks=background_tasks,
        group_id=group_id,
        start_date=start_date,
        end_date=end_date,
        source_id=source_id,
        tpex_source_id=tpex_source_id,
        include_children=include_children,
        enabled_only=enabled_only,
        sleep_seconds=sleep_seconds,
        skip_existing_months=skip_existing_months,
    )


@router.post(
    "/groups/{group_id}/refresh-latest",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_watchlist_group_latest_prices(
    group_id: int,
    background_tasks: BackgroundTasks,
    to_date: date | None = None,
    lookback_days: int = Query(default=14, ge=1, le=365),
    include_today: bool = False,
    source_id: int | None = None,
    tpex_source_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    sleep_seconds: float = Query(default=0.8, ge=0.2, le=10.0),
    skip_existing_months: bool = True,
    db: Session = Depends(get_db),
):
    return _queue_group_refresh_latest_job(
        db=db,
        background_tasks=background_tasks,
        group_id=group_id,
        to_date=to_date,
        lookback_days=lookback_days,
        include_today=include_today,
        source_id=source_id,
        tpex_source_id=tpex_source_id,
        include_children=include_children,
        enabled_only=enabled_only,
        sleep_seconds=sleep_seconds,
        skip_existing_months=skip_existing_months,
    )


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


@router.post("/items/{item_id}/move", response_model=WatchlistItemRead)
def move_watchlist_item(
    item_id: int,
    payload: WatchlistItemMove,
    db: Session = Depends(get_db),
):
    try:
        return service.move_item(db=db, item_id=item_id, payload=payload)
    except service.WatchlistItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.WatchlistGroupNotFoundError as exc:
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
    

@router.get(
    "/groups/{group_id}/signals/latest",
    response_model=WatchlistGroupLatestSignalsRead,
)
def get_watchlist_group_latest_signals(
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    ma_windows: str = "5,20,60",
    volume_ma_windows: str = "5,20",
    limit: int = Query(default=100, ge=20, le=500),
    volume_ratio_threshold: float = Query(default=1.5, ge=1.0, le=5.0),
    db: Session = Depends(get_db),
):
    try:
        return signal_service.get_watchlist_group_latest_signals(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            ma_windows=ma_windows,
            volume_ma_windows=volume_ma_windows,
            limit=limit,
            volume_ratio_threshold=volume_ratio_threshold,
        )
    except service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    

@router.get(
    "/groups/{group_id}/rankings/latest",
    response_model=WatchlistGroupRankingRead,
)
def get_watchlist_group_latest_ranking(
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = "watchlist",
    sort_order: str = "asc",
    ma_windows: str = "5,20,60",
    volume_ma_windows: str = "5,20",
    limit: int = Query(default=100, ge=20, le=500),
    volume_ratio_threshold: float = Query(default=1.5, ge=1.0, le=5.0),
    use_intraday: bool = False,
    intraday_limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    try:
        return ranking_service.get_watchlist_group_latest_ranking(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            rank_by=rank_by,
            sort_order=sort_order,
            ma_windows=ma_windows,
            volume_ma_windows=volume_ma_windows,
            limit=limit,
            volume_ratio_threshold=volume_ratio_threshold,
            use_intraday=use_intraday,
            intraday_limit=intraday_limit,
        )
    except service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/groups/{group_id}/rankings/latest-batch",
    response_model=WatchlistGroupRankingBatchRead,
)
def get_watchlist_group_latest_ranking_batch(
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = "watchlist",
    sort_order: str = "asc",
    ma_windows: str = "5,20,60",
    volume_ma_windows: str = "5,20",
    limit: int = Query(default=100, ge=20, le=500),
    volume_ratio_threshold: float = Query(default=1.5, ge=1.0, le=5.0),
    use_intraday: bool = False,
    intraday_limit: int = Query(default=30, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    batch_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    try:
        return ranking_service.get_watchlist_group_latest_ranking_batch(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            rank_by=rank_by,
            sort_order=sort_order,
            ma_windows=ma_windows,
            volume_ma_windows=volume_ma_windows,
            limit=limit,
            volume_ratio_threshold=volume_ratio_threshold,
            use_intraday=use_intraday,
            intraday_limit=intraday_limit,
            offset=offset,
            batch_size=batch_size,
        )
    except service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/groups/{group_id}/radar",
    response_model=WatchlistGroupRadarRead,
)
def get_watchlist_group_radar(
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    mode: str = Query(
        default="action",
        pattern="^(action|surge|breakout|volume|overheat|weakness|risk|momentum|all)$",
    ),
    max_results: int = Query(default=30, ge=1, le=200),
    ma_windows: str = "5,20,60",
    volume_ma_windows: str = "5,20",
    calculation_limit: int = Query(default=100, ge=20, le=500),
    volume_ratio_threshold: float = Query(default=1.5, ge=1.0, le=5.0),
    use_intraday: bool = False,
    intraday_limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    try:
        return radar_service.get_watchlist_group_radar(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            mode=mode,
            max_results=max_results,
            ma_windows=ma_windows,
            volume_ma_windows=volume_ma_windows,
            calculation_limit=calculation_limit,
            volume_ratio_threshold=volume_ratio_threshold,
            use_intraday=use_intraday,
            intraday_limit=intraday_limit,
        )
    except service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
