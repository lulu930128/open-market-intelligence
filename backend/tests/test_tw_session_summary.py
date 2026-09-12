from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.market import tw_session_summary as summary
from app.market.tw_technical_service import TaiwanTechnicalService
from app.market_data.contracts import Quantity, QuantityUnit
from test_tw_technical_service import _series, TAIPEI


DAY = date(2026, 9, 11)


def bars_fixture(volumes=(1000, 2000)):
    base = _series()
    start = datetime(2026, 9, 11, 9, tzinfo=TAIPEI)
    bars = tuple(base.bars[i].model_copy(update={
        "interval": "1m", "start_at": start + timedelta(minutes=i),
        "end_at": start + timedelta(minutes=i + 1),
        "volume": None if volume is None else Quantity(value=Decimal(volume), unit=QuantityUnit.SHARE),
        "turnover_value": None,
    }) for i, volume in enumerate(volumes))
    states = tuple(base.bar_states[i].model_copy(update={"start_at": bar.start_at}) for i, bar in enumerate(bars))
    return base.model_copy(update={"requested_interval": "1m", "base_interval": "1m", "bars": bars, "bar_states": states,
        "current_session_coverage": SimpleNamespace(status="complete_prefix")})


def quote_fixture():
    return dict(trade_date=DAY.isoformat(), quote_time="2026-09-11T13:30:00+08:00", source="test_quote",
        open_price=101, high_price=110, low_price=100, total_volume_lots=0, volume_status="available",
        last_trade_volume_lots=0, actual_trade_occurred=True, last_trade_volume_status="available",
        headline_trade_date=DAY.isoformat(), headline_price=105, official_close_status="confirmed_latest_session",
        presentation_session_state="previous_session", freshness={"status": "stale"},
        volume_scope="regular_session_board_lot_cumulative", bid_depth_status="unavailable", bid_total_size_lots=500,
        change_reference={"price": 100, "display_usable": True, "calculation_eligible": True, "applies_to_trade_date": DAY.isoformat()})


def project(bars=None, quote=None, previous=None, pace=None):
    bars = bars if bars is not None else bars_fixture()
    return summary.project_session_summary(instrument_id="2330", trade_date=DAY, bars=bars,
        quote=quote if quote is not None else quote_fixture(), technical_point=TaiwanTechnicalService().session_average(bars),
        previous_daily=previous, pace=pace or {})


def test_summary_uses_weighted_canonical_average_not_ohlc_mean():
    result = project()
    expected = ((102 + 99 + 101) / 3 * 1000 + (102.5 + 99.5 + 101.5) / 3 * 2000) / 3000
    assert result.metrics["average"].value == pytest.approx(expected)
    assert result.metrics["average"].estimated
    assert result.metrics["turnover"].value == 101 * 1000 + 101.5 * 2000
    assert result.metrics["turnover"].estimated
    assert result.metrics["range_pct"].value == 10
    assert result.metrics["vwap_distance_pct"].value == pytest.approx((105 / expected - 1) * 100)


def test_zero_is_not_missing_and_stale_is_not_promoted_by_close():
    result = project()
    assert result.metrics["volume"].value == 0
    assert result.metrics["last_volume"].value == 0
    assert result.metrics["volume"].freshness == "stale"
    assert result.official_close_status == "confirmed_latest_session"
    assert result.metrics["bid"].value is None


@pytest.mark.parametrize("volumes,expected", [((0, 2000), 101.16666667), ((None, 2000), None), ((0, 0), None)])
def test_average_zero_weight_and_missing_do_not_restart_suffix(volumes, expected):
    average = project(bars_fixture(volumes)).metrics["average"].value
    assert average == pytest.approx(expected) if expected is not None else average is None


def test_wrong_date_quote_does_not_leak_price_or_volume():
    quote = quote_fixture()
    quote["trade_date"] = "2026-09-10"
    quote["headline_trade_date"] = "2026-09-10"
    result = project(quote=quote)
    assert result.metrics["high"].value is None
    assert result.metrics["volume"].value is None
    assert result.metrics["vwap_distance_pct"].value is None


def test_previous_daily_must_match_previous_session_and_preserves_scope():
    daily = SimpleNamespace(trade_date=date(2026, 9, 10), trade_volume=321123, source="official")
    item = project(previous=daily).metrics["previous_volume"]
    assert item.value == 321.123
    assert item.trade_date == date(2026, 9, 10)
    assert "VOLUME_SCOPE_DIFFERS_FROM_QUOTE_CUMULATIVE" in item.limitations
    daily.trade_date = date(2026, 9, 9)
    assert project(previous=daily).metrics["previous_volume"].value is None


