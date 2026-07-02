from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.crypto_market.schemas import (
    CryptoCvdHistoryRead,
    CryptoCvdRefreshResultRead,
    CryptoDerivativesMetricRead,
    CryptoDerivativesMetricHistoryRead,
    CryptoDerivativesRefreshResultRead,
    CryptoLiquidationEventRead,
    CryptoLiquidationHeatmapCellRead,
    CryptoLiquidationHeatmapRefreshResultRead,
    CryptoLiquidityHistoryRead,
    CryptoLongShortRatioHistoryRead,
    CryptoLongShortRatioRefreshResultRead,
    CryptoMarketCapRead,
    CryptoMarketCapRefreshResultRead,
    CryptoOrderBookRead,
    CryptoOrderBookRefreshResultRead,
    CryptoOhlcvBarRead,
    CryptoOhlcvBundleRefreshResultRead,
    CryptoOhlcvCoverageRead,
    CryptoOhlcvRefreshResultRead,
    CryptoProviderContractRead,
    CryptoRealtimeLatestRead,
    CryptoRealtimeStatusRead,
    CryptoRealtimeStreamRead,
    CryptoSourceHealthRead,
    CryptoSpreadRead,
    CryptoSpreadHistoryRead,
    CryptoSpreadRefreshResultRead,
    CryptoTickerHistoryRead,
    CryptoTickerRead,
    CryptoTickerRefreshResultRead,
    CryptoWatchlistGroupCreate,
    CryptoWatchlistGroupDeleteResultRead,
    CryptoWatchlistGroupRead,
    CryptoWatchlistGroupTreeRead,
    CryptoWatchlistGroupUpdate,
    CryptoWatchlistItemCreate,
    CryptoWatchlistItemRead,
    CryptoWatchlistItemUpdate,
)
from app.crypto_market.service import (
    CryptoMarketError,
    CryptoMarketUnsupportedError,
    get_crypto_provider_contract,
    list_crypto_cvd_history,
    list_crypto_derivatives_history,
    list_crypto_liquidation_events,
    list_crypto_liquidation_heatmap_cells,
    list_crypto_liquidity_history,
    list_crypto_long_short_ratio_history,
    list_crypto_spread_history,
    list_crypto_ticker_history,
    list_latest_crypto_derivatives,
    list_latest_crypto_market_caps,
    list_latest_crypto_order_books,
    list_latest_crypto_ohlcv_bars,
    list_latest_crypto_spreads,
    list_latest_crypto_tickers,
    list_crypto_ohlcv_coverage,
    refresh_crypto_cvd,
    refresh_crypto_derivatives,
    refresh_crypto_liquidation_heatmap,
    refresh_crypto_long_short_ratios,
    refresh_crypto_market_caps,
    refresh_crypto_order_books,
    refresh_crypto_ohlcv,
    refresh_crypto_ohlcv_bundle,
    refresh_crypto_spreads,
    refresh_crypto_tickers,
)
from app.crypto_market.auto_refresh import (
    crypto_auto_refresh_status,
    reload_crypto_auto_refresh,
)
from app.crypto_market.realtime import build_crypto_realtime_stream_specs, crypto_realtime_store
from app.crypto_market.source_health import build_crypto_source_health
from app.crypto_market import watchlist as crypto_watchlist
from app.crypto_market.ws_runtime import (
    crypto_realtime_collector_status,
    reload_crypto_realtime_collectors,
)
from app.db.session import get_db


router = APIRouter()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _sse_event(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=_json_default)
    return f"event: {event}\ndata: {payload}\n\n"


async def _iter_crypto_realtime_latest_sse(
    request: Request,
    *,
    provider: str | None,
    resource: str | None,
    symbol: str | None,
    instrument_type: str | None,
    interval_ms: int,
    stale_seconds: int | None,
):
    interval_seconds = interval_ms / 1000
    while not await request.is_disconnected():
        rows = crypto_realtime_store.latest(
            provider=provider,
            resource=resource,
            symbol=symbol,
            instrument_type=instrument_type,
            stale_seconds=stale_seconds,
        )
        yield _sse_event(
            "snapshot",
            {
                "kind": "crypto_realtime_latest",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "rows": rows,
            },
        )
        await asyncio.sleep(interval_seconds)


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _handle_crypto_watchlist_error(exc: Exception) -> HTTPException:
    if isinstance(
        exc,
        (
            crypto_watchlist.CryptoWatchlistGroupNotFoundError,
            crypto_watchlist.CryptoWatchlistItemNotFoundError,
        ),
    ):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, crypto_watchlist.CryptoWatchlistDuplicateItemError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/provider-contract", response_model=CryptoProviderContractRead)
