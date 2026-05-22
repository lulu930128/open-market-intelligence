from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.market.backfill import backfill_tpex_trading_stock, backfill_twse_stock_day
from app.market.daily_metrics_backfill import ensure_daily_metrics, ensure_latest_daily_metrics
from app.db.session import get_db
from app.market.intraday import get_intraday_trend
from app.market.schemas import (
    IntradayTrendRead,
    InstitutionalTradeDailyRead,
    MarginTradingDailyRead,
    MarketDailyChartRead,
    MarketOhlcChartRead,
    MarketDailyPriceRead,
    TwseBackfillResultRead,
)
from app.market.service import (
    get_latest_stock_daily_price,
    get_latest_stock_institutional_trade,
    get_latest_stock_margin_trade,
    list_institutional_trades,
    list_latest_institutional_trades,
    list_latest_margin_trades,
    list_latest_market_daily_prices,
    list_margin_trades,
    list_market_daily_prices,
    list_stock_chart_data,
    list_stock_daily_history,
    list_stock_ohlc_chart_data,
    list_stock_institutional_trade_history,
    list_stock_margin_trade_history,
)

router = APIRouter()


def _split_categories(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@router.post("/backfill/twse/{stock_id}", response_model=TwseBackfillResultRead)
def backfill_twse_stock_daily_prices(
    stock_id: str,
    start_date: date,
    end_date: date,
    source_id: int = 1,
    sleep_seconds: float = 0.8,
    skip_existing_months: bool = False,
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
            skip_existing_months=skip_existing_months,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/backfill/tpex/{stock_id}", response_model=TwseBackfillResultRead)
def backfill_tpex_stock_daily_prices(
    stock_id: str,
    start_date: date,
    end_date: date,
    source_id: int = 6,
    sleep_seconds: float = 0.8,
    skip_existing_months: bool = False,
    db: Session = Depends(get_db),
):
    try:
        return backfill_tpex_trading_stock(
            db=db,
            stock_id=stock_id,
            start_date=start_date,
            end_date=end_date,
            source_id=source_id,
            sleep_seconds=sleep_seconds,
            skip_existing_months=skip_existing_months,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/backfill/daily-metrics")
def backfill_market_daily_metrics(
    start_date: date | None = None,
    end_date: date | None = None,
    categories: str = Query(default="institutional_trade,margin_trading"),
    lookback_days: int = Query(default=30, ge=1, le=1000),
    include_today: bool = False,
    sleep_seconds: float = Query(default=0.2, ge=0, le=3),
    skip_existing: bool = True,
    db: Session = Depends(get_db),
):
    try:
        category_list = _split_categories(categories)

        if start_date is not None:
            return ensure_daily_metrics(
                db=db,
                start_date=start_date,
                end_date=end_date or start_date,
                categories=category_list,
                sleep_seconds=sleep_seconds,
                skip_existing=skip_existing,
            )

        return ensure_latest_daily_metrics(
            db=db,
            categories=category_list,
            to_date=end_date,
            lookback_days=lookback_days,
            include_today=include_today,
            sleep_seconds=sleep_seconds,
            skip_existing=skip_existing,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/ohlc/{stock_id}", response_model=MarketOhlcChartRead)
def get_stock_ohlc_chart_data(
    stock_id: str,
    timeframe: str = Query(default="daily", pattern="^(daily|weekly|monthly)$"),
    bars: int = Query(default=90, ge=1, le=240),
    ensure_history: bool = True,
    to_date: date | None = None,
    sleep_seconds: float = Query(default=0.08, ge=0, le=2),
    db: Session = Depends(get_db),
):
    try:
        return list_stock_ohlc_chart_data(
            db=db,
            stock_id=stock_id,
            timeframe=timeframe,
            bars=bars,
            ensure_history=ensure_history,
            to_date=to_date,
            sleep_seconds=sleep_seconds,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/intraday/{stock_id}", response_model=IntradayTrendRead)
def get_stock_intraday_trend(
    stock_id: str,
    db: Session = Depends(get_db),
):
    return get_intraday_trend(db=db, stock_id=stock_id)


@router.get("/institutional/latest", response_model=list[InstitutionalTradeDailyRead])
def get_latest_institutional_trades(limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    return list_latest_institutional_trades(db=db, limit=limit, offset=offset)


@router.get("/institutional/{stock_id}/latest", response_model=InstitutionalTradeDailyRead)
def get_latest_stock_institutional_trade_api(
    stock_id: str,
    ensure_daily: bool = True,
    include_today: bool = False,
    sleep_seconds: float = Query(default=0.2, ge=0, le=3),
    db: Session = Depends(get_db),
):
    if ensure_daily:
        ensure_latest_daily_metrics(
            db=db,
            categories=["institutional_trade"],
            include_today=include_today,
            sleep_seconds=sleep_seconds,
        )

    result = get_latest_stock_institutional_trade(db=db, stock_id=stock_id)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Latest institutional trade for stock_id='{stock_id}' not found.")
    return result


@router.get("/institutional/{stock_id}/history", response_model=list[InstitutionalTradeDailyRead])
def get_stock_institutional_trade_history(
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=250, ge=1, le=5000),
    ensure_history: bool = True,
    lookback_days: int = Query(default=365, ge=1, le=5000),
    include_today: bool = False,
    sleep_seconds: float = Query(default=0.2, ge=0, le=3),
    db: Session = Depends(get_db),
):
    if ensure_history:
        if to_date is None:
            ensure_latest_daily_metrics(
                db=db,
                categories=["institutional_trade"],
                lookback_days=lookback_days,
                include_today=include_today,
                sleep_seconds=sleep_seconds,
            )
        else:
            ensure_daily_metrics(
                db=db,
                start_date=from_date or to_date - timedelta(days=lookback_days),
                end_date=to_date,
                categories=["institutional_trade"],
                sleep_seconds=sleep_seconds,
            )

    return list_stock_institutional_trade_history(db=db, stock_id=stock_id, from_date=from_date, to_date=to_date, limit=limit, ascending=True)


@router.get("/institutional", response_model=list[InstitutionalTradeDailyRead])
def get_institutional_trades(trade_date: date | None = None, stock_id: str | None = None, limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    return list_institutional_trades(db=db, trade_date=trade_date, stock_id=stock_id, limit=limit, offset=offset)


@router.get("/margin/latest", response_model=list[MarginTradingDailyRead])
def get_latest_margin_trades(
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_latest_margin_trades(db=db, limit=limit, offset=offset)


@router.get("/margin/{stock_id}/latest", response_model=MarginTradingDailyRead)
def get_latest_stock_margin_trade_api(
    stock_id: str,
    ensure_daily: bool = True,
    include_today: bool = False,
    sleep_seconds: float = Query(default=0.2, ge=0, le=3),
    db: Session = Depends(get_db),
):
    if ensure_daily:
        ensure_latest_daily_metrics(
            db=db,
            categories=["margin_trading"],
            include_today=include_today,
            sleep_seconds=sleep_seconds,
        )

    result = get_latest_stock_margin_trade(db=db, stock_id=stock_id)

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Latest margin trading for stock_id='{stock_id}' not found.",
        )

    return result


@router.get("/margin/{stock_id}/history", response_model=list[MarginTradingDailyRead])
def get_stock_margin_trade_history(
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = Query(default=250, ge=1, le=5000),
    ensure_history: bool = True,
    lookback_days: int = Query(default=365, ge=1, le=5000),
    include_today: bool = False,
    sleep_seconds: float = Query(default=0.2, ge=0, le=3),
    db: Session = Depends(get_db),
):
    if ensure_history:
        if to_date is None:
            ensure_latest_daily_metrics(
                db=db,
                categories=["margin_trading"],
                lookback_days=lookback_days,
                include_today=include_today,
                sleep_seconds=sleep_seconds,
            )
        else:
            ensure_daily_metrics(
                db=db,
                start_date=from_date or to_date - timedelta(days=lookback_days),
                end_date=to_date,
                categories=["margin_trading"],
                sleep_seconds=sleep_seconds,
            )

    return list_stock_margin_trade_history(
        db=db,
        stock_id=stock_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        ascending=True,
    )


@router.get("/margin", response_model=list[MarginTradingDailyRead])
def get_margin_trades(
    trade_date: date | None = None,
    stock_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    return list_margin_trades(
        db=db,
        trade_date=trade_date,
        stock_id=stock_id,
        limit=limit,
        offset=offset,
    )



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
