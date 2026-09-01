from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.jobs import backfill_tasks
from app.jobs.job_types import (
    US_OHLC_HISTORY_REPAIR_JOB_TYPE,
    US_SEC_13F_HISTORY_SYNC_JOB_TYPE,
    US_SEC_13F_MAPPING_SYNC_JOB_TYPE,
    US_SEC_13F_QUARTER_SYNC_JOB_TYPE,
    US_SEC_FORM4_SYNC_JOB_TYPE,
)
from app.jobs.schemas import JobRunRead
from app.routers.market_family_helpers import (
    enqueue_serialized_job,
    fetch_error,
    watchlist_group_error,
    watchlist_group_target,
    watchlist_item_error,
)
from app.settings.refresh_execution import (
    resolve_observed_stock_refresh_interval_seconds,
    resolve_subresource_refresh_interval_seconds,
)
from app.us_market.errors import USMarketDataFetchError
from app.us_market.daily_ohlcv_chart import (
    read_us_daily_ohlcv_chart,
    read_us_daily_ohlcv_history,
)
from app.us_market.daily_ohlcv_platform import refresh_us_daily_ohlcv
from app.us_market.schemas import (
    MacroSeriesObservationRead,
    USDailyPriceRead,
    USDailyPriceQualityRepairResultRead,
    USDailyPriceRefreshResultRead,
    USCompanyProfileRead,
    USCorporateActionRead,
    USIntradayTrendRead,
    USMarketResearchRead,
    USOhlcChartRead,
    USResolvedQuoteSnapshotRead,
    USResourceRefreshResultRead,
    USSecCompanyFactRead,
    USSecFactRefreshResultRead,
    USSecFinancialContractRead,
    USSecFundamentalSummaryRead,
    USSecForm4SyncRequest,
    USSec13FCoverageRead,
    USSec13FHistorySyncRequest,
    USSec13FInstitutionalHoldingsRead,
    USSec13FMappingSyncRequest,
    USSec13FQuarterSyncRequest,
    USSecInsiderTransactionsRead,
    USShortVolumeDailyRead,
    USSourceHealthRead,
    USStockMasterRead,
    USSymbolSyncResultRead,
    USWatchlistGroupCreate,
    USWatchlistGroupDeleteResultRead,
    USWatchlistGroupRead,
    USWatchlistGroupTreeRead,
    USWatchlistGroupUpdate,
    USWatchlistItemCreate,
    USWatchlistItemRead,
    USWatchlistItemUpdate,
    USWatchlistRankingRead,
)
from app.watchlists.schemas import WatchlistGroupRadarRead
from app.routers import us_corporate_events
from app.us_market.service import (
    USMarketConfigurationError,
    USStockNotFoundError,
    USWatchlistDuplicateItemError,
    USWatchlistGroupNotEmptyError,
    USWatchlistGroupNotFoundError,
    USWatchlistInvalidTreeError,
    USWatchlistItemNotFoundError,
    create_us_watchlist_group,
    create_us_watchlist_item,
    delete_us_watchlist_group,
    delete_us_watchlist_item,
    build_us_source_health,
    snapshot_us_source_health,
    get_us_company_profile,
    get_us_intraday_trend,
    get_us_quote_snapshot,
    build_us_market_research,
    get_us_sec_fundamental_summary,
    get_us_sec_financial_contract,
    get_us_stock,
    get_us_watchlist_group,
    get_us_watchlist_ranking,
    get_us_watchlist_technical_radar,
    get_us_watchlist_tree,
    list_macro_series_observations,
    list_us_company_profiles,
    list_us_corporate_actions,
    list_us_watchlist_groups,
    list_us_watchlist_items,
    list_us_sec_company_facts,
    list_us_short_volumes,
    list_us_stocks,
    refresh_fred_macro_series,
    refresh_us_company_profile_from_alphavantage,
    refresh_us_corporate_actions_from_alphavantage,
    refresh_us_sec_companyfacts,
    refresh_us_short_volume_from_finra,
    refresh_us_intraday_bars,
    refresh_us_quote_snapshot,
    repair_us_daily_price_quality,
    search_us_stocks,
    sync_us_sec_company_data,
    sync_us_symbol_master,
    update_us_watchlist_group,
    update_us_watchlist_item,
)
from app.us_market.ownership_service import read_insider_transactions
from app.us_market.ownership_13f_analytics import (
    get_13f_coverage_contract,
    get_13f_symbol_contract,
)


router = APIRouter()
router.include_router(us_corporate_events.router)


def _fetch_error(exc: Exception) -> HTTPException:
    return fetch_error(exc)


