from __future__ import annotations

from datetime import date

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.jobs import backfill_tasks, service as job_service
from app.jobs.job_types import KR_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE
from app.jobs.schemas import JobRunRead
from app.kr_market.schemas import (
    KRCompanyFundamentalRead,
    KRDailyPriceRead,
    KRDailyPriceRefreshResultRead,
    KRIndexOhlcChartRead,
    KRIndexIntradayTrendRead,
    KRIndexRefreshBatchResultRead,
    KRIndexRefreshResultRead,
    KRIndexSummaryRead,
    KRInvestorTradeDailyRead,
    KRMarketBreadthRead,
    KRMarketBreadthRefreshResultRead,
    KROhlcChartRead,
    KRMarketIndexRead,
    KRMarketIndexSyncResultRead,
    KRResourceRefreshResultRead,
    KRResourceSummaryRead,
    KRSourceHealthRead,
    KRStockMasterRead,
    KRStockMasterSyncResultRead,
    KRWatchlistGroupCreate,
    KRWatchlistGroupDeleteResultRead,
    KRWatchlistGroupRead,
    KRWatchlistGroupTreeRead,
    KRWatchlistGroupUpdate,
    KRWatchlistItemCreate,
    KRWatchlistItemRead,
    KRWatchlistItemUpdate,
    KRWatchlistRankingRead,
    KRWatchlistReadinessRead,
)
from app.kr_market.service import (
    KRIndexNotFoundError,
    KRStockNotFoundError,
    KRWatchlistDuplicateItemError,
    KRWatchlistGroupNotEmptyError,
    KRWatchlistGroupNotFoundError,
    KRWatchlistInvalidTreeError,
    KRWatchlistItemNotFoundError,
    build_kr_source_health,
    create_kr_watchlist_group,
    create_kr_watchlist_item,
    delete_kr_watchlist_group,
    delete_kr_watchlist_item,
    get_kr_index_summary,
    get_kr_index_intraday_trend,
    get_kr_market_breadth,
    get_kr_market_index_config,
    get_kr_resource_summary,
    get_kr_stock,
    get_kr_watchlist_group,
    get_kr_watchlist_ranking,
    get_kr_watchlist_readiness,
    get_kr_watchlist_technical_radar,
    get_kr_watchlist_tree,
    list_kr_index_ohlc_chart_data,
    list_kr_market_indices,
    list_kr_company_fundamentals,
    list_kr_daily_prices,
    list_kr_investor_trades,
    list_kr_ohlc_chart_data,
    list_kr_stocks,
    list_kr_watchlist_groups,
    list_kr_watchlist_items,
    refresh_kr_company_fundamental as refresh_kr_company_fundamental_service,
    refresh_kr_daily_prices as refresh_kr_daily_prices_service,
    refresh_kr_index_daily_prices as refresh_kr_index_daily_prices_service,
    refresh_kr_market_breadth_daily_prices,
    refresh_kr_market_indices,
    refresh_kr_market_resource,
    sync_kr_index_master,
    search_kr_stocks,
    sync_kr_symbol_master,
    update_kr_watchlist_group,
    update_kr_watchlist_item,
)
from app.kr_market.sources import KRMarketDataFetchError
from app.settings.refresh_execution import (
    resolve_observed_stock_refresh_interval_seconds,
    resolve_subresource_refresh_interval_seconds,
)
from app.watchlists.schemas import WatchlistGroupRadarRead


router = APIRouter()


def _fetch_error(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=str(exc),
    )


