from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.market.backfill import backfill_twse_stock_day
from app.db.session import get_db
from app.market.schemas import (
    InstitutionalTradeDailyRead,
    MarketDailyChartRead,
    MarketDailyPriceRead,
    TwseBackfillResultRead,
)
from app.market.service import (
    get_latest_stock_daily_price,
    get_latest_stock_institutional_trade,
    list_institutional_trades,
    list_latest_institutional_trades,
    list_latest_market_daily_prices,
    list_market_daily_prices,
    list_stock_chart_data,
    list_stock_daily_history,
    list_stock_institutional_trade_history,
)

router = APIRouter()


@router.post("/backfill/twse/{stock_id}", response_model=TwseBackfillResultRead)
def backfill_twse_stock_daily_prices(
    stock_id: str,
    start_date: date,
    end_date: date,
    source_id: int = 1,
    sleep_seconds: float = 0.8,
    db: Session = Depends(get_db),
):
    try:
        return backfill_twse_stock_day(
            db=db,
            stock_id=stock_id,
            start_date=start_date,
            end_date=end_date,
            source_id=source_id,
            sleep_seconds=sleep_seconds,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/institutional/latest", response_model=list[InstitutionalTradeDailyRead])
def get_latest_institutional_trades(limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    return list_latest_institutional_trades(db=db, limit=limit, offset=offset)


@router.get("/institutional/{stock_id}/latest", response_model=InstitutionalTradeDailyRead)
def get_latest_stock_institutional_trade_api(stock_id: str, db: Session = Depends(get_db)):
    result = get_latest_stock_institutional_trade(db=db, stock_id=stock_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Latest institutional trade for stock_id='{stock_id}' not found.")
    return result


@router.get("/institutional/{stock_id}/history", response_model=list[InstitutionalTradeDailyRead])
def get_stock_institutional_trade_history(stock_id: str, from_date: date | None = None, to_date: date | None = None, limit: int = Query(default=250, ge=1, le=5000), db: Session = Depends(get_db)):
    return list_stock_institutional_trade_history(db=db, stock_id=stock_id, from_date=from_date, to_date=to_date, limit=limit, ascending=True)


@router.get("/institutional", response_model=list[InstitutionalTradeDailyRead])
def get_institutional_trades(trade_date: date | None = None, stock_id: str | None = None, limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    return list_institutional_trades(db=db, trade_date=trade_date, stock_id=stock_id, limit=limit, offset=offset)



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