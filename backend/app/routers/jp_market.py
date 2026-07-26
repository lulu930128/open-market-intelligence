from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.jobs import backfill_tasks
from app.jobs.job_types import JP_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE
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
from app.jp_market.errors import JPMarketDataFetchError
from app.jp_market.schemas import (
    JPCompanyFundamentalRead,
    JPDailyPriceRead,
    JPDailyPriceRefreshResultRead,
    JPIntradayTrendRead,
    JPMarketOverviewRead,
    JPOhlcChartRead,
    JPResourceSummaryRead,
    JPResourceRefreshResultRead,
    JPSourceHealthRead,
    JPStockMasterRead,
    JPStockMasterSyncResultRead,
    JPWatchlistGroupCreate,
    JPWatchlistGroupDeleteResultRead,
    JPWatchlistGroupRead,
    JPWatchlistGroupTreeRead,
    JPWatchlistGroupUpdate,
    JPWatchlistItemCreate,
    JPWatchlistItemRead,
    JPWatchlistItemUpdate,
    JPWatchlistRankingRead,
)
from app.jp_market.source_health import build_jp_source_health
from app.watchlists.schemas import WatchlistGroupRadarRead
from app.jp_market.service import (
    JPWatchlistDuplicateItemError,
    JPWatchlistGroupNotEmptyError,
    JPWatchlistGroupNotFoundError,
    JPWatchlistInvalidTreeError,
    JPWatchlistItemNotFoundError,
    JPStockNotFoundError,
    create_jp_watchlist_group,
    create_jp_watchlist_item,
    delete_jp_watchlist_group,
    delete_jp_watchlist_item,
    get_jp_company_fundamental,
    get_jp_watchlist_tree,
    get_jp_watchlist_group,
    get_jp_watchlist_ranking,
    get_jp_watchlist_technical_radar,
    get_jp_intraday_trend,
    get_jp_market_overview,
    get_jp_stock,
    get_jp_resource_summary,
    list_jp_daily_prices,
    list_jp_company_fundamentals,
    list_jp_ohlc_chart_data,
    list_jp_stocks,
    list_jp_watchlist_groups,
    list_jp_watchlist_items,
    refresh_jp_market_resource,
    refresh_jp_company_fundamental as refresh_jp_company_fundamental_service,
    refresh_jp_daily_prices as refresh_jp_daily_prices_service,
    search_jp_stocks,
    sync_jp_symbol_master,
    update_jp_watchlist_group,
    update_jp_watchlist_item,
)


router = APIRouter()


def _fetch_error(exc: Exception) -> HTTPException:
    return fetch_error(exc)


def _group_error(exc: Exception) -> HTTPException:
    return watchlist_group_error(
        exc,
        not_found_errors=(JPWatchlistGroupNotFoundError,),
        bad_request_errors=(JPWatchlistInvalidTreeError, JPWatchlistGroupNotEmptyError),
    )


def _item_error(exc: Exception) -> HTTPException:
    return watchlist_item_error(
        exc,
        not_found_errors=(JPWatchlistGroupNotFoundError, JPWatchlistItemNotFoundError, JPStockNotFoundError),
        duplicate_errors=(JPWatchlistDuplicateItemError,),
    )


@router.get("/source-health", response_model=JPSourceHealthRead)
def get_jp_source_health(
    symbol: str | None = None,
    expected_daily_price_date: date | None = None,
    use_expected_date: bool = True,
    db: Session = Depends(get_db),
):
    return build_jp_source_health(
        db=db,
        symbol=symbol,
        expected_daily_price_date=expected_daily_price_date,
        use_expected_date=use_expected_date,
    )