def get_provider_contract():
    return get_crypto_provider_contract()


@router.get("/source-health", response_model=CryptoSourceHealthRead)
def get_crypto_source_health(
    provider: str | None = None,
    symbol: str | None = None,
    base: str | None = None,
    required_only: bool = Query(default=False),
    include_events: bool = Query(default=False),
    max_entries: int | None = Query(default=None, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return build_crypto_source_health(
        db=db,
        provider=provider,
        symbol=symbol,
        base=base,
        required_only=required_only,
        include_events=include_events,
        max_entries=max_entries,
    )


@router.post("/source-health/snapshot", response_model=CryptoSourceHealthRead)
def sync_crypto_source_health_snapshot(
    provider: str | None = None,
    symbol: str | None = None,
    base: str | None = None,
    required_only: bool = Query(default=False),
    include_events: bool = Query(default=True),
    max_entries: int | None = Query(default=None, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return build_crypto_source_health(
        db=db,
        provider=provider,
        symbol=symbol,
        base=base,
        required_only=required_only,
        include_events=include_events,
        max_entries=max_entries,
        sync_snapshots=True,
    )


@router.get("/realtime/streams", response_model=list[CryptoRealtimeStreamRead])
def get_crypto_realtime_streams():
    return [spec.to_dict() for spec in build_crypto_realtime_stream_specs()]


@router.get("/realtime/status", response_model=CryptoRealtimeStatusRead)
def get_crypto_realtime_status():
    return crypto_realtime_collector_status()


@router.get("/auto-refresh/status")
def get_crypto_auto_refresh_status():
    return crypto_auto_refresh_status()


@router.get("/watchlists/tree", response_model=list[CryptoWatchlistGroupTreeRead])
def get_crypto_watchlist_tree(
    is_active: bool | None = True,
    db: Session = Depends(get_db),
):
    return crypto_watchlist.get_crypto_watchlist_tree(db=db, is_active=is_active)


@router.get("/watchlists/items", response_model=list[CryptoWatchlistItemRead])
def list_crypto_watchlist_items(
    group_id: int | None = None,
    enabled: bool | None = None,
    db: Session = Depends(get_db),
):
    try:
        return crypto_watchlist.list_crypto_watchlist_items(
            db=db,
            group_id=group_id,
            enabled=enabled,
        )
    except Exception as exc:
        raise _handle_crypto_watchlist_error(exc) from exc


@router.post(
    "/watchlists/groups",
    response_model=CryptoWatchlistGroupRead,
    status_code=status.HTTP_201_CREATED,
)
def create_crypto_watchlist_group(
    payload: CryptoWatchlistGroupCreate,
    db: Session = Depends(get_db),
):
    try:
        return crypto_watchlist.create_crypto_watchlist_group(db=db, payload=payload)
    except Exception as exc:
        raise _handle_crypto_watchlist_error(exc) from exc


@router.patch("/watchlists/groups/{group_id}", response_model=CryptoWatchlistGroupRead)
def update_crypto_watchlist_group(
    group_id: int,
    payload: CryptoWatchlistGroupUpdate,
    db: Session = Depends(get_db),
):
    try:
        return crypto_watchlist.update_crypto_watchlist_group(
            db=db,
            group_id=group_id,
            payload=payload,
        )
    except Exception as exc:
        raise _handle_crypto_watchlist_error(exc) from exc


@router.delete(
    "/watchlists/groups/{group_id}",
    response_model=CryptoWatchlistGroupDeleteResultRead,
)
def delete_crypto_watchlist_group(
    group_id: int,
    recursive: bool = False,
    db: Session = Depends(get_db),
):
    try:
        return crypto_watchlist.delete_crypto_watchlist_group(
            db=db,
            group_id=group_id,
            recursive=recursive,
        )
    except Exception as exc:
        raise _handle_crypto_watchlist_error(exc) from exc


@router.post(
    "/watchlists/items",
    response_model=CryptoWatchlistItemRead,
    status_code=status.HTTP_201_CREATED,
)
def create_crypto_watchlist_item(
    payload: CryptoWatchlistItemCreate,
    db: Session = Depends(get_db),
):
    try:
        return crypto_watchlist.create_crypto_watchlist_item(db=db, payload=payload)
    except Exception as exc:
        raise _handle_crypto_watchlist_error(exc) from exc


@router.patch("/watchlists/items/{item_id}", response_model=CryptoWatchlistItemRead)
def update_crypto_watchlist_item(
    item_id: int,
    payload: CryptoWatchlistItemUpdate,
    db: Session = Depends(get_db),
):
    try:
        return crypto_watchlist.update_crypto_watchlist_item(
            db=db,
            item_id=item_id,
            payload=payload,
        )
    except Exception as exc:
        raise _handle_crypto_watchlist_error(exc) from exc


@router.delete("/watchlists/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_crypto_watchlist_item(
    item_id: int,
    db: Session = Depends(get_db),
):
    try:
        crypto_watchlist.delete_crypto_watchlist_item(db=db, item_id=item_id)
    except Exception as exc:
        raise _handle_crypto_watchlist_error(exc) from exc
    return None


@router.post("/auto-refresh/reload")
async def reload_crypto_auto_refresh_status():
    return await reload_crypto_auto_refresh(reason="manual_api")


@router.post("/realtime/reload", response_model=CryptoRealtimeStatusRead)
async def reload_crypto_realtime_status():
    return await reload_crypto_realtime_collectors(reason="manual_api")


@router.get("/realtime/latest", response_model=list[CryptoRealtimeLatestRead])
def get_crypto_realtime_latest(
    provider: str | None = None,
    resource: str | None = None,
    symbol: str | None = None,
    instrument_type: str | None = None,
):
    return crypto_realtime_store.latest(
        provider=provider,
        resource=resource,
        symbol=symbol,
        instrument_type=instrument_type,
    )


@router.get("/realtime/stream")
async def stream_crypto_realtime_latest(
    request: Request,
    provider: str | None = None,
    resource: str | None = None,
    symbol: str | None = None,
    instrument_type: str | None = None,
    interval_ms: int = Query(default=1000, ge=250, le=5000),
    stale_seconds: int | None = Query(default=None, ge=1, le=3600),
):
    return StreamingResponse(
        _iter_crypto_realtime_latest_sse(
            request,
            provider=provider,
            resource=resource,
            symbol=symbol,
            instrument_type=instrument_type,
            interval_ms=interval_ms,
            stale_seconds=stale_seconds,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/quotes/latest", response_model=list[CryptoTickerRead])
def get_latest_crypto_quotes(
    provider: str | None = None,
    symbols: str | None = None,
    instrument_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_latest_crypto_tickers(
        db,
        provider=provider,
        symbols=symbols,
        instrument_type=instrument_type,
        limit=limit,
    )


@router.get("/quotes/history", response_model=list[CryptoTickerHistoryRead])
def get_crypto_quote_history(
    provider: str | None = None,
    symbols: str | None = None,
    instrument_type: str | None = None,
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
    ascending: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    return list_crypto_ticker_history(
        db,
        provider=provider,
        symbols=symbols,
        instrument_type=instrument_type,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        ascending=ascending,
    )


@router.post("/quotes/refresh", response_model=CryptoTickerRefreshResultRead)
def refresh_crypto_quotes(
    providers: str | None = Query(default=None),
    symbols: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return refresh_crypto_tickers(db, providers=providers, symbols=symbols)
    except CryptoMarketUnsupportedError as exc:
        raise _bad_request(exc) from exc


@router.get("/order-books/latest", response_model=list[CryptoOrderBookRead])
def get_latest_crypto_order_books(
    provider: str | None = None,
    symbols: str | None = None,
    instrument_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_latest_crypto_order_books(
        db,
        provider=provider,
        symbols=symbols,
        instrument_type=instrument_type,
        limit=limit,
    )


@router.get("/order-books/history", response_model=list[CryptoLiquidityHistoryRead])
def get_crypto_order_book_history(
    provider: str | None = None,
    symbols: str | None = None,
    instrument_type: str | None = None,
    depth_limit: int | None = Query(default=None, ge=1, le=100),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
    ascending: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    return list_crypto_liquidity_history(
        db,
        provider=provider,
        symbols=symbols,
        instrument_type=instrument_type,
        depth_limit=depth_limit,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        ascending=ascending,
    )


@router.post("/order-books/refresh", response_model=CryptoOrderBookRefreshResultRead)
def refresh_crypto_order_book_cache(
    providers: str | None = Query(default=None),
    symbols: str | None = Query(default=None),
    depth_limit: int = Query(default=5, ge=1, le=100),
    db: Session = Depends(get_db),
):
    try:
        return refresh_crypto_order_books(
            db,
            providers=providers,
            symbols=symbols,
            depth_limit=depth_limit,
        )
    except CryptoMarketUnsupportedError as exc:
        raise _bad_request(exc) from exc


@router.get("/ohlcv/latest", response_model=list[CryptoOhlcvBarRead])
def get_latest_crypto_ohlcv(
    provider: str | None = None,
    symbols: str | None = None,
    instrument_type: str | None = None,
    interval: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    return list_latest_crypto_ohlcv_bars(
        db,
        provider=provider,
        symbols=symbols,
        instrument_type=instrument_type,
        interval=interval,
        limit=limit,
    )


@router.get("/ohlcv/coverage", response_model=list[CryptoOhlcvCoverageRead])
def get_crypto_ohlcv_coverage(
    provider: str | None = None,
    symbols: str | None = None,
    instrument_type: str | None = None,
    interval: str | None = None,
    db: Session = Depends(get_db),
):
    return list_crypto_ohlcv_coverage(
        db,
        provider=provider,
        symbols=symbols,
        instrument_type=instrument_type,
        interval=interval,
    )


@router.post("/ohlcv/refresh", response_model=CryptoOhlcvRefreshResultRead)
def refresh_crypto_ohlcv_cache(
    providers: str | None = Query(default=None),
    symbols: str | None = Query(default=None),
    interval: str = Query(default="1m"),
    limit: int = Query(default=100, ge=1, le=1000),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return refresh_crypto_ohlcv(
            db,
            providers=providers,
            symbols=symbols,
            interval=interval,
            limit=limit,
            start_time=start_time,
            end_time=end_time,
        )
    except (CryptoMarketError, ValueError) as exc:
        raise _bad_request(exc) from exc


@router.post("/ohlcv/refresh-bundle", response_model=CryptoOhlcvBundleRefreshResultRead)
def refresh_crypto_ohlcv_bundle_cache(
    providers: str | None = Query(default=None),
    symbols: str | None = Query(default=None),
    intervals: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return refresh_crypto_ohlcv_bundle(
            db,
            providers=providers,
            symbols=symbols,
            intervals=intervals,
        )
    except (CryptoMarketError, ValueError) as exc:
        raise _bad_request(exc) from exc


@router.get("/derivatives/latest", response_model=list[CryptoDerivativesMetricRead])
def get_latest_crypto_derivatives(
    provider: str | None = None,
    symbols: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_latest_crypto_derivatives(
        db,
        provider=provider,
        symbols=symbols,
        limit=limit,
    )


@router.get("/derivatives/history", response_model=list[CryptoDerivativesMetricHistoryRead])
def get_crypto_derivatives_history(
    provider: str | None = None,
    symbols: str | None = None,
    instrument_type: str | None = None,
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
    ascending: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    return list_crypto_derivatives_history(
        db,
        provider=provider,
        symbols=symbols,
        instrument_type=instrument_type,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        ascending=ascending,
    )


@router.post("/derivatives/refresh", response_model=CryptoDerivativesRefreshResultRead)
def refresh_crypto_derivatives_cache(
    providers: str | None = Query(default=None),
    symbols: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return refresh_crypto_derivatives(db, providers=providers, symbols=symbols)
    except CryptoMarketUnsupportedError as exc:
        raise _bad_request(exc) from exc


@router.get("/liquidations/events", response_model=list[CryptoLiquidationEventRead])
def get_crypto_liquidation_events(
    provider: str | None = None,
    symbols: str | None = None,
    instrument_type: str | None = None,
    liquidation_side: str | None = None,
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
    ascending: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    return list_crypto_liquidation_events(
        db,
        provider=provider,
        symbols=symbols,
        instrument_type=instrument_type,
        liquidation_side=liquidation_side,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        ascending=ascending,
    )


@router.get("/liquidations/heatmap", response_model=list[CryptoLiquidationHeatmapCellRead])
def get_crypto_liquidation_heatmap(
    provider: str | None = None,
    symbols: str | None = None,
    instrument_type: str | None = None,
    source_kind: str | None = None,
    method: str | None = None,
    liquidation_side: str | None = None,
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    limit: int = Query(default=5000, ge=1, le=5000),
    ascending: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    return list_crypto_liquidation_heatmap_cells(
        db,
        provider=provider,
        symbols=symbols,
        instrument_type=instrument_type,
        source_kind=source_kind,
        method=method,
        liquidation_side=liquidation_side,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        ascending=ascending,
    )


@router.post("/liquidations/refresh", response_model=CryptoLiquidationHeatmapRefreshResultRead)
def refresh_crypto_liquidation_heatmap_cache(
    providers: str | None = Query(default=None),
    symbols: str | None = Query(default=None),
    range_: str | None = Query(default=None, alias="range"),
    allow_local_fallback: bool | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return refresh_crypto_liquidation_heatmap(
            db,
            providers=providers,
            symbols=symbols,
            range_value=range_,
            allow_local_fallback=allow_local_fallback,
        )
    except CryptoMarketUnsupportedError as exc:
        raise _bad_request(exc) from exc


@router.get("/cvd/history", response_model=list[CryptoCvdHistoryRead])
def get_crypto_cvd_history(
    provider: str | None = None,
    symbols: str | None = None,
    instrument_type: str | None = None,
    bucket_seconds: int | None = Query(default=None, ge=1, le=86400),
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
    ascending: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    return list_crypto_cvd_history(
        db,
        provider=provider,
        symbols=symbols,
        instrument_type=instrument_type,
        bucket_seconds=bucket_seconds,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        ascending=ascending,
    )


@router.post("/cvd/refresh", response_model=CryptoCvdRefreshResultRead)
def refresh_crypto_cvd_cache(
    providers: str | None = Query(default=None),
    symbols: str | None = Query(default=None),
    instrument_type: str = Query(default="spot"),
    db: Session = Depends(get_db),
):
    try:
        return refresh_crypto_cvd(
            db,
            providers=providers,
            symbols=symbols,
            instrument_type=instrument_type,
        )
    except CryptoMarketUnsupportedError as exc:
        raise _bad_request(exc) from exc


@router.get("/long-short-ratios/history", response_model=list[CryptoLongShortRatioHistoryRead])
def get_crypto_long_short_ratio_history(
    provider: str | None = None,
    symbols: str | None = None,
    instrument_type: str | None = None,
    ratio_scope: str | None = None,
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
    ascending: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    return list_crypto_long_short_ratio_history(
        db,
        provider=provider,
        symbols=symbols,
        instrument_type=instrument_type,
        ratio_scope=ratio_scope,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        ascending=ascending,
    )


@router.post("/long-short-ratios/refresh", response_model=CryptoLongShortRatioRefreshResultRead)
def refresh_crypto_long_short_ratios_cache(
    providers: str | None = Query(default=None),
    symbols: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return refresh_crypto_long_short_ratios(db, providers=providers, symbols=symbols)
    except CryptoMarketUnsupportedError as exc:
        raise _bad_request(exc) from exc


@router.get("/market-caps/latest", response_model=list[CryptoMarketCapRead])
def get_latest_crypto_market_caps(
    vs_currency: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_latest_crypto_market_caps(
        db,
        vs_currency=vs_currency,
        limit=limit,
    )


@router.post("/market-caps/refresh", response_model=CryptoMarketCapRefreshResultRead)
def refresh_crypto_market_cap_cache(
    assets: str | None = Query(default=None),
    ids: str | None = Query(default=None),
    vs_currency: str = Query(default="usd"),
    db: Session = Depends(get_db),
):
    return refresh_crypto_market_caps(
        db,
        assets=assets,
        ids=ids,
        vs_currency=vs_currency,
    )


@router.get("/spreads", response_model=list[CryptoSpreadRead])
def get_latest_crypto_spreads(
    base: str | None = None,
    global_provider: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return list_latest_crypto_spreads(
        db,
        base=base,
        global_provider=global_provider,
        limit=limit,
    )


@router.get("/spreads/history", response_model=list[CryptoSpreadHistoryRead])
def get_crypto_spread_history(
    base: str | None = None,
    global_provider: str | None = None,
    start_time: datetime | None = Query(default=None),
    end_time: datetime | None = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
    ascending: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    return list_crypto_spread_history(
        db,
        base=base,
        global_provider=global_provider,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        ascending=ascending,
    )


@router.post("/spreads/refresh", response_model=CryptoSpreadRefreshResultRead)
def refresh_crypto_spread_cache(
    bases: str | None = Query(default=None),
    global_providers: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    try:
        return refresh_crypto_spreads(
            db,
            bases=bases,
            global_providers=global_providers,
        )
    except CryptoMarketError as exc:
        raise _bad_request(exc) from exc
