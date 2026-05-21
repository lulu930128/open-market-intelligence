from collections import OrderedDict
from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import (
    InstitutionalTradeDaily,
    MarginTradingDaily,
    MarketDailyPrice,
    StockMaster,
)
from app.market.backfill import backfill_tpex_trading_stock, backfill_twse_stock_day


CHART_LOOKBACK_MULTIPLIER = {
    "daily": 1,
    "weekly": 7,
    "monthly": 31,
}


def list_market_daily_prices(
    db: Session,
    trade_date: date | None = None,
    stock_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[MarketDailyPrice]:
    query = db.query(MarketDailyPrice)

    if trade_date is not None:
        query = query.filter(MarketDailyPrice.trade_date == trade_date)

    if stock_id is not None:
        query = query.filter(MarketDailyPrice.stock_id == stock_id)

    return (
        query.order_by(
            MarketDailyPrice.trade_date.desc(),
            MarketDailyPrice.stock_id.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )


def get_latest_trade_date(db: Session) -> date | None:
    return db.query(func.max(MarketDailyPrice.trade_date)).scalar()


def list_latest_market_daily_prices(
    db: Session,
    limit: int = 100,
    offset: int = 0,
) -> list[MarketDailyPrice]:
    latest_trade_date = get_latest_trade_date(db)

    if latest_trade_date is None:
        return []

    return list_market_daily_prices(
        db=db,
        trade_date=latest_trade_date,
        limit=limit,
        offset=offset,
    )


def get_latest_stock_daily_price(
    db: Session,
    stock_id: str,
) -> MarketDailyPrice | None:
    return (
        db.query(MarketDailyPrice)
        .filter(MarketDailyPrice.stock_id == stock_id)
        .order_by(MarketDailyPrice.trade_date.desc())
        .first()
    )


def list_stock_daily_history(
    db: Session,
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 250,
    ascending: bool = True,
) -> list[MarketDailyPrice]:
    query = db.query(MarketDailyPrice).filter(MarketDailyPrice.stock_id == stock_id)

    if from_date is not None:
        query = query.filter(MarketDailyPrice.trade_date >= from_date)

    if to_date is not None:
        query = query.filter(MarketDailyPrice.trade_date <= to_date)

    # Get latest N rows first, then reverse to chronological order for charting.
    rows = (
        query.order_by(MarketDailyPrice.trade_date.desc())
        .limit(limit)
        .all()
    )

    if ascending:
        rows.reverse()

    return rows


def list_stock_chart_data(
    db: Session,
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 250,
) -> list[dict]:
    rows = list_stock_daily_history(
        db=db,
        stock_id=stock_id,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        ascending=True,
    )

    return [
        {
            "time": row.trade_date,
            "open": row.open_price,
            "high": row.high_price,
            "low": row.low_price,
            "close": row.close_price,
            "volume": row.trade_volume,
            "trade_value": row.trade_value,
            "transaction_count": row.transaction_count,
        }
        for row in rows
    ]


def _sum_nullable(values: list[int | None]) -> int | None:
    valid_values = [value for value in values if value is not None]

    if not valid_values:
        return None

    return sum(valid_values)


def _chart_row(row: MarketDailyPrice, time_value: date | None = None) -> dict:
    return {
        "time": time_value or row.trade_date,
        "open": row.open_price,
        "high": row.high_price,
        "low": row.low_price,
        "close": row.close_price,
        "volume": row.trade_volume,
        "trade_value": row.trade_value,
        "transaction_count": row.transaction_count,
    }


def _aggregate_market_rows(
    rows: list[MarketDailyPrice],
    timeframe: str,
) -> list[dict]:
    if timeframe == "daily":
        return [_chart_row(row) for row in rows]

    groups: "OrderedDict[date, list[MarketDailyPrice]]" = OrderedDict()

    for row in rows:
        if timeframe == "weekly":
            key = row.trade_date - timedelta(days=row.trade_date.weekday())
        else:
            key = date(row.trade_date.year, row.trade_date.month, 1)

        groups.setdefault(key, []).append(row)

    results: list[dict] = []

    for key, grouped_rows in groups.items():
        first = grouped_rows[0]
        last = grouped_rows[-1]
        highs = [
            row.high_price
            for row in grouped_rows
            if row.high_price is not None
        ]
        lows = [
            row.low_price
            for row in grouped_rows
            if row.low_price is not None
        ]

        results.append(
            {
                "time": key,
                "open": first.open_price,
                "high": max(highs) if highs else None,
                "low": min(lows) if lows else None,
                "close": last.close_price,
                "volume": _sum_nullable([row.trade_volume for row in grouped_rows]),
                "trade_value": _sum_nullable([row.trade_value for row in grouped_rows]),
                "transaction_count": _sum_nullable(
                    [row.transaction_count for row in grouped_rows]
                ),
            }
        )

    return results


def _get_stock_market(db: Session, stock_id: str) -> str | None:
    stock = db.query(StockMaster).filter(StockMaster.stock_id == stock_id).first()

    if stock is None:
        return None

    return stock.market.upper()


def _ensure_stock_history(
    db: Session,
    stock_id: str,
    start_date: date,
    end_date: date,
    sleep_seconds: float,
) -> dict | None:
    market = _get_stock_market(db=db, stock_id=stock_id)

    if market == "TWSE":
        return backfill_twse_stock_day(
            db=db,
            stock_id=stock_id,
            start_date=start_date,
            end_date=end_date,
            source_id=1,
            sleep_seconds=sleep_seconds,
            skip_existing_months=True,
        )

    if market == "TPEX":
        return backfill_tpex_trading_stock(
            db=db,
            stock_id=stock_id,
            start_date=start_date,
            end_date=end_date,
            source_id=6,
            sleep_seconds=sleep_seconds,
            skip_existing_months=True,
        )

    return {
        "stock_id": stock_id,
        "stock_name": None,
        "source_id": 0,
        "start_date": start_date,
        "end_date": end_date,
        "requested_month_count": 0,
        "fetched_month_count": 0,
        "skipped_existing_month_count": 0,
        "parsed_count": 0,
        "inserted_count": 0,
        "skipped_count": 0,
        "status": "skipped",
        "message": f"History backfill is not configured for market='{market}'.",
        "months": [],
    }


def list_stock_ohlc_chart_data(
    db: Session,
    stock_id: str,
    timeframe: str = "daily",
    bars: int = 90,
    ensure_history: bool = True,
    to_date: date | None = None,
    sleep_seconds: float = 0.1,
) -> dict:
    if timeframe not in CHART_LOOKBACK_MULTIPLIER:
        raise ValueError("timeframe must be one of: daily, weekly, monthly.")

    if bars <= 0:
        raise ValueError("bars must be greater than 0.")

    if bars > 240:
        raise ValueError("bars must be less than or equal to 240.")

    end_date = to_date or date.today()
    lookback_days = bars * CHART_LOOKBACK_MULTIPLIER[timeframe]
    start_date = end_date - timedelta(days=lookback_days)

    backfill_result = None

    if ensure_history:
        backfill_result = _ensure_stock_history(
            db=db,
            stock_id=stock_id,
            start_date=start_date,
            end_date=end_date,
            sleep_seconds=sleep_seconds,
        )

    rows = list_stock_daily_history(
        db=db,
        stock_id=stock_id,
        from_date=start_date,
        to_date=end_date,
        limit=5000,
        ascending=True,
    )
    points = _aggregate_market_rows(rows=rows, timeframe=timeframe)[-bars:]

    return {
        "stock_id": stock_id,
        "timeframe": timeframe,
        "bars": bars,
        "lookback_days": lookback_days,
        "from_date": start_date,
        "to_date": end_date,
        "point_count": len(points),
        "points": points,
        "backfill": backfill_result,
    }


def get_latest_institutional_trade_date(db: Session) -> date | None:
    return db.query(func.max(InstitutionalTradeDaily.trade_date)).scalar()


def list_institutional_trades(db: Session, trade_date: date | None = None, stock_id: str | None = None, limit: int = 100, offset: int = 0) -> list[InstitutionalTradeDaily]:
    query = db.query(InstitutionalTradeDaily)
    if trade_date is not None:
        query = query.filter(InstitutionalTradeDaily.trade_date == trade_date)
    if stock_id is not None:
        query = query.filter(InstitutionalTradeDaily.stock_id == stock_id)
    return query.order_by(InstitutionalTradeDaily.trade_date.desc(), InstitutionalTradeDaily.stock_id.asc()).offset(offset).limit(limit).all()


def list_latest_institutional_trades(db: Session, limit: int = 100, offset: int = 0) -> list[InstitutionalTradeDaily]:
    latest_trade_date = get_latest_institutional_trade_date(db)
    if latest_trade_date is None:
        return []
    return list_institutional_trades(db=db, trade_date=latest_trade_date, limit=limit, offset=offset)


def get_latest_stock_institutional_trade(db: Session, stock_id: str) -> InstitutionalTradeDaily | None:
    return db.query(InstitutionalTradeDaily).filter(InstitutionalTradeDaily.stock_id == stock_id).order_by(InstitutionalTradeDaily.trade_date.desc()).first()


def list_stock_institutional_trade_history(db: Session, stock_id: str, from_date: date | None = None, to_date: date | None = None, limit: int = 250, ascending: bool = True) -> list[InstitutionalTradeDaily]:
    query = db.query(InstitutionalTradeDaily).filter(InstitutionalTradeDaily.stock_id == stock_id)
    if from_date is not None:
        query = query.filter(InstitutionalTradeDaily.trade_date >= from_date)
    if to_date is not None:
        query = query.filter(InstitutionalTradeDaily.trade_date <= to_date)
    rows = query.order_by(InstitutionalTradeDaily.trade_date.desc()).limit(limit).all()
    if ascending:
        rows.reverse()
    return rows


def get_latest_margin_trade_date(db: Session) -> date | None:
    return db.query(func.max(MarginTradingDaily.trade_date)).scalar()


def list_margin_trades(
    db: Session,
    trade_date: date | None = None,
    stock_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[MarginTradingDaily]:
    query = db.query(MarginTradingDaily)

    if trade_date is not None:
        query = query.filter(MarginTradingDaily.trade_date == trade_date)

    if stock_id is not None:
        query = query.filter(MarginTradingDaily.stock_id == stock_id)

    return (
        query.order_by(
            MarginTradingDaily.trade_date.desc(),
            MarginTradingDaily.stock_id.asc(),
        )
        .offset(offset)
        .limit(limit)
        .all()
    )


def list_latest_margin_trades(
    db: Session,
    limit: int = 100,
    offset: int = 0,
) -> list[MarginTradingDaily]:
    latest_trade_date = get_latest_margin_trade_date(db)

    if latest_trade_date is None:
        return []

    return list_margin_trades(
        db=db,
        trade_date=latest_trade_date,
        limit=limit,
        offset=offset,
    )


def get_latest_stock_margin_trade(
    db: Session,
    stock_id: str,
) -> MarginTradingDaily | None:
    return (
        db.query(MarginTradingDaily)
        .filter(MarginTradingDaily.stock_id == stock_id)
        .order_by(MarginTradingDaily.trade_date.desc())
        .first()
    )


def list_stock_margin_trade_history(
    db: Session,
    stock_id: str,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 250,
    ascending: bool = True,
) -> list[MarginTradingDaily]:
    query = db.query(MarginTradingDaily).filter(MarginTradingDaily.stock_id == stock_id)

    if from_date is not None:
        query = query.filter(MarginTradingDaily.trade_date >= from_date)

    if to_date is not None:
        query = query.filter(MarginTradingDaily.trade_date <= to_date)

    rows = (
        query.order_by(MarginTradingDaily.trade_date.desc())
        .limit(limit)
        .all()
    )

    if ascending:
        rows.reverse()

    return rows
