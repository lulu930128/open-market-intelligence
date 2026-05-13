from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import InstitutionalTradeDaily, MarketDailyPrice


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

