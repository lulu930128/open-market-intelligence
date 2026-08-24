from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market.tw_market_dashboard import (
    DEFAULT_GROUP_LIMIT,
    DEFAULT_WATCHLIST_LIMIT,
    TaiwanDashboardStockNotFoundError,
    TaiwanDashboardWatchlistGroupNotFoundError,
    build_tw_dashboard_stock_detail,
    build_tw_market_dashboard,
    search_tw_dashboard_symbols,
)
from app.market.tw_market_dashboard_schemas import (
    TaiwanDashboardSymbolSearchRead,
    TaiwanDashboardStockDetailRead,
    TaiwanMarketDashboardRead,
)


router = APIRouter()


@router.get("/snapshot", response_model=TaiwanMarketDashboardRead)
def read_tw_market_dashboard(
    watchlist_group_id: int | None = Query(default=None, ge=1),
    include_watchlist_children: bool = Query(default=True),
    watchlist_limit: int = Query(
        default=DEFAULT_WATCHLIST_LIMIT,
        ge=1,
        le=100,
    ),
    group_limit: int = Query(default=DEFAULT_GROUP_LIMIT, ge=1, le=30),
    db: Session = Depends(get_db),
):
    try:
        return build_tw_market_dashboard(
            db,
            watchlist_group_id=watchlist_group_id,
            include_watchlist_children=include_watchlist_children,
            watchlist_limit=watchlist_limit,
            group_limit=group_limit,
        )
    except TaiwanDashboardWatchlistGroupNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get("/symbols/search", response_model=TaiwanDashboardSymbolSearchRead)
def search_tw_market_dashboard_symbols(
    keyword: str = Query(min_length=1, max_length=80),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
):
    try:
        return search_tw_dashboard_symbols(db, keyword=keyword, limit=limit)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get(
    "/stocks/{stock_id}",
    response_model=TaiwanDashboardStockDetailRead,
)
def read_tw_market_dashboard_stock_detail(
    stock_id: str,
    timeframe: str = Query(
        default="daily",
        pattern="^(today|daily|weekly|monthly)$",
    ),
    bars: int = Query(default=90, ge=20, le=500),
    db: Session = Depends(get_db),
):
    try:
        return build_tw_dashboard_stock_detail(
            db,
            stock_id=stock_id,
            timeframe=timeframe,
            bars=bars,
        )
    except TaiwanDashboardStockNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
