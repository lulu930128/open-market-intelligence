from datetime import date

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.watchlists import (
    indicator_service,
    radar_active_v2_service,
    radar_backtest_v2,
    radar_outcome_service,
    radar_service,
    radar_shadow_v2_service,
    radar_v2_service,
    ranking_service,
    service,
    signal_service,
)
from app.db.session import get_db
from app.jobs import backfill_tasks, service as job_service
from app.jobs.schemas import JobRunRead
from app.settings.refresh_execution import resolve_observed_stock_refresh_interval_seconds
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
    WatchlistRadarOutcomeSummaryRead,
    WatchlistRadarSnapshotRead,
    WatchlistRadarV2BacktestRead,
    WatchlistRadarV2OutcomeSummaryRead,
    WatchlistRadarV2PersistResultRead,
    WatchlistRadarV2ProjectionHistoryRead,
)
from app.watchlists.radar_rule_contract import (
    RADAR_V1_FROZEN_AT,
    RADAR_V1_LIFECYCLE_STATUS,
    RADAR_V1_RULE_VERSION,
    RADAR_V2_ACTIVE_CONTRACT,
    RADAR_V2_ACTIVE_RULE_CONFIG_HASH,
    RADAR_V2_ACTIVE_RULE_VERSION,
    RADAR_V2_RULE_CONFIG_HASH,
    RADAR_V2_RULE_VERSION,
)

router = APIRouter()


