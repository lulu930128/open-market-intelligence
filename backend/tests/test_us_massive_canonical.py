from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.market_data.contracts import InstrumentKey, InstrumentType, Market
from app.market_data.integration_contracts import ProviderTimeframe
from app.us_market.providers.canonical import (
    canonical_massive_index_aggregates_payload,
    canonical_massive_index_snapshot_payload,
)


EASTERN = ZoneInfo("America/New_York")


def _index(symbol: str = "^GSPC") -> InstrumentKey:
    return InstrumentKey(
        market=Market.US,
        symbol=symbol,
        instrument_type=InstrumentType.INDEX,
        venue="INDEX",
    )


def test_massive_snapshot_preserves_event_time_timeframe_and_omi_identity() -> None:
    event_at = datetime(2026, 9, 1, 15, 59, tzinfo=EASTERN)
    batch = canonical_massive_index_snapshot_payload(
        instrument=_index(),
        payload={
            "status": "OK",
            "results": [
                {
                    "ticker": "I:SPX",
                    "value": 6512.34,
                    "last_updated": int(event_at.timestamp() * 1_000_000_000),
                    "timeframe": "REAL-TIME",
                    "market_status": "open",
                    "session": {
                        "open": 6480.0,
                        "high": 6520.0,
                        "low": 6470.0,
                        "previous_close": 6460.0,
                    },
                }
            ],
        },
        fetched_at=event_at.replace(second=30),
    )

    assert batch.snapshot is not None
    quote = batch.snapshot.quote
    assert quote is not None
    assert quote.instrument.symbol == "^GSPC"
    assert quote.last_trade_price == Decimal("6512.34")
    assert quote.lineage.provider == "massive"
    assert quote.lineage.event_at == event_at.astimezone(timezone.utc)
    assert batch.provider_timeframe is ProviderTimeframe.REAL_TIME
    assert batch.limitations == ()


def test_massive_delayed_snapshot_is_explicitly_limited() -> None:
    event_at = datetime(2026, 9, 1, 15, 45, tzinfo=EASTERN)
    batch = canonical_massive_index_snapshot_payload(
        instrument=_index("^VIX"),
        payload={
            "results": [
                {
                    "ticker": "I:VIX",
                    "value": 18.4,
                    "last_updated": int(event_at.timestamp() * 1_000_000_000),
                    "timeframe": "DELAYED",
                }
            ]
        },
        fetched_at=datetime(2026, 9, 1, 16, 0, tzinfo=EASTERN),
    )

    assert batch.provider_timeframe is ProviderTimeframe.DELAYED
    assert batch.limitations == ("MASSIVE_PROVIDER_TIMEFRAME_DELAYED",)


def test_massive_minute_aggregates_sort_and_preserve_not_applicable_volume() -> None:
    batch = canonical_massive_index_aggregates_payload(
        instrument=_index("^SOX"),
        payload={
            "status": "OK",
            "ticker": "I:SOX",
            "results": [
                {"t": 1788298260000, "o": 5901, "h": 5904, "l": 5899, "c": 5903},
                {"t": 1788298200000, "o": 5900, "h": 5902, "l": 5898, "c": 5901},
                {"t": "bad", "o": 1, "h": 1, "l": 1, "c": 1},
            ],
        },
        fetched_at=datetime(2026, 9, 2, 14, 0, tzinfo=timezone.utc),
        interval="1m",
    )

    assert len(batch.bars) == 2
    assert batch.bars[0].start_at < batch.bars[1].start_at
    assert all(bar.volume is None for bar in batch.bars)
    assert all(bar.volume_status == "not_applicable" for bar in batch.bars)
    assert all(bar.lineage.provider == "massive" for bar in batch.bars)
    assert "MALFORMED_BARS_SKIPPED" in batch.limitations


def test_massive_daily_bar_uses_us_completed_session_boundary() -> None:
    batch = canonical_massive_index_aggregates_payload(
        instrument=_index("^IXIC"),
        payload={
            "status": "DELAYED",
            "ticker": "I:COMP",
            "results": [
                {"t": 1788235200000, "o": 22000, "h": 22200, "l": 21900, "c": 22150}
            ],
        },
        fetched_at=datetime(2026, 9, 2, 8, 0, tzinfo=EASTERN),
        interval="1d",
    )

    assert len(batch.bars) == 1
    bar = batch.bars[0]
    assert (bar.start_at.hour, bar.start_at.minute) == (9, 30)
    assert (bar.end_at.hour, bar.end_at.minute) == (16, 0)
    assert bar.finalization.value == "final"
    assert bar.volume_status == "not_applicable"
    assert batch.provider_timeframe is ProviderTimeframe.DELAYED
    assert "MASSIVE_PROVIDER_TIMEFRAME_DELAYED" in batch.limitations


def test_massive_adapter_rejects_stock_identity() -> None:
    stock = InstrumentKey(
        market=Market.US,
        symbol="AAPL",
        instrument_type=InstrumentType.STOCK,
        venue="NASDAQ",
    )
    with pytest.raises(ValueError, match="only canonical index"):
        canonical_massive_index_snapshot_payload(
            instrument=stock,
            payload={"results": []},
            fetched_at=datetime.now(timezone.utc),
        )
