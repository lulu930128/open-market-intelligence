from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.resource_market.schemas import (
    ResourceInstrumentRead,
    ResourceOhlcvBarRead,
    ResourceProviderContractRead,
    ResourceQuoteRead,
    ResourceRefreshResultRead,
    ResourceSourceHealthRead,
)
from app.resource_market.service import (
    get_resource_provider_contract,
    list_latest_resource_quotes,
    list_resource_ohlcv_bars,
    list_supported_resource_instruments,
    resource_ohlcv_bar_to_public_dict,
    resource_quote_to_public_dict,
    refresh_resource_market_snapshot,
    refresh_resource_ohlcv,
    refresh_resource_quotes,
)
from app.resource_market.source_health import build_resource_source_health


router = APIRouter()


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/provider-contract", response_model=ResourceProviderContractRead)
def get_provider_contract():
    return get_resource_provider_contract()


@router.get("/source-health", response_model=ResourceSourceHealthRead)
def get_resource_source_health(
    provider: str | None = None,
    symbols: str | None = None,
    group: str | None = None,
    intervals: str | None = None,
    include_events: bool = Query(default=True),
    max_entries: int | None = Query(default=None, ge=1, le=500),
    db: Session = Depends(get_db),
):
    try:
        return build_resource_source_health(
            db,
            provider=provider,
            symbols=symbols,
            group=group,
            intervals=intervals,
            include_events=include_events,
            max_entries=max_entries,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/instruments", response_model=list[ResourceInstrumentRead])
def get_resource_instruments(
    root_folder: str | None = None,
    group: str | None = None,
    symbol: str | None = None,
):
    return list_supported_resource_instruments(
        root_folder=root_folder,
        group=group,
        symbol=symbol,
    )


@router.get("/quotes/latest", response_model=list[ResourceQuoteRead])
def get_latest_resource_quotes(
    provider: str | None = None,
    symbols: str | None = None,
    group: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    rows = list_latest_resource_quotes(
        db,
        provider=provider,
        symbols=symbols,
        group=group,
        limit=limit,
    )
    return [resource_quote_to_public_dict(row) for row in rows]


@router.post("/quotes/refresh", response_model=ResourceRefreshResultRead)
def refresh_resource_quotes_api(
    symbols: str | None = None,
    db: Session = Depends(get_db),
):
    try:
        return refresh_resource_quotes(db, symbols=symbols)
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.get("/ohlcv/latest", response_model=list[ResourceOhlcvBarRead])
def get_latest_resource_ohlcv(
    provider: str | None = None,
    symbols: str | None = None,
    group: str | None = None,
    interval: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    rows = list_resource_ohlcv_bars(
        db,
        provider=provider,
        symbols=symbols,
        group=group,
        interval=interval,
        limit=limit,
    )
    return [resource_ohlcv_bar_to_public_dict(row) for row in rows]


@router.post("/ohlcv/refresh", response_model=ResourceRefreshResultRead)
def refresh_resource_ohlcv_api(
    symbols: str | None = None,
    interval: str = Query(default="15m"),
    limit: int = Query(default=120, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    try:
        return refresh_resource_ohlcv(
            db,
            symbols=symbols,
            interval=interval,
            limit=limit,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc


@router.post("/refresh", response_model=ResourceRefreshResultRead)
def refresh_resource_market_snapshot_api(
    symbols: str | None = None,
    intervals: str | None = Query(default="1m,15m"),
    limit: int = Query(default=120, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    try:
        return refresh_resource_market_snapshot(
            db,
            symbols=symbols,
            intervals=intervals,
            limit=limit,
        )
    except ValueError as exc:
        raise _bad_request(exc) from exc
