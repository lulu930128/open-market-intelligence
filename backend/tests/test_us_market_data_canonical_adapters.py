from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from app.market_data.contracts import (
    BarFinalization,
    InstrumentKey,
    InstrumentType,
    Market,
    MarketSession,
)
from app.us_market.providers.canonical import (
    canonical_alphavantage_daily_payload,
    canonical_yahoo_chart_payload,
    us_session_for_timestamp,
)


NEW_YORK = ZoneInfo("America/New_York")


def _instrument() -> InstrumentKey:
    return InstrumentKey(
        market=Market.US,
        symbol="AAPL",
        instrument_type=InstrumentType.STOCK,
        venue="NASDAQ",
    )


def _timestamp(hour: int, minute: int, second: int = 0) -> int:
    return int(
        datetime(
            2026,
            8,
            21,
            hour,
            minute,
            second,
            tzinfo=NEW_YORK,
        ).timestamp()
    )


def _yahoo_payload() -> dict:
    return {
        "chart": {
            "result": [
                {
                    "meta": {
                        "symbol": "AAPL",
                        "currency": "USD",
                        "chartPreviousClose": 224.5,
                    },
                    "timestamp": [
                        _timestamp(8, 0),
                        _timestamp(9, 30),
                        _timestamp(16, 30),
                    ],
                    "indicators": {
                        "quote": [
                            {
                                "open": [224.8, 225.0, 226.1],
                                "high": [225.0, 226.0, 226.5],
                                "low": [224.6, 224.9, 226.0],
                                "close": [224.9, 225.8, 226.4],
                                "volume": [100, 1200, 80],
                            }
                        ]
                    },
                }
            ],
            "error": None,
        }
    }


def test_yahoo_intraday_converts_sessions_lineage_and_quote() -> None:
    fetched_at = datetime(2026, 8, 21, 17, 0, tzinfo=NEW_YORK)
    batch = canonical_yahoo_chart_payload(
        instrument=_instrument(),
        payload=_yahoo_payload(),
        fetched_at=fetched_at,
        interval="1m",
        session_scope="all",
    )

    assert len(batch.bars) == 3
    assert [us_session_for_timestamp(bar.start_at) for bar in batch.bars] == [
        MarketSession.PRE_OPEN,
        MarketSession.CONTINUOUS,
        MarketSession.POST_CLOSE,
    ]
    assert all(bar.volume and bar.volume.unit.value == "share" for bar in batch.bars)
    assert all(bar.finalization is BarFinalization.FINAL for bar in batch.bars)
    assert batch.snapshot is not None
    assert batch.snapshot.session is not None
    assert batch.snapshot.session.session is MarketSession.POST_CLOSE
    assert batch.snapshot.quote is not None
    assert batch.snapshot.quote.last_trade_price == Decimal("226.4")
    assert batch.snapshot.quote.previous_close == Decimal("224.5")
    assert batch.snapshot.quote.lineage.provider == "yahoo_chart"
    assert batch.snapshot.quote.lineage.event_at is not None
    assert batch.snapshot.quote.lineage.fetched_at == fetched_at


def test_yahoo_scope_filter_and_provisional_bar_are_truthful() -> None:
    batch = canonical_yahoo_chart_payload(
        instrument=_instrument(),
        payload=_yahoo_payload(),
        fetched_at=datetime(2026, 8, 21, 9, 30, 30, tzinfo=NEW_YORK),
        interval="1m",
        session_scope="regular",
    )
    assert len(batch.bars) == 1
    assert batch.bars[0].start_at.hour == 9
    assert batch.bars[0].finalization is BarFinalization.PROVISIONAL


def test_yahoo_intraday_normalizes_and_deduplicates_provider_minute_identity() -> None:
    payload = _yahoo_payload()
    payload["chart"]["result"][0]["timestamp"] = [
        _timestamp(9, 30, 15),
        _timestamp(9, 30, 52),
    ]
    quote = payload["chart"]["result"][0]["indicators"]["quote"][0]
    quote["open"] = [225.0, 225.4]
    quote["high"] = [225.5, 226.0]
    quote["low"] = [224.9, 225.2]
    quote["close"] = [225.4, 225.8]
    quote["volume"] = [300, 500]
    fetched_at = datetime(2026, 8, 21, 9, 30, 58, tzinfo=NEW_YORK)

    batch = canonical_yahoo_chart_payload(
        instrument=_instrument(),
        payload=payload,
        fetched_at=fetched_at,
        interval="1m",
        session_scope="regular",
    )

    assert len(batch.bars) == 1
    assert batch.bars[0].start_at == datetime(
        2026,
        8,
        21,
        9,
        30,
        tzinfo=NEW_YORK,
    )
    assert batch.bars[0].end_at == datetime(
        2026,
        8,
        21,
        9,
        31,
        tzinfo=NEW_YORK,
    )
    assert batch.bars[0].close_price == Decimal("225.8")
    assert batch.bars[0].lineage.event_at == datetime(
        2026,
        8,
        21,
        9,
        30,
        52,
        tzinfo=NEW_YORK,
    )
    assert batch.bars[0].lineage.event_at <= fetched_at
    assert "YAHOO_DUPLICATE_MINUTE_BARS_DEDUPLICATED" in batch.limitations


