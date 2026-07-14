from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.db.models import USDailyPrice, utc_now
from app.us_market.chart_projection import should_skip_daily_price_update as _should_skip_us_daily_price_update
from app.us_market.sources import USDailyPriceRecord, normalize_us_symbol

def upsert_us_daily_price_records(
    db: Session,
    records: list[USDailyPriceRecord],
) -> dict:
    inserted_count = 0
    updated_count = 0

    for record in records:
        existing = (
            db.query(USDailyPrice)
            .filter(USDailyPrice.provider == record.provider)
            .filter(USDailyPrice.symbol == record.symbol)
            .filter(USDailyPrice.trade_date == record.trade_date)
            .first()
        )

        if existing is None:
            db.add(
                USDailyPrice(
                    provider=record.provider,
                    symbol=record.symbol,
                    trade_date=record.trade_date,
                    open_price=record.open_price,
                    high_price=record.high_price,
                    low_price=record.low_price,
                    close_price=record.close_price,
                    adjusted_close=record.adjusted_close,
                    trade_volume=record.trade_volume,
                    dividend_amount=record.dividend_amount,
                    split_coefficient=record.split_coefficient,
                    source_url=record.source_url,
                    raw_payload_hash=record.raw_payload_hash,
                    fetched_at=utc_now(),
                )
            )
            inserted_count += 1
            continue

        if _should_skip_us_daily_price_update(existing=existing, record=record):
            continue

        existing.open_price = record.open_price
        existing.high_price = record.high_price
        existing.low_price = record.low_price
        existing.close_price = record.close_price
        existing.adjusted_close = record.adjusted_close
        existing.trade_volume = record.trade_volume
        existing.dividend_amount = record.dividend_amount
        existing.split_coefficient = record.split_coefficient
        existing.source_url = record.source_url
        existing.raw_payload_hash = record.raw_payload_hash
        existing.fetched_at = utc_now()
        existing.updated_at = utc_now()
        updated_count += 1

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
    }


def _us_daily_price_sample(row: USDailyPrice) -> dict:
    return {
        "id": row.id,
        "provider": row.provider,
        "symbol": row.symbol,
        "trade_date": row.trade_date,
        "open_price": row.open_price,
        "high_price": row.high_price,
        "low_price": row.low_price,
        "close_price": row.close_price,
        "trade_volume": row.trade_volume,
        "source_url": row.source_url,
    }


def list_us_daily_prices(
    db: Session,
    *,
    symbol: str,
    provider: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[USDailyPrice]:
    normalized_symbol = normalize_us_symbol(symbol)
    query = db.query(USDailyPrice).filter(USDailyPrice.symbol == normalized_symbol)

    if provider is not None:
        query = query.filter(USDailyPrice.provider == provider)

    if from_date is not None:
        query = query.filter(USDailyPrice.trade_date >= from_date)

    if to_date is not None:
        query = query.filter(USDailyPrice.trade_date <= to_date)

    return (
        query.order_by(USDailyPrice.trade_date.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


def _list_us_ohlc_source_rows(
    db: Session,
    *,
    symbol: str,
    from_date: date,
    to_date: date,
) -> list[USDailyPrice]:
    rows = list_us_daily_prices(
        db=db,
        symbol=symbol,
        from_date=from_date,
        to_date=to_date,
        limit=5000,
        offset=0,
    )
    return sorted(rows, key=lambda row: row.trade_date)