def _group_error(exc: Exception) -> HTTPException:
    return watchlist_group_error(
        exc,
        not_found_errors=(USWatchlistGroupNotFoundError,),
        bad_request_errors=(USWatchlistInvalidTreeError, USWatchlistGroupNotEmptyError),
    )


def _item_error(exc: Exception) -> HTTPException:
    return watchlist_item_error(
        exc,
        not_found_errors=(USWatchlistGroupNotFoundError, USWatchlistItemNotFoundError, USStockNotFoundError),
        duplicate_errors=(USWatchlistDuplicateItemError,),
    )


def _enqueue_us_watchlist_daily_refresh(
    *,
    db: Session,
    group_id: int | None,
    include_children: bool,
    enabled_only: bool,
    outputsize: str,
    adjusted: bool,
    sleep_seconds: float,
    job_type: str = "us_market.watchlist_daily_refresh",
) -> dict:
    target = watchlist_group_target(group_id)
    request = {
        "group_id": group_id,
        "include_children": include_children,
        "enabled_only": enabled_only,
        "outputsize": outputsize,
        "adjusted": adjusted,
        "sleep_seconds": sleep_seconds,
    }
    return enqueue_serialized_job(
        db=db,
        job_type=job_type,
        target=target,
        request=request,
        progress_total=1,
        message="Queued US watchlist daily refresh.",
        task=backfill_tasks.run_us_watchlist_daily_refresh_job,
        task_args=(
            group_id,
            include_children,
            enabled_only,
            outputsize,
            adjusted,
            sleep_seconds,
        ),
    )


def _enqueue_us_watchlist_resource_refresh(
    *,
    db: Session,
    group_id: int | None,
    include_children: bool,
    enabled_only: bool,
    include_daily: bool,
    include_sec_facts: bool,
    include_profile: bool,
    include_actions: bool,
    outputsize: str,
    adjusted: bool,
    sleep_seconds: float,
) -> dict:
    target = watchlist_group_target(group_id)
    request = {
        "group_id": group_id,
        "include_children": include_children,
        "enabled_only": enabled_only,
        "include_daily": include_daily,
        "include_sec_facts": include_sec_facts,
        "include_profile": include_profile,
        "include_actions": include_actions,
        "outputsize": outputsize,
        "adjusted": adjusted,
        "sleep_seconds": sleep_seconds,
    }
    return enqueue_serialized_job(
        db=db,
        job_type="us_market.watchlist_resource_refresh",
        target=target,
        request=request,
        progress_total=1,
        message="Queued US watchlist resource refresh.",
        task=backfill_tasks.run_us_watchlist_resource_refresh_job,
        task_args=(
            group_id,
            include_children,
            enabled_only,
            include_daily,
            include_sec_facts,
            include_profile,
            include_actions,
            outputsize,
            adjusted,
            sleep_seconds,
        ),
    )


def _enqueue_us_daily_price_quality_repair(
    *,
    db: Session,
    symbol: str | None,
    dry_run: bool,
    limit: int,
    refresh: bool,
    outputsize: str,
    adjusted: bool,
    sleep_seconds: float,
) -> dict:
    normalized_symbol = symbol.upper().strip() if symbol else None
    target = normalized_symbol or "all"
    request = {
        "symbol": normalized_symbol,
        "dry_run": dry_run,
        "limit": limit,
        "refresh": refresh,
        "outputsize": outputsize,
        "adjusted": adjusted,
        "sleep_seconds": sleep_seconds,
    }
    return enqueue_serialized_job(
        db=db,
        job_type="us_market.daily_price_quality_repair",
        target=target,
        request=request,
        progress_total=1,
        message="Queued US daily price quality repair.",
        task=backfill_tasks.run_us_daily_price_quality_repair_job,
        task_args=(
            normalized_symbol,
            dry_run,
            limit,
            refresh,
            outputsize,
            adjusted,
            sleep_seconds,
        ),
    )


def _enqueue_us_ohlc_history_repair(
    *,
    db: Session,
    symbol: str,
    timeframe: str,
    bars: int,
    provider: str | None,
    adjusted: bool,
    max_provider_calls: int,
    force_full: bool,
) -> dict:
    normalized_symbol = symbol.upper().strip()
    target = f"{normalized_symbol}:{timeframe}:{bars}"
    request = {
        "symbol": normalized_symbol,
        "timeframe": timeframe,
        "bars": bars,
        "provider": provider,
        "adjusted": adjusted,
        "max_provider_calls": max_provider_calls,
        "force_full": force_full,
    }
    return enqueue_serialized_job(
        db=db,
        job_type=US_OHLC_HISTORY_REPAIR_JOB_TYPE,
        target=target,
        request=request,
        progress_total=1,
        message="Queued US OHLC continuity repair.",
        task=backfill_tasks.run_us_ohlc_history_repair_job,
        task_args=(
            normalized_symbol,
            timeframe,
            bars,
            provider,
            adjusted,
            max_provider_calls,
            force_full,
        ),
    )


