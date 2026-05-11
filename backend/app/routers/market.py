from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market.schemas import MarketDailyChartRead, MarketDailyPriceRead
from app.market.service import (
    get_latest_stock_daily_price,
    list_latest_market_daily_prices,
    list_market_daily_prices,
    list_stock_chart_data,
    list_stock_daily_history,
)

router = APIRouter()


@router.get("/daily/latest", response_model=list[MarketDailyPriceRead])
def get_latest_market_daily_prices(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_latest_market_daily_prices(
        db=db,
        limit=limit,
        offset=offset,
    )


@router.get("/daily/{stock_id}/latest", response_model=MarketDailyPriceRead)
def get_latest_stock_daily_price_api(
    stock_id: str,
    db: Session = Depends(get_db),
):
    result = get_latest_stock_daily_price(db=db, stock_id=stock_id)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Latest market daily price for stock_id='{stock_id}' not found.",
        )

    return result


@router.get("/daily/{stock_id}/history", response_model=list[MarketDailyPriceRead])
def get_stock_daily_history(
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=250, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    return list_stock_daily_history(
        db=db,
        stock_id=stock_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        ascending=True,
    )


@router.get("/daily/{stock_id}/chart", response_model=list[MarketDailyChartRead])
def get_stock_daily_chart_data(
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=250, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    return list_stock_chart_data(
        db=db,
        stock_id=stock_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
    )


@router.get("/daily", response_model=list[MarketDailyPriceRead])
def get_market_daily_prices(
    trade_date: date | None = None,
    stock_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_market_daily_prices(
        db=db,
        trade_date=trade_date,
        stock_id=stock_id,
        limit=limit,
        offset=offset,
    )