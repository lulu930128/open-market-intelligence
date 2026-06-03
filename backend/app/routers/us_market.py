from __future__ import annotations

from datetime import date

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.jobs import backfill_tasks, service as job_service
from app.jobs.schemas import JobRunRead
from app.us_market.schemas import (
    MacroSeriesObservationRead,
    USDailyPriceRead,
    USDailyPriceRefreshResultRead,
    USCompanyProfileRead,
    USCorporateActionRead,
    USIntradayTrendRead,
    USOhlcChartRead,
    USResourceRefreshResultRead,
    USSecCompanyFactRead,
    USSecFactRefreshResultRead,
    USSecFundamentalSummaryRead,
    USShortVolumeDailyRead,
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
from app.us_market.service import (
    USMarketConfigurationError,
    USMarketDataFetchError,
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
    get_us_company_profile,
    get_us_intraday_trend,
    get_us_sec_fundamental_summary,
    get_us_stock,
    get_us_watchlist_group,
    get_us_watchlist_ranking,
    get_us_watchlist_tree,
    list_macro_series_observations,
    list_us_company_profiles,
    list_us_corporate_actions,
    list_us_ohlc_chart_data,
    list_us_watchlist_groups,
    list_us_watchlist_items,
    list_us_daily_prices,
    list_us_sec_company_facts,
    list_us_short_volumes,
    list_us_stocks,
    refresh_fred_macro_series,
    refresh_us_company_profile_from_alphavantage,
    refresh_us_corporate_actions_from_alphavantage,
    refresh_us_daily_prices as refresh_us_daily_prices_service,
    refresh_us_sec_companyfacts,
    refresh_us_short_volume_from_finra,
    search_us_stocks,
    sync_us_sec_company_data,
    sync_us_symbol_master,
    update_us_watchlist_group,
    update_us_watchlist_item,
)


router = APIRouter()


def _fetch_error(exc: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=str(exc),
    )


def _group_error(exc: Exception) -> HTTPException:
    if isinstance(exc, USWatchlistGroupNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    if isinstance(exc, (USWatchlistInvalidTreeError, USWatchlistGroupNotEmptyError)):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _item_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (USWatchlistGroupNotFoundError, USWatchlistItemNotFoundError, USStockNotFoundError)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    if isinstance(exc, USWatchlistDuplicateItemError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


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
    target = f"group:{group_id}" if group_id is not None else "all"
    request = {
        "group_id": group_id,
        "include_children": include_children,
        "enabled_only": enabled_only,
        "outputsize": outputsize,
        "adjusted": adjusted,
        "sleep_seconds": sleep_seconds,
    }
    job, _created = job_service.enqueue_job(
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
    return job_service.serialize_job(job)


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
    sleep_seconds: float = Query(default=12.0, ge=0, le=120),
    db: Session = Depends(get_db),
):
    return _enqueue_us_watchlist_daily_refresh(
        db=db,
        group_id=None,
        include_children=include_children,
        enabled_only=enabled_only,
        outputsize=outputsize,
        adjusted=adjusted,
        sleep_seconds=sleep_seconds,
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
    sleep_seconds: float = Query(default=12.0, ge=0, le=120),
    db: Session = Depends(get_db),
):
    try:
        get_us_watchlist_group(db=db, group_id=group_id)
        return _enqueue_us_watchlist_daily_refresh(
            db=db,
            group_id=group_id,
            include_children=include_children,
            enabled_only=enabled_only,
            outputsize=outputsize,
            adjusted=adjusted,
            sleep_seconds=sleep_seconds,
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
    except requests.RequestException as exc:
        raise _fetch_error(exc) from exc
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
    except requests.RequestException as exc:
        raise _fetch_error(exc) from exc
    except USMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


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


@router.post("/daily/{symbol}/refresh", response_model=USDailyPriceRefreshResultRead)
def refresh_us_daily_prices(
    symbol: str,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    adjusted: bool = False,
    provider: str = Query(default="auto", pattern="^(auto|alphavantage|yahoo_chart)$"),
    db: Session = Depends(get_db),
):
    try:
        return refresh_us_daily_prices_service(
            db=db,
            symbol=symbol,
            outputsize=outputsize,
            adjusted=adjusted,
            provider=provider,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except USMarketConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except requests.RequestException as exc:
        raise _fetch_error(exc) from exc
    except USMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.get("/daily/{symbol}/history", response_model=list[USDailyPriceRead])
def list_us_daily_history(
    symbol: str,
    provider: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_us_daily_prices(
        db=db,
        symbol=symbol,
        provider=provider,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )


@router.get("/ohlc/{symbol}", response_model=USOhlcChartRead)
def get_us_ohlc_chart_data(
    symbol: str,
    timeframe: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    bars: int = Query(default=90, ge=1, le=5000),
    ensure_history: bool = False,
    outputsize: str = Query(default="compact", pattern="^(compact|full)$"),
    adjusted: bool = False,
    to_date: date | None = None,
    db: Session = Depends(get_db),
):
    try:
        return list_us_ohlc_chart_data(
            db=db,
            symbol=symbol,
            timeframe=timeframe,
            bars=bars,
            ensure_history=ensure_history,
            outputsize=outputsize,
            adjusted=adjusted,
            to_date=to_date,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except USMarketConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except requests.RequestException as exc:
        raise _fetch_error(exc) from exc
    except USMarketDataFetchError as exc:
        raise _fetch_error(exc) from exc


@router.get("/intraday/{symbol}", response_model=USIntradayTrendRead)
def get_us_intraday_trend_api(symbol: str):
    return get_us_intraday_trend(symbol=symbol)


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
    except requests.RequestException as exc:
        raise _fetch_error(exc) from exc
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


@router.post("/profiles/{symbol}/refresh", response_model=USResourceRefreshResultRead)
def refresh_us_company_profile(symbol: str, db: Session = Depends(get_db)):
    try:
        return refresh_us_company_profile_from_alphavantage(db=db, symbol=symbol)
    except USMarketConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except requests.RequestException as exc:
        raise _fetch_error(exc) from exc
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
    except requests.RequestException as exc:
        raise _fetch_error(exc) from exc
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
    except requests.RequestException as exc:
        raise _fetch_error(exc) from exc
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
    except requests.RequestException as exc:
        raise _fetch_error(exc) from exc
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