def _enqueue_us_sec_form4_sync(
    *,
    db: Session,
    request_model: USSecForm4SyncRequest,
) -> dict:
    request = request_model.model_dump(mode="json")
    if request_model.scope == "symbol":
        if not request_model.symbol:
            raise ValueError("symbol is required when scope='symbol'.")
        target = request_model.symbol.strip().upper()
    else:
        target = watchlist_group_target(request_model.group_id)
    return enqueue_serialized_job(
        db=db,
        job_type=US_SEC_FORM4_SYNC_JOB_TYPE,
        target=target,
        request=request,
        progress_total=max(request_model.max_symbols, 1),
        message="Queued SEC Form 4 sync.",
        task=backfill_tasks.run_us_sec_form4_sync_job,
        task_args=(
            request_model.scope,
            request_model.symbol,
            request_model.group_id,
            request_model.include_children,
            request_model.enabled_only,
            request_model.from_date,
            request_model.to_date,
            request_model.max_symbols,
            request_model.max_filings_per_symbol,
        ),
    )


def _enqueue_us_sec_13f_quarter_sync(
    *,
    db: Session,
    request_model: USSec13FQuarterSyncRequest,
) -> dict:
    request = request_model.model_dump(mode="json")
    return enqueue_serialized_job(
        db=db,
        job_type=US_SEC_13F_QUARTER_SYNC_JOB_TYPE,
        target=request_model.period_key.strip().upper(),
        request=request,
        progress_total=5,
        message="Queued SEC Form 13F quarter sync.",
        task=backfill_tasks.run_us_sec_13f_quarter_sync_job,
        task_args=(
            request_model.period_key,
            request_model.source_url,
            request_model.force_download,
            request_model.force_rebuild,
        ),
    )


def _enqueue_us_sec_13f_mapping_sync(
    *,
    db: Session,
    request_model: USSec13FMappingSyncRequest,
) -> dict:
    request = request_model.model_dump(mode="json")
    return enqueue_serialized_job(
        db=db,
        job_type=US_SEC_13F_MAPPING_SYNC_JOB_TYPE,
        target="cusip",
        request=request,
        progress_total=2,
        message="Queued SEC Form 13F identifier mapping sync.",
        task=backfill_tasks.run_us_sec_13f_mapping_sync_job,
        task_args=(
            request_model.cusips,
            request_model.max_identifiers,
            request_model.refresh,
            request_model.rebuild_projections,
        ),
    )


def _enqueue_us_sec_13f_history_sync(
    *,
    db: Session,
    request_model: USSec13FHistorySyncRequest,
) -> dict:
    request = request_model.model_dump(mode="json")
    return enqueue_serialized_job(
        db=db,
        job_type=US_SEC_13F_HISTORY_SYNC_JOB_TYPE,
        target="all-published-history",
        request=request,
        progress_total=max(request_model.max_releases, 1),
        message="Queued SEC Form 13F history sync.",
        task=backfill_tasks.run_us_sec_13f_history_sync_job,
        task_args=(
            request_model.max_releases,
            request_model.refresh_manifest,
            request_model.include_completed,
            request_model.force_download,
            request_model.force_rebuild,
            request_model.stop_on_error,
            request_model.rebuild_projections,
        ),
    )


@router.post(
    "/watchlists/groups",
    response_model=USWatchlistGroupRead,
    status_code=status.HTTP_201_CREATED,
)
def create_us_watchlist_group_api(
    payload: USWatchlistGroupCreate,
    db: Session = Depends(get_db),
):
    try:
        return create_us_watchlist_group(db=db, payload=payload)
    except Exception as exc:
        raise _group_error(exc) from exc


@router.get("/watchlists/groups", response_model=list[USWatchlistGroupRead])
def list_us_watchlist_groups_api(
    is_active: bool | None = None,
    db: Session = Depends(get_db),
):
    return list_us_watchlist_groups(db=db, is_active=is_active)


@router.get("/watchlists/tree", response_model=list[USWatchlistGroupTreeRead])
def get_us_watchlist_tree_api(
    is_active: bool | None = True,
    db: Session = Depends(get_db),
):
    return get_us_watchlist_tree(db=db, is_active=is_active)


