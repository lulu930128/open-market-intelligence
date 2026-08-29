from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.market_data.contracts import InstrumentKey, InstrumentType, Market
from app.us_market.providers.canonical import (
    canonical_twelve_data_intraday_payload,
    canonical_twelve_data_quote_payload,
)


NEW_YORK = ZoneInfo("America/New_York")


def _instrument() -> InstrumentKey:
    return InstrumentKey(
        market=Market.US,
        symbol="AAPL",
        instrument_type=InstrumentType.STOCK,
        venue="NASDAQ",
    )


def test_twelve_quote_preserves_partial_volume_limitation() -> None:
    batch = canonical_twelve_data_quote_payload(
        instrument=_instrument(),
        payload={
            "symbol": "AAPL",
            "currency": "USD",
            "datetime": "2026-08-28 15:59:00",
            "open": "230.0",
            "high": "233.0",
            "low": "229.5",
            "close": "232.1",
            "previous_close": "229.2",
            "volume": "123456",
        },
        fetched_at=datetime(2026, 8, 28, 16, 0, tzinfo=NEW_YORK),
    )
    assert batch.snapshot is not None
    assert batch.snapshot.quote is not None
    assert batch.snapshot.quote.last_trade_price == Decimal("232.1")
    assert batch.snapshot.quote.lineage.provider == "twelve_data"
    assert batch.limitations == ("PARTIAL_US_MARKET_VOLUME",)


def test_twelve_quote_uses_price_when_close_is_null() -> None:
    batch = canonical_twelve_data_quote_payload(
        instrument=_instrument(),
        payload={
            "symbol": "AAPL",
            "currency": "USD",
            "datetime": "2026-08-28 15:59:00",
            "close": None,
            "price": "232.1",
        },
        fetched_at=datetime(2026, 8, 28, 16, 0, tzinfo=NEW_YORK),
    )
    assert batch.snapshot is not None
    assert batch.snapshot.quote is not None
    assert batch.snapshot.quote.last_trade_price == Decimal("232.1")


def test_twelve_intraday_sorts_local_exchange_times_and_flags_bad_rows() -> None:
    batch = canonical_twelve_data_intraday_payload(
        instrument=_instrument(),
        payload={
            "meta": {
                "symbol": "AAPL",
                "currency": "USD",
                "exchange_timezone": "America/New_York",
            },
            "values": [
                {
                    "datetime": "2026-08-28 09:31:00",
                    "open": "230.2",
                    "high": "230.4",
                    "low": "230.1",
                    "close": "230.3",
                    "volume": "1200",
                },
                {
                    "datetime": "2026-08-28 09:30:00",
                    "open": "230.0",
                    "high": "230.3",
                    "low": "229.9",
                    "close": "230.2",
                    "volume": "1000",
                },
                {
                    "datetime": "broken",
                    "open": "1",
                    "high": "1",
                    "low": "1",
                    "close": "1",
                },
            ],
        },
        fetched_at=datetime(2026, 8, 28, 10, 0, tzinfo=NEW_YORK),
        interval="1min",
    )
    assert [bar.start_at.minute for bar in batch.bars] == [30, 31]
    assert all(bar.interval == "1m" for bar in batch.bars)
    assert "PARTIAL_US_MARKET_VOLUME" in batch.limitations
    assert "MALFORMED_BARS_SKIPPED" in batch.limitations


def test_twelve_intraday_duplicate_timestamp_fails_closed() -> None:
    row = {
        "datetime": "2026-08-28 09:30:00",
        "open": "230.0",
        "high": "230.3",
        "low": "229.9",
        "close": "230.2",
        "volume": "1000",
    }
    with pytest.raises(ValueError, match="duplicate"):
        canonical_twelve_data_intraday_payload(
            instrument=_instrument(),
            payload={
                "meta": {
                    "symbol": "AAPL",
                    "exchange_timezone": "America/New_York",
                },
                "values": [row, dict(row)],
            },
            fetched_at=datetime(2026, 8, 28, 10, 0, tzinfo=NEW_YORK),
            interval="1min",
        )
