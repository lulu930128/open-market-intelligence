from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market.public_quote_platform import (
    acquire_taiwan_public_last_trade_quote,
    read_taiwan_public_last_trade_quote,
)
from app.market_data.integration_contracts import MarketDataResultV1
from app.market_data.policies import RealtimePolicy


router = APIRouter()


@router.get(
    "/quotes/{stock_id}/public-last-trade",
    response_model=MarketDataResultV1,
)
def get_public_last_trade_quote(
    stock_id: str,
    db: Session = Depends(get_db),
):
    try:
        return read_taiwan_public_last_trade_quote(db, stock_id=stock_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post(
    "/quotes/{stock_id}/public-last-trade/refresh",
    response_model=MarketDataResultV1,
)
def refresh_public_last_trade_quote(
    stock_id: str,
    policy: Literal["prefer_live", "require_live"] = Query(
        default="prefer_live"
    ),
    db: Session = Depends(get_db),
):
    try:
        return acquire_taiwan_public_last_trade_quote(
            db,
            stock_id=stock_id,
            policy=RealtimePolicy(policy),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


__all__ = [
    "get_public_last_trade_quote",
    "refresh_public_last_trade_quote",
    "router",
]
