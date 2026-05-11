from datetime import date

from sqlalchemy.orm import Session

from app.db.models import MarketDailyPrice


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