def test_yahoo_extended_zero_volume_is_unknown_not_traded_zero() -> None:
    payload = _yahoo_payload()
    payload["chart"]["result"][0]["indicators"]["quote"][0]["volume"] = [0, 0, 0]
    batch = canonical_yahoo_chart_payload(
        instrument=_instrument(),
        payload=payload,
        fetched_at=datetime(2026, 8, 21, 17, 0, tzinfo=NEW_YORK),
        interval="1m",
        session_scope="all",
    )

    assert batch.bars[0].volume is None
    assert batch.bars[1].volume is not None
    assert batch.bars[1].volume.value == Decimal("0")
    assert batch.bars[2].volume is None
    assert "YAHOO_EXTENDED_VOLUME_ZERO_FILLED" in batch.limitations


def test_early_close_session_mapping_uses_verified_1300_close() -> None:
    assert us_session_for_timestamp(
        datetime(2026, 11, 27, 12, 59, tzinfo=NEW_YORK)
    ) is MarketSession.CONTINUOUS
    assert us_session_for_timestamp(
        datetime(2026, 11, 27, 13, 0, tzinfo=NEW_YORK)
    ) is MarketSession.CLOSING_AUCTION
    assert us_session_for_timestamp(
        datetime(2026, 11, 27, 13, 1, tzinfo=NEW_YORK)
    ) is MarketSession.POST_CLOSE


def test_yahoo_regular_scope_keeps_the_1600_closing_auction_print() -> None:
    payload = _yahoo_payload()
    payload["chart"]["result"][0]["timestamp"] = [
        _timestamp(15, 59),
        _timestamp(16, 0),
    ]
    quote = payload["chart"]["result"][0]["indicators"]["quote"][0]
    quote["open"] = [225.0, 225.8]
    quote["high"] = [226.0, 226.1]
    quote["low"] = [224.9, 225.7]
    quote["close"] = [225.8, 226.0]
    quote["volume"] = [1200, 5000]

    batch = canonical_yahoo_chart_payload(
        instrument=_instrument(),
        payload=payload,
        fetched_at=datetime(2026, 8, 21, 16, 2, tzinfo=NEW_YORK),
        interval="1m",
        session_scope="regular",
    )

    assert len(batch.bars) == 2
    assert [us_session_for_timestamp(bar.start_at) for bar in batch.bars] == [
        MarketSession.CONTINUOUS,
        MarketSession.CLOSING_AUCTION,
    ]
    assert batch.snapshot is not None
    assert batch.snapshot.session is not None
    assert batch.snapshot.session.session is MarketSession.CLOSING_AUCTION


def test_yahoo_malformed_bar_is_counted_not_coerced_to_zero() -> None:
    payload = _yahoo_payload()
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"][1] = None
    batch = canonical_yahoo_chart_payload(
        instrument=_instrument(),
        payload=payload,
        fetched_at=datetime(2026, 8, 21, 17, 0, tzinfo=NEW_YORK),
        interval="1m",
        session_scope="all",
    )
    assert len(batch.bars) == 2
    assert batch.skipped_bar_count == 1
    assert batch.limitations == ("MALFORMED_BARS_SKIPPED",)


def test_alphavantage_daily_converts_raw_bars_and_adjusted_limitation() -> None:
    payload = {
        "Meta Data": {"2. Symbol": "AAPL"},
        "Time Series (Daily)": {
            "2026-08-20": {
                "1. open": "223.1",
                "2. high": "225.0",
                "3. low": "222.8",
                "4. close": "224.9",
                "5. adjusted close": "224.7",
                "6. volume": "1234567",
            }
        },
    }
    batch = canonical_alphavantage_daily_payload(
        instrument=_instrument(),
        payload=payload,
        fetched_at=datetime(2026, 8, 21, 8, 0, tzinfo=NEW_YORK),
    )
    assert len(batch.bars) == 1
    assert batch.bars[0].close_price == Decimal("224.9")
    assert batch.bars[0].volume is not None
    assert batch.bars[0].volume.value == Decimal("1234567")
    assert batch.snapshot is not None
    assert batch.snapshot.session is not None
    assert batch.snapshot.session.session is MarketSession.POST_CLOSE
    assert batch.price_basis == "raw"
    assert "ADJUSTED_CLOSE_AVAILABLE_BUT_BARS_REMAIN_RAW" in batch.limitations


def test_provider_symbol_mismatch_and_naive_fetch_time_fail_closed() -> None:
    payload = _yahoo_payload()
    payload["chart"]["result"][0]["meta"]["symbol"] = "MSFT"
    with pytest.raises(ValueError, match="provider symbol"):
        canonical_yahoo_chart_payload(
            instrument=_instrument(),
            payload=payload,
            fetched_at=datetime(2026, 8, 21, 17, 0, tzinfo=NEW_YORK),
            interval="1m",
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        canonical_yahoo_chart_payload(
            instrument=_instrument(),
            payload=_yahoo_payload(),
            fetched_at=datetime(2026, 8, 21, 17, 0),
            interval="1m",
        )


def test_non_us_instrument_is_rejected() -> None:
    with pytest.raises((ValueError, ValidationError)):
        canonical_yahoo_chart_payload(
            instrument=InstrumentKey(
                market=Market.TW,
                symbol="2330",
                instrument_type=InstrumentType.STOCK,
                venue="TWSE",
            ),
            payload=_yahoo_payload(),
            fetched_at=datetime(2026, 8, 21, 17, 0, tzinfo=NEW_YORK),
            interval="1m",
        )
