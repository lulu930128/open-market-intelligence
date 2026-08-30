from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.models import RawFetchResult, SourceRegistry, USDailyPrice
from app.us_market.sources import USDailyPriceRecord, normalize_us_symbol
from app.us_market.trading_calendar import US_MARKET_TIMEZONE, us_session_close_time


_CANONICAL_LINEAGE = {
    "yahoo_chart": ("yahoo.chart.1d", "yahoo.chart.v8"),
    "alphavantage": (
        "alphavantage.time_series_daily",
        "alphavantage.daily.v1",
    ),
    "alpaca": ("alpaca.sip.stock_bars.1d", "alpaca.stock_bars.v2"),
}


def upsert_canonical_us_daily_price_records(
    db: Session,
    records: list[USDailyPriceRecord],
) -> dict[str, int]:
    """Persist complete canonical test lineage without using legacy quarantine."""

    inserted_count = 0
    updated_count = 0
    for record in records:
        symbol = normalize_us_symbol(record.symbol)
        source_name, contract_version = _CANONICAL_LINEAGE.get(
            record.provider,
            (
                f"test_canonical.{record.provider}.daily",
                f"{record.provider}.test.v1",
            ),
        )
        source = (
            db.query(SourceRegistry)
            .filter(SourceRegistry.source_name == source_name)
            .first()
        )
        if source is None:
            source = SourceRegistry(
                source_name=source_name,
                source_type="api",
                category="market_data",
                endpoint_url=record.source_url,
                enabled=True,
                reliability_level="vendor",
            )
            db.add(source)
            db.flush()
        fetched_at = datetime.now(timezone.utc)
        content_hash = str(record.raw_payload_hash or "").strip() or (
            f"test:{record.provider}:{symbol}:{record.trade_date.isoformat()}"
        )
        raw = RawFetchResult(
            source_id=source.id,
            fetched_at=fetched_at,
            url=record.source_url,
            method="GET",
            content_hash=content_hash,
            parser_version=contract_version,
        )
        db.add(raw)
        db.flush()
        is_index = symbol.startswith("^")
        canonical_volume = None if is_index else record.trade_volume
        fields = {
            "open_price": record.open_price,
            "high_price": record.high_price,
            "low_price": record.low_price,
            "close_price": record.close_price,
            "adjusted_close": record.adjusted_close,
            "trade_volume": canonical_volume,
            "dividend_amount": record.dividend_amount,
            "split_coefficient": record.split_coefficient,
            "source_url": record.source_url,
            "source_id": source.id,
            "raw_result_id": raw.id,
            "raw_payload_hash": content_hash,
            "fetched_at": fetched_at,
            "authority": "vendor",
            "raw_contract_version": contract_version,
            "event_at": datetime.combine(
                record.trade_date,
                us_session_close_time(record.trade_date),
                tzinfo=US_MARKET_TIMEZONE,
            ),
            "finalization": "final",
            "price_basis": "raw",
            "volume_unit": "shares" if canonical_volume is not None else None,
            "volume_status": (
                "observed"
                if canonical_volume is not None
                else "not_applicable"
                if is_index
                else "missing"
            ),
        }
        row = (
            db.query(USDailyPrice)
            .filter(USDailyPrice.provider == record.provider)
            .filter(USDailyPrice.symbol == symbol)
            .filter(USDailyPrice.trade_date == record.trade_date)
            .first()
        )
        if row is None:
            db.add(
                USDailyPrice(
                    provider=record.provider,
                    symbol=symbol,
                    trade_date=record.trade_date,
                    currency="USD",
                    **fields,
                )
            )
            inserted_count += 1
        else:
            for name, value in fields.items():
                setattr(row, name, value)
            updated_count += 1
    db.commit()
    return {
        "inserted_count": inserted_count,
        "updated_count": updated_count,
    }


__all__ = ["upsert_canonical_us_daily_price_records"]
