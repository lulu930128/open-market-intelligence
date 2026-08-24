from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.market.providers.kgi_canonical import canonical_snapshot_from_kgi
from app.market.providers.twse_mis_canonical import canonical_snapshot_from_twse_mis
from app.market_data.contracts import (
    InstrumentKey,
    InstrumentTradability,
    InstrumentType,
    Market,
    MarketSession,
    ObservationState,
    QuantityUnit,
    TradeObservationState,
)


TAIWAN_TZ = timezone(timedelta(hours=8))


def _instrument() -> InstrumentKey:
    return InstrumentKey(
        market=Market.TW,
        symbol="2330",
        instrument_type=InstrumentType.STOCK,
        venue="TWSE",
    )


def _kgi_quote(*, simtrade: int = 0) -> dict[str, object]:
    return {
        "exchange": "TWStock",
        "symbol": "2330",
        "odd_lot": False,
        "datetime": "20260630090512" if not simtrade else "20260630085900",
        "open": 2380 if not simtrade else 0,
        "high": 2420 if not simtrade else 0,
        "low": 2375 if not simtrade else 0,
        "close": 2410 if not simtrade else 2412.5,
        "volume": 750 if not simtrade else 2046,
        "total_volume": 49540 if not simtrade else 0,
        "bid_prices": [2410, 2405, 2400, 2395, 2390],
        "bid_volumes": [978, 1150, 1399, 599, 924],
        "ask_prices": [2415, 2420, 2425, 2430, 2435],
        "ask_volumes": [2, 209, 209, 3, 1],
        "price_chg": 40 if not simtrade else 42.5,
        "simtrade": simtrade,
        "suspend": 0,
        "received_at": "2026-06-30T01:05:12.100000+00:00",
    }


def _mis_message(*, trial: bool = False) -> dict[str, str]:
    return {
        "c": "2330",
        "d": "20260630",
        "t": "08:59:00" if trial else "09:05:12",
        "z": "-" if trial else "2410",
        "y": "2370",
        "o": "-" if trial else "2380",
        "h": "-" if trial else "2420",
        "l": "-" if trial else "2375",
        "v": "0" if trial else "49540",
        "tv": "-" if trial else "750",
        "b": "2410_2405_2400_2395_2390_",
        "g": "978_1150_1399_599_924_",
        "a": "2415_2420_2425_2430_2435_",
        "f": "2_209_209_3_1_",
        "ts": "1" if trial else "0",
        "pz": "2412.5" if trial else "-",
        "ps": "2046" if trial else "-",
    }


def test_kgi_live_quote_normalizes_lots_to_shares_with_lineage() -> None:
    snapshot = canonical_snapshot_from_kgi(
        instrument=_instrument(),
        quote=_kgi_quote(),
        session="regular_live",
    )
    assert snapshot.quote is not None
    assert snapshot.quote.last_trade_price == Decimal("2410")
    assert snapshot.quote.trade_state is TradeObservationState.TRADE_OBSERVED
    assert snapshot.quote.last_trade_quantity is not None
    assert snapshot.quote.last_trade_quantity.value == Decimal("750000")
    assert snapshot.quote.last_trade_quantity.original_value == Decimal("750")
    assert snapshot.quote.last_trade_quantity.original_unit is QuantityUnit.BOARD_LOT
    assert snapshot.depth is not None
    assert snapshot.depth.bids[0].quantity is not None
    assert snapshot.depth.bids[0].quantity.value == Decimal("978000")
    assert snapshot.session is not None
    assert snapshot.session.session is MarketSession.CONTINUOUS
    assert snapshot.trading_status is not None
    assert snapshot.trading_status.status is InstrumentTradability.UNKNOWN
    assert snapshot.trading_status.official is False


def test_kgi_simtrade_is_indicative_and_never_becomes_last_trade() -> None:
    snapshot = canonical_snapshot_from_kgi(
        instrument=_instrument(),
        quote=_kgi_quote(simtrade=1),
        session="preopen_auction",
    )
    assert snapshot.quote is not None
    assert snapshot.quote.state is ObservationState.INDICATIVE
    assert snapshot.quote.last_trade_price is None
    assert snapshot.quote.trade_state is TradeObservationState.INDICATIVE_OBSERVED
    assert snapshot.quote.last_trade_quantity is None
    assert snapshot.auction is not None
    assert snapshot.auction.indicative_price == Decimal("2412.5")
    assert snapshot.auction.indicative_quantity is not None
    assert snapshot.auction.indicative_quantity.value == Decimal("2046000")


def test_kgi_zero_cumulative_preopen_quote_is_indicative_when_flag_is_clear() -> None:
    quote = _kgi_quote()
    quote.update(
        {
            "datetime": "20260630083500",
            "open": 0,
            "high": 0,
            "low": 0,
            "close": 2412.5,
            "volume": 2046,
            "total_volume": 0,
            "simtrade": 0,
        }
    )

    snapshot = canonical_snapshot_from_kgi(
        instrument=_instrument(),
        quote=quote,
        session="preopen_auction",
    )

    assert snapshot.quote is not None
    assert snapshot.quote.state is ObservationState.INDICATIVE
    assert snapshot.quote.trade_state is TradeObservationState.INDICATIVE_OBSERVED
    assert snapshot.quote.last_trade_price is None
    assert snapshot.quote.last_trade_quantity is None
    assert snapshot.auction is not None
    assert snapshot.auction.indicative_price == Decimal("2412.5")


def test_kgi_adapter_rejects_symbol_mismatch_and_odd_lot() -> None:
    mismatch = _kgi_quote()
    mismatch["symbol"] = "2317"
    with pytest.raises(ValueError, match="does not match"):
        canonical_snapshot_from_kgi(
            instrument=_instrument(), quote=mismatch, session="regular_live"
        )
    odd_lot = _kgi_quote()
    odd_lot["odd_lot"] = True
    with pytest.raises(ValueError, match="odd-lot"):
        canonical_snapshot_from_kgi(
            instrument=_instrument(), quote=odd_lot, session="regular_live"
        )


def test_kgi_suspend_is_only_a_non_official_broker_hint() -> None:
    quote = _kgi_quote()
    quote["suspend"] = 1
    quote["price_chg"] = -40
    snapshot = canonical_snapshot_from_kgi(
        instrument=_instrument(), quote=quote, session="regular_live"
    )
    assert snapshot.quote is not None
    assert snapshot.quote.previous_close == Decimal("2450")
    assert snapshot.trading_status is not None
    assert snapshot.trading_status.status is InstrumentTradability.SUSPENDED
    assert snapshot.trading_status.official is False
    assert snapshot.trading_status.reason == "broker_suspend_hint"


def test_mis_actual_trade_requires_trade_date_time_and_volume_evidence() -> None:
    fetched_at = datetime(2026, 6, 30, 1, 5, 13, tzinfo=timezone.utc)
    snapshot = canonical_snapshot_from_twse_mis(
        instrument=_instrument(),
        message=_mis_message(),
        session="regular_live",
        fetched_at=fetched_at,
        expected_trade_date=date(2026, 6, 30),
    )
    assert snapshot.quote is not None
    assert snapshot.quote.last_trade_price == Decimal("2410")
    assert snapshot.quote.cumulative_quantity is not None
    assert snapshot.quote.cumulative_quantity.value == Decimal("49540000")
    assert snapshot.quote.lineage.provider == "twse_mis"
    assert snapshot.quote.lineage.event_at is not None
    assert snapshot.depth is not None
    assert len(snapshot.depth.bids) == 5


def test_mis_trial_fields_are_auction_evidence_not_actual_trade() -> None:
    fetched_at = datetime(2026, 6, 30, 0, 59, 1, tzinfo=timezone.utc)
    snapshot = canonical_snapshot_from_twse_mis(
        instrument=_instrument(),
        message=_mis_message(trial=True),
        session="preopen_auction",
        fetched_at=fetched_at,
        expected_trade_date=date(2026, 6, 30),
    )
    assert snapshot.quote is not None
    assert snapshot.quote.last_trade_price is None
    assert snapshot.quote.state is ObservationState.INDICATIVE
    assert snapshot.auction is not None
    assert snapshot.auction.indicative_price == Decimal("2412.5")
    assert snapshot.auction.indicative_quantity is not None
    assert snapshot.auction.indicative_quantity.original_value == Decimal("2046")


def test_mis_date_mismatch_cannot_manufacture_actual_trade() -> None:
    fetched_at = datetime(2026, 7, 1, 1, 5, 13, tzinfo=timezone.utc)
    snapshot = canonical_snapshot_from_twse_mis(
        instrument=_instrument(),
        message=_mis_message(),
        session="regular_live",
        fetched_at=fetched_at,
        expected_trade_date=date(2026, 7, 1),
    )
    assert snapshot.quote is not None
    assert snapshot.quote.last_trade_price is None
    assert snapshot.quote.state is ObservationState.PARTIAL
    assert snapshot.quote.trade_state is TradeObservationState.AWAITING_FIRST_TRADE


def test_mis_zero_price_depth_is_kept_as_non_price_level() -> None:
    message = _mis_message(trial=True)
    message["b"] = "0_2405_"
    message["g"] = "100_200_"
    snapshot = canonical_snapshot_from_twse_mis(
        instrument=_instrument(),
        message=message,
        session="preopen_auction",
        fetched_at=datetime(2026, 6, 30, 0, 59, 1, tzinfo=timezone.utc),
    )
    assert snapshot.depth is not None
    assert snapshot.depth.bids[0].price is None
    assert snapshot.depth.bids[0].quantity is not None
    assert snapshot.depth.bids[0].quantity.value == Decimal("100000")
