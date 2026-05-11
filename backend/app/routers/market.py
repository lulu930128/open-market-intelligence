from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.market.schemas import MarketDailyPriceRead
from app.market.service import list_market_daily_prices

router = APIRouter()


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