def _raise_frozen_radar_v1_write() -> None:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail={
            "code": "RADAR_V1_FROZEN",
            "message": (
                "Radar v1 is frozen and no longer accepts snapshots or outcome "
                "evaluation writes. Use the Radar v2 endpoints instead."
            ),
            "rule_version": RADAR_V1_RULE_VERSION,
            "frozen_at": RADAR_V1_FROZEN_AT,
        },
    )


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
        reuse_success_within_seconds=300,
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
    sleep_seconds: float | None = Query(default=None, ge=0.2, le=10.0),
    skip_existing_months: bool = True,
    db: Session = Depends(get_db),
):
    resolved_sleep_seconds = resolve_observed_stock_refresh_interval_seconds(
        db=db,
        market="tw",
        explicit_sleep_seconds=sleep_seconds,
    )
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
        sleep_seconds=resolved_sleep_seconds,
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
    sleep_seconds: float | None = Query(default=None, ge=0.2, le=10.0),
    skip_existing_months: bool = True,
    db: Session = Depends(get_db),
):
    resolved_sleep_seconds = resolve_observed_stock_refresh_interval_seconds(
        db=db,
        market="tw",
        explicit_sleep_seconds=sleep_seconds,
    )
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
        sleep_seconds=resolved_sleep_seconds,
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
    sleep_seconds: float | None = Query(default=None, ge=0.2, le=10.0),
    skip_existing_months: bool = True,
    db: Session = Depends(get_db),
):
    resolved_sleep_seconds = resolve_observed_stock_refresh_interval_seconds(
        db=db,
        market="tw",
        explicit_sleep_seconds=sleep_seconds,
    )
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
        sleep_seconds=resolved_sleep_seconds,
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
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
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
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
    limit: int = Query(default=100, ge=20, le=500),
    volume_ratio_threshold: float | None = Query(default=None, ge=1.0, le=5.0),
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
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
    limit: int = Query(default=100, ge=20, le=500),
    volume_ratio_threshold: float | None = Query(default=None, ge=1.0, le=5.0),
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
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
    limit: int = Query(default=100, ge=20, le=500),
    volume_ratio_threshold: float | None = Query(default=None, ge=1.0, le=5.0),
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
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
    calculation_limit: int = Query(default=100, ge=20, le=500),
    volume_ratio_threshold: float | None = Query(default=None, ge=1.0, le=5.0),
    use_intraday: bool = False,
    intraday_limit: int = Query(default=30, ge=1, le=100),
    prefer_snapshot: bool = True,
    snapshot_only: bool = False,
    include_shadow_v2: bool | None = None,
    version: str = Query(default="v2", pattern="^(v1|v2)$"),
    db: Session = Depends(get_db),
):
    try:
        if version == "v2":
            snapshot_matches_default_calculation = (
                ma_windows is None
                and volume_ma_windows is None
                and calculation_limit == 100
                and volume_ratio_threshold is None
            )
            if (
                prefer_snapshot
                and not use_intraday
                and snapshot_matches_default_calculation
            ) or snapshot_only:
                active_snapshot = (
                    radar_v2_service.get_latest_radar_v2_projection(
                        db=db,
                        group_id=group_id,
                        mode=mode,
                        max_results=max_results,
                        minimum_snapshot_date=(
                            ranking_service.expected_daily_price_date()
                        ),
                    )
                )
                if (
                    active_snapshot is not None
                    and bool(active_snapshot.get("include_children"))
                    == include_children
                ):
                    return active_snapshot
                if snapshot_only:
                    raise radar_outcome_service.WatchlistRadarSnapshotNotFoundError(
                        "No Radar v2 snapshot is available for "
                        f"group id={group_id}, mode={mode}."
                    )

            base_radar, calculation_universe = (
                radar_service.get_watchlist_group_radar_bundle(
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
            )
            base_radar["group_id"] = group_id
            base_radar["cache_status"] = "computed"
            return (
                radar_active_v2_service.build_radar_v2_active_projection_from_db(
                    db=db,
                    radar=base_radar,
                    universe_items=calculation_universe,
                )
            )

        snapshot = radar_outcome_service.get_latest_watchlist_radar_snapshot_payload(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            mode=mode,
            max_results=max_results,
            radar_rule_version=RADAR_V1_RULE_VERSION,
        )
        if snapshot is None:
            raise radar_outcome_service.WatchlistRadarSnapshotNotFoundError(
                "No frozen Radar v1 snapshot is available for "
                f"group id={group_id}, mode={mode}."
            )
        limitations = list(snapshot.get("data_limitations") or [])
        limitations.append(
            "Radar v1 is frozen at 2026-08-01; this is read-only persisted history."
        )
        return {
            **snapshot,
            "cache_status": "frozen_v1_snapshot",
            "data_limitations": limitations,
            "radar_engine": {
                "active_version": RADAR_V2_ACTIVE_RULE_VERSION,
                "active_config_hash": RADAR_V2_ACTIVE_RULE_CONFIG_HASH,
                "shadow_version": RADAR_V2_RULE_VERSION,
                "shadow_config_hash": RADAR_V2_RULE_CONFIG_HASH,
                "mode": "frozen",
                "rollback_version": RADAR_V1_RULE_VERSION,
                "technical_direction_owner": "backend",
                "legacy_status": RADAR_V1_LIFECYCLE_STATUS,
                "legacy_frozen_at": RADAR_V1_FROZEN_AT,
            },
        }
    except service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except radar_outcome_service.WatchlistRadarSnapshotNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get(
    "/groups/{group_id}/radar/v2/snapshots/history",
    response_model=list[WatchlistRadarV2ProjectionHistoryRead],
)
def list_watchlist_group_radar_v2_snapshots(
    group_id: int,
    mode: str = Query(
        default="action",
        pattern="^(action|surge|breakout|volume|overheat|weakness|risk|momentum|all)$",
    ),
    limit: int = Query(default=30, ge=1, le=120),
    db: Session = Depends(get_db),
):
    return radar_v2_service.list_radar_v2_projection_history(
        db=db,
        group_id=group_id,
        mode=mode,
        limit=limit,
    )


@router.get(
    "/groups/{group_id}/radar/v2/outcomes/latest",
    response_model=WatchlistRadarV2OutcomeSummaryRead,
)
def get_latest_watchlist_group_radar_v2_outcome(
    group_id: int,
    mode: str = Query(
        default="action",
        pattern="^(action|surge|breakout|volume|overheat|weakness|risk|momentum|all)$",
    ),
    snapshot_date: date | None = None,
    horizon_trading_days: int = Query(default=1, ge=1, le=20),
    item_limit: int = Query(default=30, ge=0, le=200),
    db: Session = Depends(get_db),
):
    return radar_v2_service.get_radar_v2_outcome_summary(
        db=db,
        group_id=group_id,
        mode=mode,
        snapshot_date=snapshot_date,
        horizon_trading_days=horizon_trading_days,
        item_limit=item_limit,
    )


@router.get(
    "/groups/{group_id}/radar/v2/outcomes/history",
    response_model=list[WatchlistRadarV2OutcomeSummaryRead],
)
def list_watchlist_group_radar_v2_outcomes(
    group_id: int,
    mode: str = Query(
        default="action",
        pattern="^(action|surge|breakout|volume|overheat|weakness|risk|momentum|all)$",
    ),
    horizon_trading_days: int = Query(default=1, ge=1, le=20),
    limit: int = Query(default=30, ge=1, le=120),
    db: Session = Depends(get_db),
):
    return radar_v2_service.list_radar_v2_outcome_history(
        db=db,
        group_id=group_id,
        mode=mode,
        horizon_trading_days=horizon_trading_days,
        limit=limit,
    )


@router.post(
    "/groups/{group_id}/radar/v2/backtests",
    response_model=WatchlistRadarV2BacktestRead,
)
def run_watchlist_group_radar_v2_backtest(
    group_id: int,
    period_start: date,
    period_end: date,
    mode: str = Query(
        default="action",
        pattern="^(action|surge|breakout|volume|overheat|weakness|risk|momentum|all)$",
    ),
    horizon_trading_days: int = Query(default=5, ge=1, le=20),
    minimum_samples: int = Query(default=30, ge=5, le=10000),
    db: Session = Depends(get_db),
):
    try:
        service.get_group(db=db, group_id=group_id)
        stock_ids = radar_v2_service.list_radar_v2_scope_stock_ids(
            db=db,
            group_id=group_id,
            mode=mode,
            period_start=period_start,
            period_end=period_end,
        )
        contract = RADAR_V2_ACTIVE_CONTRACT
        return radar_backtest_v2.run_radar_backtest_v2(
            db=db,
            request=radar_backtest_v2.RadarBacktestRequest(
                rule_version=str(contract["rule_version"]),
                rule_config_hash=str(contract["rule_config_hash"]),
                feature_version=str(contract["feature_version"]),
                feature_config_hash=str(contract["feature_config_hash"]),
                outcome_contract_version=str(
                    contract["outcome_contract_version"]
                ),
                outcome_config_hash=str(
                    contract["outcome_config_hash"]
                ),
                period_start=period_start,
                period_end=period_end,
                horizon_trading_days=horizon_trading_days,
                stock_ids=tuple(stock_ids),
                scope_key=f"watchlist_group:{group_id}:{mode}",
                minimum_samples=minimum_samples,
            ),
        )
    except service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/groups/{group_id}/radar/v2/backtests/latest",
    response_model=WatchlistRadarV2BacktestRead,
)
def get_latest_watchlist_group_radar_v2_backtest(
    group_id: int,
    mode: str = Query(
        default="action",
        pattern="^(action|surge|breakout|volume|overheat|weakness|risk|momentum|all)$",
    ),
    db: Session = Depends(get_db),
):
    contract = RADAR_V2_ACTIVE_CONTRACT
    result = radar_backtest_v2.get_latest_radar_backtest_v2(
        db=db,
        rule_version=str(contract["rule_version"]),
        rule_config_hash=str(contract["rule_config_hash"]),
        scope_key=f"watchlist_group:{group_id}:{mode}",
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No Radar v2 backtest is available for "
                f"group id={group_id}, mode={mode}."
            ),
        )
    return result