@router.patch("/watchlists/groups/{group_id}", response_model=USWatchlistGroupRead)
def update_us_watchlist_group_api(
    group_id: int,
    payload: USWatchlistGroupUpdate,
    db: Session = Depends(get_db),
):
    try:
        return update_us_watchlist_group(db=db, group_id=group_id, payload=payload)
    except Exception as exc:
        raise _group_error(exc) from exc


@router.delete(
    "/watchlists/groups/{group_id}",
    response_model=USWatchlistGroupDeleteResultRead,
)
def delete_us_watchlist_group_api(
    group_id: int,
    recursive: bool = False,
    db: Session = Depends(get_db),
):
    try:
        return delete_us_watchlist_group(db=db, group_id=group_id, recursive=recursive)
    except Exception as exc:
        raise _group_error(exc) from exc


@router.post(
    "/watchlists/items",
    response_model=USWatchlistItemRead,
    status_code=status.HTTP_201_CREATED,
)
def create_us_watchlist_item_api(
    payload: USWatchlistItemCreate,
    db: Session = Depends(get_db),
):
    try:
        return create_us_watchlist_item(db=db, payload=payload)
    except Exception as exc:
        raise _item_error(exc) from exc


@router.get("/watchlists/items", response_model=list[USWatchlistItemRead])
def list_us_watchlist_items_api(
    group_id: int | None = None,
    symbol: str | None = None,
    enabled: bool | None = None,
    include_children: bool = False,
    limit: int = Query(default=100, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        return list_us_watchlist_items(
            db=db,
            group_id=group_id,
            symbol=symbol,
            enabled=enabled,
            include_children=include_children,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        raise _item_error(exc) from exc


@router.get("/watchlists/ranking", response_model=USWatchlistRankingRead)
def get_us_watchlist_ranking_api(
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = Query(default="none", pattern="^(none|change_pct|volume|close)$"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    use_intraday: bool = False,
    intraday_limit: int = Query(default=30, ge=1, le=100),
    intraday_session_scope: str = Query(default="regular", pattern="^(regular|extended|all)$"),
    db: Session = Depends(get_db),
):
    try:
        return get_us_watchlist_ranking(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            rank_by=rank_by,
            sort_order=sort_order,
            use_intraday=use_intraday,
            intraday_limit=intraday_limit,
            intraday_session_scope=intraday_session_scope,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise _group_error(exc) from exc


@router.get(
    "/watchlists/groups/{group_id}/radar",
    response_model=WatchlistGroupRadarRead,
)
def get_us_watchlist_radar_api(
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    mode: str = Query(
        default="action",
        pattern="^(action|surge|breakout|volume|overheat|weakness|risk|momentum|all)$",
    ),
    max_results: int = Query(default=30, ge=1, le=200),
    calculation_limit: int = Query(default=100, ge=20, le=500),
    use_intraday: bool = False,
    intraday_limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    try:
        return get_us_watchlist_technical_radar(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            mode=mode,
            max_results=max_results,
            calculation_limit=calculation_limit,
            use_intraday=use_intraday,
            intraday_limit=intraday_limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise _group_error(exc) from exc


@router.patch("/watchlists/items/{item_id}", response_model=USWatchlistItemRead)
def update_us_watchlist_item_api(
    item_id: int,
    payload: USWatchlistItemUpdate,
    db: Session = Depends(get_db),
):
    try:
        return update_us_watchlist_item(db=db, item_id=item_id, payload=payload)
    except Exception as exc:
        raise _item_error(exc) from exc


@router.delete("/watchlists/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_us_watchlist_item_api(
    item_id: int,
    db: Session = Depends(get_db),
):
    try:
        delete_us_watchlist_item(db=db, item_id=item_id)
    except Exception as exc:
        raise _item_error(exc) from exc
    return None


@router.post(
    "/watchlists/daily/refresh",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_all_us_watchlist_daily_prices_api(
    include_children: bool = True,
    enabled_only: bool = True,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    adjusted: bool = False,
    sleep_seconds: float | None = Query(default=None, ge=0, le=120),
    db: Session = Depends(get_db),
):
    resolved_sleep_seconds = resolve_observed_stock_refresh_interval_seconds(
        db=db,
        market="us",
        explicit_sleep_seconds=sleep_seconds,
    )
    return _enqueue_us_watchlist_daily_refresh(
        db=db,
        group_id=None,
        include_children=include_children,
        enabled_only=enabled_only,
        outputsize=outputsize,
        adjusted=adjusted,
        sleep_seconds=resolved_sleep_seconds,
    )


@router.post(
    "/watchlists/groups/{group_id}/refresh-daily",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_us_watchlist_group_daily_prices_api(
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    adjusted: bool = False,
    sleep_seconds: float | None = Query(default=None, ge=0, le=120),
    db: Session = Depends(get_db),
):
    try:
        get_us_watchlist_group(db=db, group_id=group_id)
        resolved_sleep_seconds = resolve_observed_stock_refresh_interval_seconds(
            db=db,
            market="us",
            explicit_sleep_seconds=sleep_seconds,
        )
        return _enqueue_us_watchlist_daily_refresh(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            outputsize=outputsize,
            adjusted=adjusted,
            sleep_seconds=resolved_sleep_seconds,
        )
    except Exception as exc:
        raise _group_error(exc) from exc


@router.post(
    "/watchlists/resources/refresh",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_all_us_watchlist_resources_api(
    include_children: bool = True,
    enabled_only: bool = True,
    include_daily: bool = True,
    include_sec_facts: bool = True,
    include_profile: bool = True,
    include_actions: bool = False,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    adjusted: bool = False,
    sleep_seconds: float | None = Query(default=None, ge=0, le=120),
    db: Session = Depends(get_db),
):
    resolved_sleep_seconds = resolve_subresource_refresh_interval_seconds(
        db=db,
        market="us",
        explicit_sleep_seconds=sleep_seconds,
    )
    return _enqueue_us_watchlist_resource_refresh(
        db=db,
        group_id=None,
        include_children=include_children,
        enabled_only=enabled_only,
        include_daily=include_daily,
        include_sec_facts=include_sec_facts,
        include_profile=include_profile,
        include_actions=include_actions,
        outputsize=outputsize,
        adjusted=adjusted,
        sleep_seconds=resolved_sleep_seconds,
    )


@router.post(
    "/watchlists/groups/{group_id}/refresh-resources",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_us_watchlist_group_resources_api(
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    include_daily: bool = True,
    include_sec_facts: bool = True,
    include_profile: bool = True,
    include_actions: bool = False,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    adjusted: bool = False,
    sleep_seconds: float | None = Query(default=None, ge=0, le=120),
    db: Session = Depends(get_db),
):
    try:
        get_us_watchlist_group(db=db, group_id=group_id)
        resolved_sleep_seconds = resolve_subresource_refresh_interval_seconds(
            db=db,
            market="us",
            explicit_sleep_seconds=sleep_seconds,
        )
        return _enqueue_us_watchlist_resource_refresh(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            include_daily=include_daily,
            include_sec_facts=include_sec_facts,
            include_profile=include_profile,
            include_actions=include_actions,
            outputsize=outputsize,
            adjusted=adjusted,
            sleep_seconds=resolved_sleep_seconds,
        )
    except Exception as exc:
        raise _group_error(exc) from exc


@router.post("/stocks/sync-symbols", response_model=USSymbolSyncResultRead)
def sync_us_stock_symbols(
    include_sec_company_data: bool = True,
    deactivate_missing: bool = False,
    db: Session = Depends(get_db),
):
    try:
        return sync_us_symbol_master(
            db=db,
            include_sec_company_data=include_sec_company_data,
            deactivate_missing=deactivate_missing,
        )
    except USMarketConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except USMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.post("/stocks/sync-sec-company-data", response_model=USSymbolSyncResultRead)
def sync_us_stock_sec_company_data(db: Session = Depends(get_db)):
    try:
        return sync_us_sec_company_data(db=db)
    except USMarketConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except USMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.get("/source-health", response_model=USSourceHealthRead)
def get_us_source_health(
    symbol: str | None = None,
    series_id: str | None = None,
    db: Session = Depends(get_db),
):
    return build_us_source_health(
        db=db,
        symbol=symbol,
        series_id=series_id,
    )


@router.get("/stocks/search", response_model=list[USStockMasterRead])
def search_us_stock_master(
    keyword: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return search_us_stocks(
        db=db,
        keyword=keyword,
        limit=limit,
        discover_missing_exact_symbol=True,
    )


@router.get("/stocks", response_model=list[USStockMasterRead])
def list_us_stock_master(
    exchange: str | None = None,
    asset_type: str | None = None,
    is_active: bool | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_us_stocks(
        db=db,
        exchange=exchange,
        asset_type=asset_type,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )


@router.get("/stocks/{symbol}", response_model=USStockMasterRead)
def get_us_stock_master(symbol: str, db: Session = Depends(get_db)):
    try:
        return get_us_stock(db=db, symbol=symbol)
    except USStockNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/daily/quality/repair",
    response_model=USDailyPriceQualityRepairResultRead,
)
def repair_us_daily_price_quality_api(
    symbol: str | None = None,
    dry_run: bool = True,
    limit: int = Query(default=1000, ge=1, le=10000),
    refresh: bool = False,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    adjusted: bool = False,
    sleep_seconds: float = Query(default=0.0, ge=0, le=120),
    db: Session = Depends(get_db),
):
    try:
        return repair_us_daily_price_quality(
            db=db,
            symbol=symbol,
            dry_run=dry_run,
            limit=limit,
            refresh=refresh,
            outputsize=outputsize,
            adjusted=adjusted,
            sleep_seconds=sleep_seconds,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/daily/quality/repair-job",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def repair_us_daily_price_quality_job_api(
    symbol: str | None = None,
    dry_run: bool = True,
    limit: int = Query(default=1000, ge=1, le=10000),
    refresh: bool = False,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    adjusted: bool = False,
    sleep_seconds: float = Query(default=0.0, ge=0, le=120),
    db: Session = Depends(get_db),
):
    return _enqueue_us_daily_price_quality_repair(
        db=db,
        symbol=symbol,
        dry_run=dry_run,
        limit=limit,
        refresh=refresh,
        outputsize=outputsize,
        adjusted=adjusted,
        sleep_seconds=sleep_seconds,
    )


@router.post("/daily/{symbol}/refresh", response_model=USDailyPriceRefreshResultRead)
def refresh_us_daily_prices(
    symbol: str,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    adjusted: bool = False,
    provider: str = Query(
        default="auto",
        pattern="^(auto|alphavantage|yahoo_chart)$",
        deprecated=True,
        description=(
            "Compatibility-only. Canonical refresh owns provider resolution; "
            "non-auto values are rejected."
        ),
    ),
    db: Session = Depends(get_db),
):
    try:
        if provider != "auto":
            raise ValueError(
                "provider is compatibility-only; canonical refresh requires provider=auto"
            )
        if adjusted:
            raise ValueError(
                "canonical US daily refresh currently supports price_basis=raw only"
            )
        return refresh_us_daily_ohlcv(
            db=db,
            symbol=symbol,
            outputsize=outputsize,
            adjusted=adjusted,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except USMarketConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except USMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.get("/daily/{symbol}/history", response_model=list[USDailyPriceRead])
def list_us_daily_history(
    symbol: str,
    provider: str | None = Query(
        default=None,
        deprecated=True,
        description="Compatibility-only; canonical history no longer selects providers.",
    ),
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        return read_us_daily_ohlcv_history(
            db=db,
            symbol=symbol,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            offset=offset,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/ohlc/{symbol}", response_model=USOhlcChartRead)
def get_us_ohlc_chart_data(
    symbol: str,
    timeframe: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    bars: int = Query(default=90, ge=1, le=5000),
    to_date: date | None = None,
    db: Session = Depends(get_db),
):
    try:
        return read_us_daily_ohlcv_chart(
            db=db,
            symbol=symbol,
            timeframe=timeframe,
            bars=bars,
            to_date=to_date,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except USMarketConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except USMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.post(
    "/diagnostics/providers/{provider}/ohlc/{symbol}/repair",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    deprecated=True,
)
def repair_us_ohlc_history_api(
    symbol: str,
    provider: str = Path(pattern="^(alphavantage|yahoo_chart)$"),
    timeframe: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    bars: int = Query(default=180, ge=1, le=5000),
    adjusted: bool = False,
    max_provider_calls: int = Query(default=2, ge=1, le=2),
    force_full: bool = False,
    db: Session = Depends(get_db),
):
    return _enqueue_us_ohlc_history_repair(
        db=db,
        symbol=symbol,
        timeframe=timeframe,
        bars=bars,
        provider=provider,
        adjusted=adjusted,
        max_provider_calls=max_provider_calls,
        force_full=force_full,
    )


@router.get("/intraday/{symbol}", response_model=USIntradayTrendRead)
def get_us_intraday_trend_api(
    symbol: str,
    session_scope: str = Query(default="regular", pattern="^(regular|extended|all)$"),
    interval: str = Query(default="1m", pattern="^(1m|5m|15m|30m|1h|4h)$"),
    db: Session = Depends(get_db),
):
    return get_us_intraday_trend(
        symbol=symbol,
        session_scope=session_scope,
        interval=interval,
        db=db,
    )


@router.post("/source-health/snapshot", response_model=USSourceHealthRead)
def create_us_source_health_snapshot(
    symbol: str | None = None,
    series_id: str | None = None,
    db: Session = Depends(get_db),
):
    return snapshot_us_source_health(
        db=db,
        symbol=symbol,
        series_id=series_id,
    )


@router.get("/quote/{symbol}", response_model=USResolvedQuoteSnapshotRead)
def get_us_quote_snapshot_api(
    symbol: str,
    db: Session = Depends(get_db),
):
    """Read persisted resolved Quote evidence without provider acquisition."""

    try:
        return get_us_quote_snapshot(db, symbol=symbol)
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/quote/{symbol}/refresh", response_model=dict)
def refresh_us_quote_snapshot_api(
    symbol: str,
    require_live: bool = False,
    max_provider_calls: int = Query(default=2, ge=1, le=2),
    db: Session = Depends(get_db),
):
    """Explicit bounded provider acquisition; persists then rereads canonical quote evidence."""

    try:
        return refresh_us_quote_snapshot(
            db,
            symbol=symbol,
            require_live=require_live,
            max_provider_calls=max_provider_calls,
        )
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/intraday/{symbol}/refresh", response_model=dict)
def refresh_us_intraday_bars_api(
    symbol: str,
    require_live: bool = False,
    max_provider_calls: int = Query(default=2, ge=1, le=2),
    db: Session = Depends(get_db),
):
    """Explicit bounded provider acquisition; persists then rereads canonical bars."""

    try:
        return refresh_us_intraday_bars(
            db,
            symbol=symbol,
            require_live=require_live,
            max_provider_calls=max_provider_calls,
        )
    except (LookupError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/research/{symbol}", response_model=USMarketResearchRead)
def get_us_market_research_api(
    symbol: str,
    bars: int = Query(default=260, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Read bounded research from cached resolved evidence without provider IO."""

    try:
        return build_us_market_research(db, symbol=symbol, bars=bars)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/sec/{symbol}/refresh-facts", response_model=USSecFactRefreshResultRead)
def refresh_us_sec_facts(symbol: str, db: Session = Depends(get_db)):
    try:
        return refresh_us_sec_companyfacts(db=db, symbol=symbol)
    except USStockNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except USMarketConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except USMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.get("/sec/{symbol}/facts", response_model=list[USSecCompanyFactRead])
def list_us_sec_facts(
    symbol: str,
    taxonomy: str | None = None,
    tag: str | None = None,
    form: str | None = None,
    fiscal_year: int | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_us_sec_company_facts(
        db=db,
        symbol=symbol,
        taxonomy=taxonomy,
        tag=tag,
        form=form,
        fiscal_year=fiscal_year,
        limit=limit,
        offset=offset,
    )


@router.get("/sec/{symbol}/fundamentals", response_model=USSecFundamentalSummaryRead)
def get_us_sec_fundamentals(symbol: str, db: Session = Depends(get_db)):
    try:
        return get_us_sec_fundamental_summary(db=db, symbol=symbol)
    except USStockNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/sec/{symbol}/financials", response_model=USSecFinancialContractRead)
def get_us_sec_financials(
    symbol: str,
    mode: str = Query(
        default="current_comparable",
        pattern="^(current_comparable|as_reported_as_of)$",
    ),
    periods: int = Query(default=8, ge=4, le=12),
    db: Session = Depends(get_db),
):
    try:
        return get_us_sec_financial_contract(
            db=db,
            symbol=symbol,
            mode=mode,
            periods=periods,
        )
    except USStockNotFoundError as exc:
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
    "/sec/{symbol}/insider-transactions",
    response_model=USSecInsiderTransactionsRead,
)
def get_us_sec_insider_transactions(
    symbol: str,
    from_date: date | None = None,
    to_date: date | None = None,
    codes: str | None = Query(default=None, max_length=80),
    include_derivatives: bool = True,
    limit: int = Query(default=100, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=256),
    db: Session = Depends(get_db),
):
    try:
        parsed_codes = tuple(
            item.strip().upper()
            for item in str(codes or "").split(",")
            if item.strip()
        )
        return read_insider_transactions(
            db,
            symbol=symbol,
            from_date=from_date,
            to_date=to_date,
            codes=parsed_codes,
            include_derivatives=include_derivatives,
            limit=limit,
            cursor=cursor,
        )
    except USStockNotFoundError as exc:
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
    "/sec/ownership/jobs/form4-sync",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_us_sec_form4_sync(
    request: USSecForm4SyncRequest,
    db: Session = Depends(get_db),
):
    try:
        return _enqueue_us_sec_form4_sync(db=db, request_model=request)
    except (ValueError, USMarketConfigurationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/sec/{symbol}/institutional-holdings",
    response_model=USSec13FInstitutionalHoldingsRead,
)
def get_us_sec_institutional_holdings(
    symbol: str,
    manager_limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    try:
        return get_13f_symbol_contract(
            db,
            symbol=symbol,
            manager_limit=manager_limit,
        )
    except USStockNotFoundError as exc:
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
    "/sec/ownership/coverage",
    response_model=USSec13FCoverageRead,
)
def get_us_sec_13f_coverage(db: Session = Depends(get_db)):
    return get_13f_coverage_contract(db)


@router.post(
    "/sec/ownership/jobs/13f-quarter-sync",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_us_sec_13f_quarter_sync(
    request: USSec13FQuarterSyncRequest,
    db: Session = Depends(get_db),
):
    try:
        return _enqueue_us_sec_13f_quarter_sync(db=db, request_model=request)
    except (ValueError, USMarketConfigurationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/sec/ownership/jobs/13f-mapping-sync",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_us_sec_13f_mapping_sync(
    request: USSec13FMappingSyncRequest,
    db: Session = Depends(get_db),
):
    try:
        return _enqueue_us_sec_13f_mapping_sync(db=db, request_model=request)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/sec/ownership/jobs/13f-history-sync",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def enqueue_us_sec_13f_history_sync(
    request: USSec13FHistorySyncRequest,
    db: Session = Depends(get_db),
):
    try:
        return _enqueue_us_sec_13f_history_sync(db=db, request_model=request)
    except (ValueError, USMarketConfigurationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/profiles/{symbol}/refresh", response_model=USResourceRefreshResultRead)
def refresh_us_company_profile(symbol: str, db: Session = Depends(get_db)):
    try:
        return refresh_us_company_profile_from_alphavantage(db=db, symbol=symbol)
    except USMarketConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except USMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.get("/profiles", response_model=list[USCompanyProfileRead])
def list_us_profiles(
    sector: str | None = None,
    industry: str | None = None,
    provider: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_us_company_profiles(
        db=db,
        sector=sector,
        industry=industry,
        provider=provider,
        limit=limit,
        offset=offset,
    )


@router.get("/profiles/{symbol}", response_model=USCompanyProfileRead)
def get_us_profile(
    symbol: str,
    provider: str | None = None,
    db: Session = Depends(get_db),
):
    profile = get_us_company_profile(db=db, symbol=symbol, provider=provider)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"US company profile for symbol='{symbol}' not found.",
        )
    return profile


@router.post("/corporate-actions/{symbol}/refresh", response_model=USResourceRefreshResultRead)
def refresh_us_corporate_actions(symbol: str, db: Session = Depends(get_db)):
    try:
        return refresh_us_corporate_actions_from_alphavantage(db=db, symbol=symbol)
    except USMarketConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except USMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.get("/corporate-actions/{symbol}", response_model=list[USCorporateActionRead])
def list_us_actions(
    symbol: str,
    action_type: str | None = Query(default=None, pattern="^(dividend|split)$"),
    provider: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_us_corporate_actions(
        db=db,
        symbol=symbol,
        action_type=action_type,
        provider=provider,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )


@router.post("/short-volume/finra/{trade_date}/refresh", response_model=USResourceRefreshResultRead)
def refresh_us_short_volume(trade_date: date, db: Session = Depends(get_db)):
    try:
        return refresh_us_short_volume_from_finra(db=db, trade_date=trade_date)
    except USMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.get("/short-volume/{symbol}/history", response_model=list[USShortVolumeDailyRead])
def list_us_short_volume_history(
    symbol: str,
    provider: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_us_short_volumes(
        db=db,
        symbol=symbol,
        provider=provider,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )


@router.post("/macro/fred/{series_id}/refresh", response_model=USResourceRefreshResultRead)
def refresh_us_macro_series(
    series_id: str,
    observation_start: date | None = None,
    observation_end: date | None = None,
    db: Session = Depends(get_db),
):
    try:
        return refresh_fred_macro_series(
            db=db,
            series_id=series_id,
            observation_start=observation_start,
            observation_end=observation_end,
        )
    except USMarketConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except USMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.get("/macro/{series_id}/observations", response_model=list[MacroSeriesObservationRead])
def list_us_macro_observations(
    series_id: str,
    provider: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_macro_series_observations(
        db=db,
        series_id=series_id,
        provider=provider,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )
