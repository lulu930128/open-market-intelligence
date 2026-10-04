from datetime import date, datetime, timezone

import pytest

from app.market.tw_daily_day_state import (
    TaiwanDailyEvidence, TaiwanDailyState, TaiwanPriceBasis, resolve_taiwan_daily_day_state,
)
from app.market_data.contracts import BarObservation, InstrumentKey, SourceLineage, TradingStatusObservation

DAY = date(2026, 8, 4)
INSTRUMENT = InstrumentKey(market="TW", venue="TPEX", symbol="9998", instrument_type="stock")
LINEAGE = SourceLineage(provider="tpex", source="official", authority="exchange",
    fetched_at=datetime(2026, 8, 5, tzinfo=timezone.utc), content_hash="receipt-hash", raw_receipt_id="receipt:1")


def evidence(**kwargs):
    return TaiwanDailyEvidence(trade_date=DAY, lineage=LINEAGE, all_prices_missing=True,
        **{"volume": 0, "trade_value": 0, "transaction_count": 0, **kwargs})


def price():
    return BarObservation(instrument=INSTRUMENT, lineage=LINEAGE, interval="1d",
        start_at=datetime(2026, 8, 4, 1, tzinfo=timezone.utc),
        end_at=datetime(2026, 8, 4, 5, 30, tzinfo=timezone.utc),
        open_price=10, high_price=10, low_price=10, close_price=10, finalization="final")


def status(value):
    return TradingStatusObservation(instrument=INSTRUMENT, lineage=LINEAGE,
        status=value, official=True)


def resolve(**kwargs):
    return resolve_taiwan_daily_day_state(instrument=INSTRUMENT, trade_date=DAY,
        **{"market_open": True, **kwargs})


@pytest.mark.parametrize("kwargs,state,expected", [
    ({"market_open": False}, "MARKET_CLOSED", False),
    ({"statuses": (status("suspended"),)}, "INSTRUMENT_SUSPENDED", False),
    ({"prices": (price(),)}, "TRADED_WITH_PRICE", True),
    ({"daily": (evidence(),)}, "VERIFIED_NO_TRADE", True),
    ({"daily": (evidence(trade_value=5000, transaction_count=6),)}, "TRADE_ACTIVITY_WITHOUT_PRICE", True),
    ({"daily": (evidence(trade_value=1000, transaction_count=2),)}, "TRADE_ACTIVITY_WITHOUT_PRICE", True),
    ({}, "MISSING_EVIDENCE", True),
    ({"market_open": None}, "MISSING_EVIDENCE", True),
    ({"statuses": (status("suspended"),), "prices": (price(),)}, "CONFLICTED_EVIDENCE", True),
    ({"market_open": False, "prices": (price(),)}, "CONFLICTED_EVIDENCE", True),
    ({"statuses": (status("suspended"), status("tradable"))}, "CONFLICTED_EVIDENCE", True),
    ({"daily": (evidence(), evidence(trade_value=1))}, "CONFLICTED_EVIDENCE", True),
])
def test_state_partition(kwargs, state, expected):
    result = resolve(**kwargs)
    assert result.state == state
    assert result.expected_session is expected


@pytest.mark.parametrize("kwargs", [{"volume": None}, {"trade_value": None},
    {"transaction_count": None}, {"all_prices_missing": False}])
def test_absence_is_never_no_trade(kwargs):
    row = evidence().model_copy(update=kwargs)
    assert resolve(daily=(row,)).state is TaiwanDailyState.MISSING_EVIDENCE


def test_unknown_status_does_not_remove_real_missing_day():
    result = resolve(statuses=(status("unknown"),))
    assert result.expected_session
    assert "HISTORICAL_INSTRUMENT_STATUS_UNKNOWN" in result.blockers


@pytest.mark.parametrize("basis,blocked", [
    (TaiwanPriceBasis(), True),
    (TaiwanPriceBasis(status="changed", coverage="complete"), True),
    (TaiwanPriceBasis(status="unchanged", coverage="partial"), True),
    (TaiwanPriceBasis(status="unchanged", coverage="complete", lineage=(LINEAGE,), limitations=()), False),
])
def test_no_trade_and_basis_are_independent(basis, blocked):
    result = resolve(daily=(evidence(),), price_basis=basis)
    assert result.state is TaiwanDailyState.VERIFIED_NO_TRADE
    assert bool(result.blockers) is blocked
    assert LINEAGE in result.lineage


def test_reliable_alternate_price_resolves_positive_activity():
    result = resolve(daily=(evidence(trade_value=5000, transaction_count=6),), prices=(price(),))
    assert result.state is TaiwanDailyState.TRADED_WITH_PRICE