def _group_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KRWatchlistGroupNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, (KRWatchlistInvalidTreeError, KRWatchlistGroupNotEmptyError)):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _item_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (KRWatchlistGroupNotFoundError, KRWatchlistItemNotFoundError, KRStockNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, KRWatchlistDuplicateItemError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _enqueue_kr_watchlist_resource_refresh(
    *,
    db: Session,
    group_id: int | None,
    include_children: bool,
    enabled_only: bool,
    include_daily: bool,
    include_investors: bool,
    include_fundamentals: bool,
    outputsize: str,
    provider: str,
    sleep_seconds: float,
    max_symbols: int | None,
) -> dict:
    target = f"group:{group_id}" if group_id is not None else "all"
    request = {
        "group_id": group_id,
        "include_children": include_children,
        "enabled_only": enabled_only,
        "include_daily": include_daily,
        "include_investors": include_investors,
        "include_fundamentals": include_fundamentals,
        "outputsize": outputsize,
        "provider": provider,
        "sleep_seconds": sleep_seconds,
        "max_symbols": max_symbols,
    }
    job, _created = job_service.enqueue_job(
        db=db,
        job_type=KR_WATCHLIST_RESOURCE_REFRESH_JOB_TYPE,
        target=target,
        request=request,
        progress_total=1,
        message="Queued KR watchlist resource refresh.",
        task=backfill_tasks.run_kr_watchlist_resource_refresh_job,
        task_args=(
            group_id,
            include_children,
            enabled_only,
            include_daily,
            include_investors,
            include_fundamentals,
            outputsize,
            provider,
            sleep_seconds,
            max_symbols,
        ),
    )
    return job_service.serialize_job(job)


@router.post("/stocks/sync-symbols", response_model=KRStockMasterSyncResultRead)
def sync_kr_stock_symbols(
    deactivate_missing: bool = False,
    db: Session = Depends(get_db),
):
    try:
        return sync_kr_symbol_master(db=db, deactivate_missing=deactivate_missing)
    except requests.RequestException as exc:
        raise _fetch_error(exc) from exc
    except KRMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.get("/source-health", response_model=KRSourceHealthRead)
def get_kr_source_health(symbol: str | None = None, db: Session = Depends(get_db)):
    return build_kr_source_health(db=db, symbol=symbol)


@router.post("/indices/sync", response_model=KRMarketIndexSyncResultRead)
def sync_kr_market_indices(db: Session = Depends(get_db)):
    return sync_kr_index_master(db=db)


@router.get("/indices", response_model=list[KRMarketIndexRead])
def list_kr_market_indices_api(
    is_active: bool | None = True,
    db: Session = Depends(get_db),
):
    return list_kr_market_indices(db=db, is_active=is_active)


@router.get("/indices/summary", response_model=KRIndexSummaryRead)
def get_kr_index_summary_api(db: Session = Depends(get_db)):
    return get_kr_index_summary(db=db)


@router.get("/indices/{index_id}/breadth", response_model=KRMarketBreadthRead)
def get_kr_market_breadth_api(
    index_id: str,
    trade_date: date | None = None,
    db: Session = Depends(get_db),
):
    try:
        return get_kr_market_breadth(db=db, index_id=index_id, trade_date=trade_date)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/market-breadth/refresh", response_model=KRMarketBreadthRefreshResultRead)
def refresh_kr_market_breadth_api(
    trade_date: date | None = None,
    market_id: str = Query(default="ALL", pattern="^(ALL|STK|KSQ)$"),
    db: Session = Depends(get_db),
):
    try:
        return refresh_kr_market_breadth_daily_prices(
            db=db,
            trade_date=trade_date,
            market_id=market_id,
        )
    except requests.RequestException as exc:
        raise _fetch_error(exc) from exc
    except KRMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.post("/indices/refresh", response_model=KRIndexRefreshBatchResultRead)
def refresh_kr_indices_api(
    index_ids: str | None = Query(default=None, description="Comma-separated KR index ids. Defaults to all configured indices."),
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
):
    try:
        requested_ids = [
            value.strip()
            for value in (index_ids or "").split(",")
            if value.strip()
        ] or None
        return refresh_kr_market_indices(
            db=db,
            index_ids=requested_ids,
            outputsize=outputsize,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/indices/{index_id}/refresh", response_model=KRIndexRefreshResultRead)
def refresh_kr_index_api(
    index_id: str,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
):
    try:
        return refresh_kr_index_daily_prices_service(
            db=db,
            index_id=index_id,
            outputsize=outputsize,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise _fetch_error(exc) from exc
    except KRMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.get("/indices/{index_id}", response_model=KRMarketIndexRead)
def get_kr_market_index_api(index_id: str, db: Session = Depends(get_db)):
    try:
        return get_kr_market_index_config(db=db, index_id=index_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except KRIndexNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/indices/{index_id}/ohlc", response_model=KRIndexOhlcChartRead)
def get_kr_index_ohlc_chart(
    index_id: str,
    timeframe: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    bars: int = Query(default=180, ge=1, le=5000),
    ensure_history: bool = False,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    to_date: date | None = None,
    db: Session = Depends(get_db),
):
    try:
        return list_kr_index_ohlc_chart_data(
            db=db,
            index_id=index_id,
            timeframe=timeframe,
            bars=bars,
            ensure_history=ensure_history,
            outputsize=outputsize,
            to_date=to_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise _fetch_error(exc) from exc
    except KRMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.get("/indices/{index_id}/intraday", response_model=KRIndexIntradayTrendRead)
def get_kr_index_intraday_chart(
    index_id: str,
    refresh: bool = False,
    max_pages: int = Query(default=80, ge=1, le=80),
    db: Session = Depends(get_db),
):
    try:
        return get_kr_index_intraday_trend(
            db=db,
            index_id=index_id,
            refresh=refresh,
            max_pages=max_pages,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise _fetch_error(exc) from exc
    except KRMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.get("/stocks/search", response_model=list[KRStockMasterRead])
def search_kr_stock_master(
    keyword: str,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    return search_kr_stocks(db=db, keyword=keyword, limit=limit)


@router.get("/stocks", response_model=list[KRStockMasterRead])
def list_kr_stock_master(
    exchange: str | None = None,
    asset_type: str | None = None,
    is_active: bool | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_kr_stocks(
        db=db,
        exchange=exchange,
        asset_type=asset_type,
        is_active=is_active,
        limit=limit,
        offset=offset,
    )


@router.get("/stocks/{symbol}", response_model=KRStockMasterRead)
def get_kr_stock_master(symbol: str, db: Session = Depends(get_db)):
    try:
        return get_kr_stock(db=db, symbol=symbol)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except KRStockNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/resources/{symbol}/summary", response_model=KRResourceSummaryRead)
def get_kr_resource_summary_api(symbol: str, db: Session = Depends(get_db)):
    try:
        return get_kr_resource_summary(db=db, symbol=symbol)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/resources/{symbol}/refresh", response_model=KRResourceRefreshResultRead)
def refresh_kr_market_resource_api(
    symbol: str,
    resource: str = Query(
        default="demand",
        pattern="^(demand|investors|disclosures|performance|financials)$",
    ),
    db: Session = Depends(get_db),
):
    try:
        return refresh_kr_market_resource(db=db, symbol=symbol, resource=resource)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise _fetch_error(exc) from exc
    except KRMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.post("/fundamentals/{symbol}/refresh", response_model=KRResourceRefreshResultRead)
def refresh_kr_company_fundamental(
    symbol: str,
    corp_code: str | None = None,
    fiscal_year: int | None = Query(default=None, ge=1990, le=2100),
    report_code: str = Query(default="11011", min_length=5, max_length=5),
    fs_div: str = Query(default="CFS", pattern="^(CFS|OFS)$"),
    db: Session = Depends(get_db),
):
    try:
        return refresh_kr_company_fundamental_service(
            db=db,
            symbol=symbol,
            corp_code=corp_code,
            fiscal_year=fiscal_year,
            report_code=report_code,
            fs_div=fs_div,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise _fetch_error(exc) from exc
    except KRMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.get("/fundamentals", response_model=list[KRCompanyFundamentalRead])
def list_kr_fundamentals(
    symbol: str | None = None,
    provider: str | None = None,
    fiscal_year: int | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_kr_company_fundamentals(
        db=db,
        symbol=symbol,
        provider=provider,
        fiscal_year=fiscal_year,
        limit=limit,
        offset=offset,
    )


@router.post("/daily/{symbol}/refresh", response_model=KRDailyPriceRefreshResultRead)
def refresh_kr_daily_prices(
    symbol: str,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    provider: str = Query(default="auto", pattern="^(auto|krx_data|yahoo_chart)$"),
    trade_date: date | None = None,
    db: Session = Depends(get_db),
):
    try:
        return refresh_kr_daily_prices_service(
            db=db,
            symbol=symbol,
            outputsize=outputsize,
            provider=provider,
            trade_date=trade_date,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise _fetch_error(exc) from exc
    except KRMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.get("/daily/{symbol}/history", response_model=list[KRDailyPriceRead])
def list_kr_daily_history(
    symbol: str,
    provider: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        return list_kr_daily_prices(
            db=db,
            symbol=symbol,
            provider=provider,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/investors/{symbol}/history", response_model=list[KRInvestorTradeDailyRead])
def list_kr_investor_history(
    symbol: str,
    provider: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        return list_kr_investor_trades(
            db=db,
            symbol=symbol,
            provider=provider,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/watchlists/groups",
    response_model=KRWatchlistGroupRead,
    status_code=status.HTTP_201_CREATED,
)
def create_kr_watchlist_group_api(payload: KRWatchlistGroupCreate, db: Session = Depends(get_db)):
    try:
        return create_kr_watchlist_group(db=db, payload=payload)
    except Exception as exc:
        raise _group_error(exc) from exc


@router.get("/watchlists/groups", response_model=list[KRWatchlistGroupRead])
def list_kr_watchlist_groups_api(is_active: bool | None = None, db: Session = Depends(get_db)):
    return list_kr_watchlist_groups(db=db, is_active=is_active)


@router.get("/watchlists/tree", response_model=list[KRWatchlistGroupTreeRead])
def get_kr_watchlist_tree_api(is_active: bool | None = True, db: Session = Depends(get_db)):
    return get_kr_watchlist_tree(db=db, is_active=is_active)


@router.patch("/watchlists/groups/{group_id}", response_model=KRWatchlistGroupRead)
def update_kr_watchlist_group_api(
    group_id: int,
    payload: KRWatchlistGroupUpdate,
    db: Session = Depends(get_db),
):
    try:
        return update_kr_watchlist_group(db=db, group_id=group_id, payload=payload)
    except Exception as exc:
        raise _group_error(exc) from exc


@router.delete("/watchlists/groups/{group_id}", response_model=KRWatchlistGroupDeleteResultRead)
def delete_kr_watchlist_group_api(
    group_id: int,
    recursive: bool = False,
    db: Session = Depends(get_db),
):
    try:
        return delete_kr_watchlist_group(db=db, group_id=group_id, recursive=recursive)
    except Exception as exc:
        raise _group_error(exc) from exc


@router.post(
    "/watchlists/items",
    response_model=KRWatchlistItemRead,
    status_code=status.HTTP_201_CREATED,
)
def create_kr_watchlist_item_api(payload: KRWatchlistItemCreate, db: Session = Depends(get_db)):
    try:
        return create_kr_watchlist_item(db=db, payload=payload)
    except Exception as exc:
        raise _item_error(exc) from exc


@router.get("/watchlists/items", response_model=list[KRWatchlistItemRead])
def list_kr_watchlist_items_api(
    group_id: int | None = None,
    symbol: str | None = None,
    enabled: bool | None = None,
    include_children: bool = False,
    limit: int = Query(default=100, ge=1, le=10000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    try:
        return list_kr_watchlist_items(
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


@router.get("/watchlists/ranking", response_model=KRWatchlistRankingRead)
def get_kr_watchlist_ranking_api(
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    rank_by: str = Query(default="none", pattern="^(none|change_pct|volume|close)$"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$"),
    db: Session = Depends(get_db),
):
    try:
        return get_kr_watchlist_ranking(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            rank_by=rank_by,
            sort_order=sort_order,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise _group_error(exc) from exc


@router.get("/watchlists/readiness", response_model=KRWatchlistReadinessRead)
def get_kr_watchlist_readiness_api(
    group_id: int | None = None,
    include_children: bool = True,
    enabled_only: bool = True,
    db: Session = Depends(get_db),
):
    try:
        return get_kr_watchlist_readiness(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise _group_error(exc) from exc


@router.get("/watchlists/groups/{group_id}/radar", response_model=WatchlistGroupRadarRead)
def get_kr_watchlist_radar_api(
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
        return get_kr_watchlist_technical_radar(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            mode=mode,
            max_results=max_results,
            calculation_limit=calculation_limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise _group_error(exc) from exc


@router.post(
    "/watchlists/daily/refresh",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_all_kr_watchlist_daily_prices_api(
    include_children: bool = True,
    enabled_only: bool = True,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    provider: str = Query(default="auto", pattern="^(auto|krx_data|yahoo_chart)$"),
    sleep_seconds: float | None = Query(default=None, ge=0, le=60),
    db: Session = Depends(get_db),
):
    resolved_sleep_seconds = resolve_observed_stock_refresh_interval_seconds(
        db=db,
        market="kr",
        explicit_sleep_seconds=sleep_seconds,
    )
    return _enqueue_kr_watchlist_resource_refresh(
        db=db,
        group_id=None,
        include_children=include_children,
        enabled_only=enabled_only,
        include_daily=True,
        include_investors=False,
        include_fundamentals=False,
        outputsize=outputsize,
        provider=provider,
        sleep_seconds=resolved_sleep_seconds,
        max_symbols=None,
    )


@router.post(
    "/watchlists/groups/{group_id}/refresh-daily",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_kr_watchlist_group_daily_prices_api(
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    provider: str = Query(default="auto", pattern="^(auto|krx_data|yahoo_chart)$"),
    sleep_seconds: float | None = Query(default=None, ge=0, le=60),
    db: Session = Depends(get_db),
):
    try:
        get_kr_watchlist_group(db=db, group_id=group_id)
        resolved_sleep_seconds = resolve_observed_stock_refresh_interval_seconds(
            db=db,
            market="kr",
            explicit_sleep_seconds=sleep_seconds,
        )
        return _enqueue_kr_watchlist_resource_refresh(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            include_daily=True,
            include_investors=False,
            include_fundamentals=False,
            outputsize=outputsize,
            provider=provider,
            sleep_seconds=resolved_sleep_seconds,
            max_symbols=None,
        )
    except Exception as exc:
        raise _group_error(exc) from exc


@router.post(
    "/watchlists/resources/refresh",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_all_kr_watchlist_resources_api(
    include_children: bool = True,
    enabled_only: bool = True,
    include_daily: bool = True,
    include_investors: bool = True,
    include_fundamentals: bool = False,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    provider: str = Query(default="auto", pattern="^(auto|krx_data|yahoo_chart)$"),
    sleep_seconds: float | None = Query(default=None, ge=0, le=60),
    max_symbols: int | None = Query(default=None, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    resolved_sleep_seconds = resolve_subresource_refresh_interval_seconds(
        db=db,
        market="kr",
        explicit_sleep_seconds=sleep_seconds,
    )
    return _enqueue_kr_watchlist_resource_refresh(
        db=db,
        group_id=None,
        include_children=include_children,
        enabled_only=enabled_only,
        include_daily=include_daily,
        include_investors=include_investors,
        include_fundamentals=include_fundamentals,
        outputsize=outputsize,
        provider=provider,
        sleep_seconds=resolved_sleep_seconds,
        max_symbols=max_symbols,
    )


@router.post(
    "/watchlists/groups/{group_id}/refresh-resources",
    response_model=JobRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_kr_watchlist_group_resources_api(
    group_id: int,
    include_children: bool = True,
    enabled_only: bool = True,
    include_daily: bool = True,
    include_investors: bool = True,
    include_fundamentals: bool = False,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    provider: str = Query(default="auto", pattern="^(auto|krx_data|yahoo_chart)$"),
    sleep_seconds: float | None = Query(default=None, ge=0, le=60),
    max_symbols: int | None = Query(default=None, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    try:
        get_kr_watchlist_group(db=db, group_id=group_id)
        resolved_sleep_seconds = resolve_subresource_refresh_interval_seconds(
            db=db,
            market="kr",
            explicit_sleep_seconds=sleep_seconds,
        )
        return _enqueue_kr_watchlist_resource_refresh(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            include_daily=include_daily,
            include_investors=include_investors,
            include_fundamentals=include_fundamentals,
            outputsize=outputsize,
            provider=provider,
            sleep_seconds=resolved_sleep_seconds,
            max_symbols=max_symbols,
        )
    except Exception as exc:
        raise _group_error(exc) from exc


@router.patch("/watchlists/items/{item_id}", response_model=KRWatchlistItemRead)
def update_kr_watchlist_item_api(
    item_id: int,
    payload: KRWatchlistItemUpdate,
    db: Session = Depends(get_db),
):
    try:
        return update_kr_watchlist_item(db=db, item_id=item_id, payload=payload)
    except Exception as exc:
        raise _item_error(exc) from exc


@router.delete("/watchlists/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_kr_watchlist_item_api(item_id: int, db: Session = Depends(get_db)):
    try:
        delete_kr_watchlist_item(db=db, item_id=item_id)
    except Exception as exc:
        raise _item_error(exc) from exc
    return None


@router.get("/ohlc/{symbol}", response_model=KROhlcChartRead)
def get_kr_ohlc_chart_data(
    symbol: str,
    timeframe: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    bars: int = Query(default=90, ge=1, le=5000),
    ensure_history: bool = False,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    provider: str = Query(default="auto", pattern="^(auto|krx_data|yahoo_chart)$"),
    to_date: date | None = None,
    db: Session = Depends(get_db),
):
    try:
        return list_kr_ohlc_chart_data(
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except requests.RequestException as exc:
        raise _fetch_error(exc) from exc
    except KRMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc
