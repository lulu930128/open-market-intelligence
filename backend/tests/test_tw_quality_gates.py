"""G2 source gates using fake MIS requests and canonical synthetic bars only."""

from datetime import date, datetime

import pytest

from app.market.providers import twse_mis_current_breadth as provider
from app.market.tw_bar_aggregation import continuous_session_coverage
from app.market.tw_bar_service import _current_session_coverage
from app.market_data.contracts import InstrumentType, OperationalStatus
from test_tw_breadth_acquisition_evidence import clock, offline, message, CODES, fake_fetch
from test_tw_bar_aggregation import _bar, INSTRUMENT, TAIPEI


def test_rescue_timeout_degrades_transport_and_preserves_failure_backoff(clock, monkeypatch):
    calls = []
    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages", fake_fetch(clock, calls, scan_duration=0.1, rescue_duration=5))
    codes = CODES
    result = provider.read_twse_mis_current_breadth("TWSE", 20, universe_reader=lambda _: codes)
    assert result.payload is not None, result.error
    assert provider.TWSE_MIS_PROVIDER_GUARD.snapshot().allowed
    assert result.operational_status is OperationalStatus.DEGRADED
    assert result.detail_code == "TWSE_MIS_BREADTH_RESCUE_FAILED"
    assert result.payload["failed_batch_count"] == 0  # Primary transport remains independently successful.
    assert result.payload["missing_z_rescue"]["backoff_seconds"] == 300
    assert all(row["current_price"] is None for row in result.payload["component_stock_rows"] if row["code"] in CODES[:64])
    clock.seconds += 61
    payload, count = provider._rescue_missing_z("TWSE", codes, [], result.payload, prior_states=None, remaining_seconds=4)
    assert count == 0 and len(calls) == 12
    assert payload["missing_z_rescue"]["status"] == "backoff"
    assert payload["missing_z_rescue"]["backoff_seconds"] == 300


def test_missing_z_without_transport_failure_does_not_degrade_provider(clock, monkeypatch):
    monkeypatch.setattr(provider.twse_mis, "fetch_stock_messages",
                        lambda codes, **kw: [{**message(code), "z": "-" if code == "6001" else "110"} for code in codes])
    result = provider.read_twse_mis_current_breadth("TWSE", 20, universe_reader=lambda _: CODES)
    assert result.payload is not None, result.error
    assert result.operational_status is OperationalStatus.HEALTHY
    assert result.payload["missing_z_rescue"]["status"] == "partial"
    assert next(row for row in result.payload["component_stock_rows"] if row["code"] == "6001")["current_price"] is None


@pytest.mark.parametrize("missing,expected_status", [(set(), "complete_prefix"), ({0, 1}, "trailing_window"), ({100}, "sparse")])
def test_regular_minute_coverage_does_not_invent_opening_or_closing_bars(missing, expected_status):
    day = date(2026, 10, 8)
    bars = tuple(_bar(i, trade_date=day) for i in range(265) if i not in missing)
    coverage = continuous_session_coverage(bars, trade_date=day, trading_policy_version="tw.trading_policy.continuous.v1")
    result = _current_session_coverage(coverage, instrument=INSTRUMENT, snapshot_bars=bars, trade_date=day,
                                       instrument_type=InstrumentType.STOCK, session_closed=True)
    assert result.expected_bucket_count == 265
    assert result.observed_bucket_count == 265-len(missing)
    assert result.missing_bucket_count == len(missing)
    assert result.status.value == expected_status
    assert result.session_completed is True
    assert result.repair_recommended is bool(missing)
    assert bars[-1].start_at == datetime(2026, 10, 8, 13, 24, tzinfo=TAIPEI)
    assert all(item.status.value == "not_applicable" for item in coverage if item.bucket_start.hour == 13 and item.bucket_start.minute >= 25)
    assert all(item.status.value != "verified_no_trade" for item in coverage)
