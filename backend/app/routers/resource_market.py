from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.resource_market.schemas import (
    ResourceInstrumentRead,
    ResourceOhlcvBarRead,
    ResourceProviderContractRead,
    ResourceQuoteRead,
)
from app.resource_market.service import (
    get_resource_provider_contract,
    list_latest_resource_quotes,
    list_resource_ohlcv_bars,
    list_supported_resource_instruments,
)


router = APIRouter()


@router.get("/provider-contract", response_model=ResourceProviderContractRead)
def get_provider_contract():
    return get_resource_provider_contract()


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
    return list_latest_resource_quotes(
        db,
        provider=provider,
        symbols=symbols,
        group=group,
        limit=limit,
    )


@router.get("/ohlcv/latest", response_model=list[ResourceOhlcvBarRead])
def get_latest_resource_ohlcv(
    provider: str | None = None,
    symbols: str | None = None,
    group: str | None = None,
    interval: str | None = None,
    limit: int = Query(default=500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    return list_resource_ohlcv_bars(
        db,
        provider=provider,
        symbols=symbols,
        group=group,
        interval=interval,
        limit=limit,
    )