@router.get("/overview", response_model=JPMarketOverviewRead)
def get_jp_market_overview_api(
    sector_limit: int = Query(default=10, ge=1, le=33),
    mover_limit: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    return get_jp_market_overview(
        db=db,
        sector_limit=sector_limit,
        mover_limit=mover_limit,
    )


def _enqueue_jp_watchlist_resource_refresh(
    *,
    db: Session,
    group_id: int | None,
    include_children: bool,
    enabled_only: bool,
    include_daily: bool,
    include_fundamentals: bool,
    outputsize: str,
    provider: str,
    sleep_seconds: float,
) -> dict:
    target = watchlist_group_target(group_id)
    request = {
        "group_id": group_id,
        "include_children": include_children,
        "enabled_only": enabled_only,
        "include_daily": include_daily,
        "include_fundamentals": include_fundamentals,
        "outputsize": outputsize,
        "provider": provider,
        "sleep_seconds": sleep_seconds,
    }
    return enqueue_serialized_job(
        db=db,
        job_type=JP_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE,
        target=target,
        request=request,
        progress_total=1,
        message="Queued JP watchlist resource refresh.",
        task=backfill_tasks.run_jp_watchlist_resource_refresh_job,
        task_args=(
            group_id,
            include_children,
            enabled_only,
            include_daily,
            include_fundamentals,
            outputsize,
            provider,
            sleep_seconds,
        ),
    )


@router.post("/stocks/sync-symbols", response_model=JPStockMasterSyncResultRead)
def sync_jp_stock_symbols(
    deactivate_missing: bool = False,
    db: Session = Depends(get_db),
):
    try:
        return sync_jp_symbol_master(
            db=db,
            deactivate_missing=deactivate_missing,
        )
    except JPMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.get("/stocks/search", response_model=list[JPStockMasterRead])
def search_jp_stock_master(
    keyword: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return search_jp_stocks(
        db=db,
        keyword=keyword,
        limit=limit,
    )


@router.get("/stocks", response_model=list[JPStockMasterRead])
def list_jp_stock_master(
    exchange: str | None = None,
    asset_type: str | None = None,
    is_active: bool | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_jp_stocks(
        db=db,
        exchange=exchange,
        asset_type=asset_type,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )


@router.get("/stocks/{symbol}", response_model=JPStockMasterRead)
def get_jp_stock_master(symbol: str, db: Session = Depends(get_db)):
    try:
        return get_jp_stock(db=db, symbol=symbol)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except JPStockNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/resources/{symbol}/summary", response_model=JPResourceSummaryRead)
def get_jp_resource_summary_api(symbol: str, db: Session = Depends(get_db)):
    try:
        return get_jp_resource_summary(db=db, symbol=symbol)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/resources/{symbol}/refresh", response_model=JPResourceRefreshResultRead)
def refresh_jp_market_resource_api(
    symbol: str,
    resource: str = Query(
        default="demand",
        pattern="^(demand|investors|disclosures|performance|financials)$",
    ),
    db: Session = Depends(get_db),
):
    try:
        return refresh_jp_market_resource(
            db=db,
            symbol=symbol,
            resource=resource,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except JPMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.post("/fundamentals/{symbol}/refresh", response_model=JPResourceRefreshResultRead)
def refresh_jp_company_fundamental(
    symbol: str,
    provider: str = Query(default="auto", pattern="^(auto|jquants_statements|yahoo_quote_summary)$"),
    db: Session = Depends(get_db),
):
    try:
        return refresh_jp_company_fundamental_service(
            db=db,
            symbol=symbol,
            provider=provider,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except JPMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.get("/fundamentals", response_model=list[JPCompanyFundamentalRead])
def list_jp_fundamentals(
    provider: str | None = None,
    sector: str | None = None,
    industry: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_jp_company_fundamentals(
        db=db,
        provider=provider,
        sector=sector,
        industry=industry,
        limit=limit,
        offset=offset,
    )


@router.get("/fundamentals/{symbol}", response_model=JPCompanyFundamentalRead)
def get_jp_fundamental(
    symbol: str,
    provider: str | None = None,
    db: Session = Depends(get_db),
):
    try:
        fundamental = get_jp_company_fundamental(db=db, symbol=symbol, provider=provider)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if fundamental is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"JP company fundamental for symbol='{symbol}' not found.",
        )

    return fundamental


@router.post("/daily/{symbol}/refresh", response_model=JPDailyPriceRefreshResultRead)
def refresh_jp_daily_prices(
    symbol: str,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    provider: str = Query(default="auto", pattern="^(auto|yahoo_chart)$"),
    db: Session = Depends(get_db),
):
    try:
        return refresh_jp_daily_prices_service(
            db=db,
            symbol=symbol,
            outputsize=outputsize,
            provider=provider,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except JPMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.get("/daily/{symbol}/history", response_model=list[JPDailyPriceRead])
def list_jp_daily_history(
    symbol: str,
    provider: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        return list_jp_daily_prices(
            db=db,
            symbol=symbol,
            provider=provider,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/watchlists/groups",
    response_model=JPWatchlistGroupRead,
    status_code=status.HTTP_201_CREATED,
)
def create_jp_watchlist_group_api(
    payload: JPWatchlistGroupCreate,
    db: Session = Depends(get_db),
):
    try:
        return create_jp_watchlist_group(db=db, payload=payload)
    except Exception as exc:
        raise _group_error(exc) from exc


@router.get("/watchlists/groups", response_model=list[JPWatchlistGroupRead])
def list_jp_watchlist_groups_api(
    is_active: bool | None = None,
    db: Session = Depends(get_db),
):
    return list_jp_watchlist_groups(db=db, is_active=is_active)


@router.get("/watchlists/tree", response_model=list[JPWatchlistGroupTreeRead])
def get_jp_watchlist_tree_api(
    is_active: bool | None = True,
    db: Session = Depends(get_db),
):
    return get_jp_watchlist_tree(db=db, is_active=is_active)


@router.patch("/watchlists/groups/{group_id}", response_model=JPWatchlistGroupRead)
def update_jp_watchlist_group_api(
    group_id: int,
    payload: JPWatchlistGroupUpdate,
    db: Session = Depends(get_db),
):
    try:
        return update_jp_watchlist_group(db=db, group_id=group_id, payload=payload)
    except Exception as exc:
        raise _group_error(exc) from exc


@router.delete(
    "/watchlists/groups/{group_id}",
    response_model=JPWatchlistGroupDeleteResultRead,
)
def delete_jp_watchlist_group_api(
    group_id: int,
    recursive: bool = False,
    db: Session = Depends(get_db),
):
    try:
        return delete_jp_watchlist_group(db=db, group_id=group_id, recursive=recursive)
    except Exception as exc:
        raise _group_error(exc) from exc


@router.post(
    "/watchlists/items",
    response_model=JPWatchlistItemRead,
    status_code=status.HTTP_201_CREATED,
)
def create_jp_watchlist_item_api(
    payload: JPWatchlistItemCreate,
    db: Session = Depends(get_db),
):
    try:
        return create_jp_watchlist_item(db=db, payload=payload)
    except Exception as exc:
        raise _item_error(exc) from exc


@router.get("/watchlists/items", response_model=list[JPWatchlistItemRead])
def list_jp_watchlist_items_api(
    group_id: int | None = None,
    symbol: str | None = None,
    enabled: bool | None = None,
    include_children: bool = False,
    limit: int = Query(default=100, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        return list_jp_watchlist_items(
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


@router.get("/watchlists/ranking", response_model=JPWatchlistRankingRead)
def get_jp_watchlist_ranking_api(
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = Query(default="none", pattern="^(none|change_pct|volume|close)$"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    try:
        return get_jp_watchlist_ranking(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            rank_by=rank_by,
            sort_order=sort_order,
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
def get_jp_watchlist_radar_api(
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    mode: str = Query(
        default="action",
        pattern="^(action|surge|breakout|volume|overheat|weakness|risk|momentum|all)$",
    ),
    max_results: int = Query(default=30, ge=1, le=200),
    calculation_limit: int = Query(default=100, ge=20, le=500),
    db: Session = Depends(get_db),
):
    try:
        return get_jp_watchlist_technical_radar(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            mode=mode,
            max_results=max_results,
            calculation_limit=calculation_limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise _group_error(exc) from exc


@router.post(
    "/watchlists/daily/refresh",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_all_jp_watchlist_daily_prices_api(
    include_children: bool = True,
    enabled_only: bool = True,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    provider: str = Query(default="auto", pattern="^(auto|yahoo_chart)$"),
    sleep_seconds: float | None = Query(default=None, ge=0, le=60),
    db: Session = Depends(get_db),
):
    resolved_sleep_seconds = resolve_observed_stock_refresh_interval_seconds(
        db=db,
        market="jp",
        explicit_sleep_seconds=sleep_seconds,
    )
    return _enqueue_jp_watchlist_resource_refresh(
        db=db,
        group_id=None,
        include_children=include_children,
        enabled_only=enabled_only,
        include_daily=True,
        include_fundamentals=False,
        outputsize=outputsize,
        provider=provider,
        sleep_seconds=resolved_sleep_seconds,
    )


@router.post(
    "/watchlists/groups/{group_id}/refresh-daily",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_jp_watchlist_group_daily_prices_api(
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    provider: str = Query(default="auto", pattern="^(auto|yahoo_chart)$"),
    sleep_seconds: float | None = Query(default=None, ge=0, le=60),
    db: Session = Depends(get_db),
):
    try:
        get_jp_watchlist_group(db=db, group_id=group_id)
        resolved_sleep_seconds = resolve_observed_stock_refresh_interval_seconds(
            db=db,
            market="jp",
            explicit_sleep_seconds=sleep_seconds,
        )
        return _enqueue_jp_watchlist_resource_refresh(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            include_daily=True,
            include_fundamentals=False,
            outputsize=outputsize,
            provider=provider,
            sleep_seconds=resolved_sleep_seconds,
        )
    except Exception as exc:
        raise _group_error(exc) from exc


@router.post(
    "/watchlists/resources/refresh",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_all_jp_watchlist_resources_api(
    include_children: bool = True,
    enabled_only: bool = True,
    include_daily: bool = True,
    include_fundamentals: bool = True,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    provider: str = Query(default="auto", pattern="^(auto|yahoo_chart)$"),
    sleep_seconds: float | None = Query(default=None, ge=0, le=60),
    db: Session = Depends(get_db),
):
    resolved_sleep_seconds = resolve_subresource_refresh_interval_seconds(
        db=db,
        market="jp",
        explicit_sleep_seconds=sleep_seconds,
    )
    return _enqueue_jp_watchlist_resource_refresh(
        db=db,
        group_id=None,
        include_children=include_children,
        enabled_only=enabled_only,
        include_daily=include_daily,
        include_fundamentals=include_fundamentals,
        outputsize=outputsize,
        provider=provider,
        sleep_seconds=resolved_sleep_seconds,
    )


@router.post(
    "/watchlists/groups/{group_id}/refresh-resources",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_jp_watchlist_group_resources_api(
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    include_daily: bool = True,
    include_fundamentals: bool = True,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    provider: str = Query(default="auto", pattern="^(auto|yahoo_chart)$"),
    sleep_seconds: float | None = Query(default=None, ge=0, le=60),
    db: Session = Depends(get_db),
):
    try:
        get_jp_watchlist_group(db=db, group_id=group_id)
        resolved_sleep_seconds = resolve_subresource_refresh_interval_seconds(
            db=db,
            market="jp",
            explicit_sleep_seconds=sleep_seconds,
        )
        return _enqueue_jp_watchlist_resource_refresh(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            include_daily=include_daily,
            include_fundamentals=include_fundamentals,
            outputsize=outputsize,
            provider=provider,
            sleep_seconds=resolved_sleep_seconds,
        )
    except Exception as exc:
        raise _group_error(exc) from exc


@router.patch("/watchlists/items/{item_id}", response_model=JPWatchlistItemRead)
def update_jp_watchlist_item_api(
    item_id: int,
    payload: JPWatchlistItemUpdate,
    db: Session = Depends(get_db),
):
    try:
        return update_jp_watchlist_item(db=db, item_id=item_id, payload=payload)
    except Exception as exc:
        raise _item_error(exc) from exc


@router.delete("/watchlists/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_jp_watchlist_item_api(
    item_id: int,
    db: Session = Depends(get_db),
):
    try:
        delete_jp_watchlist_item(db=db, item_id=item_id)
    except Exception as exc:
        raise _item_error(exc) from exc
    return None


@router.get("/ohlc/{symbol}", response_model=JPOhlcChartRead)
def get_jp_ohlc_chart_data(
    symbol: str,
    timeframe: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    bars: int = Query(default=90, ge=1, le=5000),
    ensure_history: bool = False,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    provider: str = Query(default="auto", pattern="^(auto|yahoo_chart)$"),
    to_date: date | None = None,
    db: Session = Depends(get_db),
):
    try:
        return list_jp_ohlc_chart_data(
            db=db,
            symbol=symbol,
            timeframe=timeframe,
            bars=bars,
            ensure_history=ensure_history,
            outputsize=outputsize,
            provider=provider,
            to_date=to_date,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except JPMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.get("/intraday/{symbol}", response_model=JPIntradayTrendRead)
def get_jp_intraday_trend_api(
    symbol: str,
    refresh: bool = False,
    db: Session = Depends(get_db),
):
    try:
        return get_jp_intraday_trend(
            db=db,
            symbol=symbol,
            refresh=refresh,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