@router.post(
    "/groups/{group_id}/radar/v2/shadow-evaluate",
    response_model=WatchlistRadarV2PersistResultRead,
)
def persist_watchlist_group_radar_v2_shadow(
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    mode: str = Query(
        default="action",
        pattern="^(action|surge|breakout|volume|overheat|weakness|risk|momentum|all)$",
    ),
    max_results: int = Query(default=30, ge=1, le=200),
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
    calculation_limit: int = Query(default=100, ge=20, le=500),
    volume_ratio_threshold: float | None = Query(default=None, ge=1.0, le=5.0),
    use_intraday: bool = False,
    intraday_limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    try:
        if not radar_shadow_v2_service.radar_v2_shadow_enabled():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Radar v2 shadow is disabled by "
                    "OMI_RADAR_V2_SHADOW_ENABLED."
                ),
            )
        radar, v2_universe = radar_service.get_watchlist_group_radar_bundle(
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
        attached = radar_shadow_v2_service.attach_radar_v2_shadow_from_db(
            db=db,
            radar=radar,
            universe_items=v2_universe,
        )
        return radar_shadow_v2_service.persist_radar_v2_shadow(
            db=db,
            radar=attached,
            group_id=group_id,
            mode=mode,
        )
    except service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/groups/{group_id}/radar/v2/evaluate",
    response_model=WatchlistRadarV2PersistResultRead,
)
def persist_watchlist_group_radar_v2_active(
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    mode: str = Query(
        default="action",
        pattern="^(action|surge|breakout|volume|overheat|weakness|risk|momentum|all)$",
    ),
    max_results: int = Query(default=30, ge=1, le=200),
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
    calculation_limit: int = Query(default=100, ge=20, le=500),
    volume_ratio_threshold: float | None = Query(default=None, ge=1.0, le=5.0),
    use_intraday: bool = False,
    intraday_limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    try:
        base_radar, calculation_universe = (
            radar_service.get_watchlist_group_radar_bundle(
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
        )
        active = (
            radar_active_v2_service.build_radar_v2_active_projection_from_db(
                db=db,
                radar=base_radar,
                universe_items=calculation_universe,
            )
        )
        persisted = radar_active_v2_service.persist_radar_v2_active(
            db=db,
            radar=active,
            group_id=group_id,
            mode=mode,
        )
        outcomes = (
            radar_shadow_v2_service.evaluate_pending_radar_v2_outcomes(
                db=db,
                evaluation_ids=persisted["evaluation_ids"],
                group_id=group_id,
                mode=mode,
                rule_version=str(persisted["rule_version"]),
            )
        )
        return {**persisted, "outcomes": outcomes}
    except service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/groups/{group_id}/radar/snapshots",
    response_model=WatchlistRadarSnapshotRead,
    status_code=status.HTTP_201_CREATED,
)
def create_watchlist_group_radar_snapshot(
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    mode: str = Query(
        default="action",
        pattern="^(action|surge|breakout|volume|overheat|weakness|risk|momentum|all)$",
    ),
    max_results: int = Query(default=30, ge=1, le=200),
    ma_windows: str | None = None,
    volume_ma_windows: str | None = None,
    calculation_limit: int = Query(default=100, ge=20, le=500),
    volume_ratio_threshold: float | None = Query(default=None, ge=1.0, le=5.0),
    use_intraday: bool = False,
    intraday_limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    _raise_frozen_radar_v1_write()


@router.post(
    "/groups/{group_id}/radar/outcomes/evaluate",
    response_model=WatchlistRadarOutcomeSummaryRead,
)
def evaluate_watchlist_group_radar_outcome(
    group_id: int,
    mode: str = Query(
        default="action",
        pattern="^(action|surge|breakout|volume|overheat|weakness|risk|momentum|all)$",
    ),
    snapshot_run_id: int | None = Query(default=None, ge=1),
    snapshot_date: date | None = None,
    item_limit: int = Query(default=12, ge=0, le=200),
    db: Session = Depends(get_db),
):
    _raise_frozen_radar_v1_write()


@router.get(
    "/groups/{group_id}/radar/outcomes/history",
    response_model=list[WatchlistRadarOutcomeSummaryRead],
)
def list_watchlist_group_radar_outcomes(
    group_id: int,
    mode: str = Query(
        default="action",
        pattern="^(action|surge|breakout|volume|overheat|weakness|risk|momentum|all)$",
    ),
    limit: int = Query(default=30, ge=1, le=120),
    item_limit: int = Query(default=8, ge=0, le=200),
    db: Session = Depends(get_db),
):
    try:
        return radar_outcome_service.list_watchlist_radar_outcome_summaries(
            db=db,
            group_id=group_id,
            mode=mode,
            limit=limit,
            item_limit=item_limit,
        )
    except service.WatchlistGroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/groups/{group_id}/radar/outcomes/snapshots/{snapshot_run_id}",
    response_model=WatchlistRadarOutcomeSummaryRead,
)
def get_watchlist_group_radar_outcome_snapshot(
    group_id: int,
    snapshot_run_id: int,
    mode: str = Query(
        default="action",
        pattern="^(action|surge|breakout|volume|overheat|weakness|risk|momentum|all)$",
    ),
    item_limit: int = Query(default=200, ge=0, le=200),
    db: Session = Depends(get_db),
):
    try:
        return radar_outcome_service.get_watchlist_radar_outcome_summary_for_scope(
            db=db,
            group_id=group_id,
            mode=mode,
            snapshot_run_id=snapshot_run_id,
            item_limit=item_limit,
        )
    except radar_outcome_service.WatchlistRadarSnapshotNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/groups/{group_id}/radar/outcomes/latest",
    response_model=WatchlistRadarOutcomeSummaryRead,
)
def get_latest_watchlist_group_radar_outcome(
    group_id: int,
    mode: str = Query(
        default="action",
        pattern="^(action|surge|breakout|volume|overheat|weakness|risk|momentum|all)$",
    ),
    snapshot_date: date | None = None,
    item_limit: int = Query(default=12, ge=0, le=200),
    db: Session = Depends(get_db),
):
    return radar_outcome_service.get_latest_watchlist_radar_outcome_summary(
        db=db,
        group_id=group_id,
        mode=mode,
        snapshot_date=snapshot_date,
        item_limit=item_limit,
    )
