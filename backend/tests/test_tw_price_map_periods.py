"""Period selection uses component end dates, canonical calculations and quality."""
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from app.market.technical_evidence import build_tw_stock_period_price_map_evidence
from app.market.stock_price_map import _collect_levels, _display_axis
from app.market.tw_bar_identity import build_taiwan_bar_series_identity
from app.market.tw_bar_aggregation import observed_trade_coverage
from app.market.trading_calendar import TAIWAN_TZ
from test_tw_technical_service import _series


def period_series(timeframe, partial=False, incomplete=False):
    original = _series()
    interval = {"weekly": "1w", "monthly": "1mo"}[timeframe]
    bars, states = [], []
    for index, bar in enumerate(original.bars):
        if timeframe == "weekly":
            start = datetime(2025, 1, 6, tzinfo=TAIWAN_TZ) + timedelta(weeks=index)
            end = start + timedelta(days=4, hours=13, minutes=30)
        else:
            year, month_index = divmod(2020 * 12 + index, 12)
            start = datetime(year, month_index + 1, 1, tzinfo=TAIWAN_TZ)
            next_year, next_month = divmod(2020 * 12 + index + 1, 12)
            end = datetime(next_year, next_month + 1, 1, tzinfo=TAIWAN_TZ) - timedelta(days=1)
            while end.weekday() > 4:
                end -= timedelta(days=1)
            end = end.replace(hour=13, minute=30)
        if partial and index == len(original.bars) - 1:
            end = start + timedelta(days=2, hours=13, minutes=30)
        bars.append(bar.model_copy(update={"start_at": start, "end_at": end, "interval": interval}))
        states.append(original.bar_states[index].model_copy(update={
            "start_at": start, "source_interval": "1d",
            "component_missing_trading_day_count": 1 if incomplete and index == 70 else 0,
        }))
    coverage = observed_trade_coverage(tuple(bars), trading_policy_version="test-period")
    identity = build_taiwan_bar_series_identity(instrument=original.instrument, requested_interval=interval,
        base_interval="1d", bars=tuple(bars), coverage=coverage, aggregation_version="period-test.v1",
        state={"bar_states": [state.model_dump(mode="json") for state in states]})
    return original.model_copy(update={"bars": tuple(bars), "bar_states": tuple(states),
        "requested_interval": interval, "derived": True, "aggregation_version": "period-test.v1",
        "bucket_coverage": coverage, "identity": identity,
        "history": original.history.model_copy(update={"requested_coverage_satisfied": not incomplete})})


@pytest.mark.parametrize("timeframe", ["weekly", "monthly"])
@pytest.mark.parametrize("partial", [False, True])
def test_period_map_uses_last_completed_bar_and_preserves_method_granularity(timeframe, partial):
    series = period_series(timeframe, partial=partial)
    history = {"cache_status": "current", "coverage_start": "2010-01-01", "coverage_end": "2030-12-31", "results": []}
    with patch("app.market.technical_evidence.TaiwanBarService") as service:
        service.return_value.read_bars.return_value = series
        evidence = build_tw_stock_period_price_map_evidence(db=object(), stock_id="2330", timeframe=timeframe, corporate_event_history=history)
    snapshot = evidence["indicators"]["timeframes"][timeframe]
    expected = series.bars[-2 if partial else -1]
    assert snapshot["completed"]["time"] == expected.start_at.date()
    assert snapshot["period"]["status"] == ("current_partial" if partial else "completed")
    assert snapshot["completed_bars"] == (79 if partial else 80)
    assert evidence["indicators"]["decision_usable"] is True
    assert "volume_profile" not in evidence
    assert evidence["method_applicability"]["volume_profile"] == "not_included_daily_ohlcv_method"
    levels = _collect_levels(evidence=evidence, next_plan={}, reference=140, timeframe=timeframe)
    assert levels
    assert all(level["timeframe"] == timeframe for level in levels)
    assert not any(level["evidence_state"] == "hypothetical" for level in levels)
    assert _display_axis(140, timeframe=timeframe)["range_percent"] > 10


def test_period_input_gap_or_unknown_corporate_history_stays_partial():
    for incomplete, history in ((True, {"cache_status": "current", "coverage_start": "2010-01-01", "coverage_end": "2030-12-31"}), (False, None)):
        with patch("app.market.technical_evidence.TaiwanBarService") as service:
            service.return_value.read_bars.return_value = period_series("weekly", incomplete=incomplete)
            evidence = build_tw_stock_period_price_map_evidence(db=object(), stock_id="2330", timeframe="weekly", corporate_event_history=history)
        assert evidence["status"] == "partial"
        assert evidence["indicators"]["decision_usable"] is False


def test_input_quality_policy_change_invalidates_snapshot_dependency_revision():
    from datetime import date
    from app.market.price_map_snapshot_repository import read_price_map_external_revision
    with (
        patch("app.market.tw_corporate_events.taiwan_corporate_event_revision", return_value="same-corporate-input"),
        patch("app.market.exchange_calendar_cache.read_exchange_calendar_cache", return_value={}),
    ):
        before = read_price_map_external_revision()
        with patch("app.market.tw_technical_service.INPUT_QUALITY_VERSION", "changed-policy"):
            assert read_price_map_external_revision() != before
        from app.market.trading_calendar import TAIWAN_MARKET_HOLIDAYS
        with patch.dict(TAIWAN_MARKET_HOLIDAYS[2025], {date(2025, 1, 2): "calendar correction"}):
            assert read_price_map_external_revision() != before
