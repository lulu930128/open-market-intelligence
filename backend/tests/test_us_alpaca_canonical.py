from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.market_data.contracts import InstrumentKey, InstrumentType, Market
from app.us_market.providers.canonical import canonical_alpaca_stock_bars_payload


NEW_YORK = ZoneInfo("America/New_York")


def _instrument(instrument_type: InstrumentType = InstrumentType.STOCK) -> InstrumentKey:
    return InstrumentKey(
        market=Market.US,
        symbol="AAPL" if instrument_type is not InstrumentType.INDEX else "^SOX",
        instrument_type=instrument_type,
        venue="NASDAQ",
    )


def _payload(*, close="232.14", next_page_token=None):
    return {
        "symbol": "AAPL",
        "bars": [
            {
                "t": "2026-08-28T04:00:00Z",
                "o": 230.5,
                "h": 233.2,
                "l": 229.9,
                "c": close,
                "v": 55881234,
                "n": 812345,
                "vw": 231.7,
            }
        ],
        "next_page_token": next_page_token,
    }


def test_alpaca_daily_maps_provider_midnight_to_us_session_identity() -> None:
    batch = canonical_alpaca_stock_bars_payload(
        instrument=_instrument(),
        payload=_payload(),
        fetched_at=datetime(2026, 8, 29, 9, 0, tzinfo=NEW_YORK),
    )

    assert len(batch.bars) == 1
    bar = batch.bars[0]
    assert bar.start_at.date().isoformat() == "2026-08-28"
    assert (bar.start_at.hour, bar.start_at.minute) == (9, 30)
    assert bar.end_at.hour == 16
    assert bar.lineage.event_at == bar.end_at
    assert bar.lineage.source == "alpaca.sip.stock_bars.1d"
    assert bar.close_price == Decimal("232.14")
    assert bar.volume is not None
    assert bar.volume.value == Decimal("55881234")
    assert bar.finalization.value == "final"
    assert "ALPACA_SIP_DELAYED_EVIDENCE" in batch.limitations


def test_alpaca_malformed_bar_and_pagination_are_truthful() -> None:
    batch = canonical_alpaca_stock_bars_payload(
        instrument=_instrument(),
        payload=_payload(close=None, next_page_token="next"),
        fetched_at=datetime(2026, 8, 29, 9, 0, tzinfo=NEW_YORK),
    )
    assert batch.bars == ()
    assert batch.skipped_bar_count == 1
    assert "MALFORMED_BARS_SKIPPED" in batch.limitations
    assert "ALPACA_PAGINATION_TRUNCATED" in batch.limitations


def test_alpaca_stock_endpoint_rejects_index_identity() -> None:
    with pytest.raises(ValueError, match="stocks and ETFs"):
        canonical_alpaca_stock_bars_payload(
            instrument=_instrument(InstrumentType.INDEX),
            payload={"symbol": "^SOX", "bars": []},
            fetched_at=datetime(2026, 8, 29, 9, 0, tzinfo=NEW_YORK),
        )