def test_partial_turnover_is_never_complete_and_no_amount_becomes_zero():
    bars = bars_fixture()
    bars = bars.model_copy(update={"bars": (bars.bars[0].model_copy(update={"turnover_value": Decimal(100)}), bars.bars[1])})
    result = project(bars)
    assert result.metrics["turnover"].value == 100
    assert result.metrics["turnover"].status == "partial"
    assert not result.metrics["turnover"].estimated
    assert project(bars_fixture((None, None))).metrics["turnover"].value is None


def test_partial_coverage_preserved_even_when_number_exists():
    bars = bars_fixture().model_copy(update={"current_session_coverage": SimpleNamespace(status="partial")})
    assert project(bars).metrics["average"].status == "partial"
    assert project(bars).metrics["turnover"].status == "partial"


def test_no_relative_volume_guess_for_missing_samples_or_wrong_date():
    assert project().metrics["relative_volume"].value is None
    pace = {"trade_date": DAY.isoformat(), "status": "partial", "same_time_baseline_5d": {"pace_ratio": 0.8, "sample_days": 3}}
    item = project(pace=pace).metrics["relative_volume"]
    assert item.value == .8 and item.status == "partial" and item.sample_days == 3
    pace["trade_date"] = "2026-09-10"
    assert project(pace=pace).metrics["relative_volume"].value is None


def test_read_rejects_mismatched_display_date_before_any_db_io():
    with pytest.raises(ValueError, match="TRADE_DATE_MISMATCH"):
        summary.read_taiwan_session_summary(object(), instrument_id="2330", expected_trade_date=date(2026, 9, 10), requested_at=datetime(2026, 9, 12, 12, tzinfo=TAIPEI))


def test_summary_rejects_other_interval_and_session():
    with pytest.raises(ValueError, match="BAR_IDENTITY_MISMATCH"):
        project(bars_fixture().model_copy(update={"requested_interval": "5m"}))
    bars = bars_fixture()
    wrong = bars.bars[0].model_copy(update={"start_at": bars.bars[0].start_at - timedelta(days=1)})
    with pytest.raises(ValueError, match="BAR_IDENTITY_MISMATCH"):
        project(bars.model_copy(update={"bars": (wrong, bars.bars[1])}))


def test_native_datetime_quote_serializes_without_losing_offset():
    quote = quote_fixture()
    quote["quote_time"] = datetime(2026, 9, 11, 13, 30, tzinfo=TAIPEI)
    assert project(quote=quote).model_dump(mode="json")["metrics"]["open"]["as_of"] == "2026-09-11T13:30:00+08:00"


def test_ineligible_current_bar_cannot_produce_confirmed_average_or_turnover():
    bars = bars_fixture()
    bars = bars.model_copy(update={"bar_states": (bars.bar_states[0], bars.bar_states[1].model_copy(update={"technical_eligible": False}))})
    result = project(bars)
    assert result.metrics["average"].value is None
    assert result.metrics["turnover"].status == "partial"


def test_read_is_fixed_one_minute_and_read_only(monkeypatch):
    bars = bars_fixture()
    calls = []
    class Reader:
        def __init__(self, db):
            pass
        def read_current_session_bars(self, **kwargs):
            calls.append(kwargs)
            return bars
    monkeypatch.setattr(summary, "TaiwanBarService", Reader)
    monkeypatch.setattr(summary, "read_taiwan_quote_evidence_projection", lambda **kwargs: quote_fixture())
    monkeypatch.setattr(summary, "read_taiwan_official_daily", lambda *args, **kwargs: calls.append(kwargs))
    monkeypatch.setattr(summary, "project_taiwan_daily_rows", lambda *args: [])
    monkeypatch.setattr(summary, "build_tw_stock_volume_pace", lambda *args, **kwargs: {})
    result = summary.read_taiwan_session_summary(object(), instrument_id="2330", expected_trade_date=DAY, requested_at=datetime(2026, 9, 12, 12, tzinfo=TAIPEI))
    assert calls[0]["interval"] == "1m"
    assert calls[1]["from_date"] == date(2026, 9, 10)
    assert result.trade_date == DAY
    assert result.model_dump(mode="json")["base_interval"] == "1m"
