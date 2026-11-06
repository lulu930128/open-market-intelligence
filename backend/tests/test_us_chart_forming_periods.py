"""Display-only US period bars using isolated canonical fixtures, never live IO."""

from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.db.models import RawFetchResult, USDailyPrice
from app.us_market.daily_ohlcv_chart import read_us_daily_ohlcv_chart
from app.us_market.intraday_acquisition import USIntradayAcquisitionExecutor
from app.us_market.intraday_platform import USIntradayMarketPlatform
from app.us_market.market_data.descriptors import YAHOO_INTRADAY_DESCRIPTOR, YAHOO_INTRADAY_RESOURCE_ID
from app.us_market.schemas import USOhlcChartRead
from app.us_market.trading_calendar import us_session_close_time, us_historical_daily_receipt_boundary
from test_us_intraday_shared_core import _db, _seed_daily_previous_close, _yahoo_bars_payload


NY = ZoneInfo("America/New_York")
DAY = date(2026, 11, 5)


@pytest.fixture
def db():
    session = _db()
    yield session
    engine = session.get_bind()
    session.close()
    engine.dispose()


def seed_history(db, now, days):
    first_day, first_close = days[0]
    _seed_daily_previous_close(db, trade_date=first_day, close_price=first_close)
    template = db.query(USDailyPrice).one()
    raw = db.get(RawFetchResult, template.raw_result_id)
    raw.fetched_at = now - timedelta(hours=1)
    template.fetched_at = raw.fetched_at
    template.event_at = datetime.combine(first_day, us_session_close_time(first_day), NY)
    for day, close in days[1:]:
        db.add(USDailyPrice(
            provider=template.provider, symbol="AAPL", trade_date=day,
            open_price=close - 1, high_price=close + 1, low_price=close - 2,
            close_price=close, trade_volume=1000, fetched_at=raw.fetched_at,
            source_id=template.source_id, raw_result_id=raw.id, authority="vendor",
            raw_contract_version=template.raw_contract_version,
            event_at=datetime.combine(day, us_session_close_time(day), NY),
            finalization="final", price_basis="raw", volume_unit="shares",
            volume_status="observed", raw_payload_hash=template.raw_payload_hash,
        ))
    db.commit()


def seed_minutes(db, day=DAY, *, count=60, missing_volume=False, premarket=False):
    start = datetime.combine(day, time(8, 0) if premarket else time(9, 30), NY)
    now = (start + timedelta(minutes=count)).astimezone(timezone.utc)
    payload = _yahoo_bars_payload(now, count=count)
    if missing_volume:
        payload["chart"]["result"][0]["indicators"]["quote"][0]["volume"][0] = None
    platform = USIntradayMarketPlatform(
        db, bar_descriptors=(YAHOO_INTRADAY_DESCRIPTOR,),
        acquisition=USIntradayAcquisitionExecutor(
            fetchers={YAHOO_INTRADAY_RESOURCE_ID: lambda *_: (payload, "https://fixture.invalid/bars")},
            clock=lambda: now,
        ),
    )
    platform.refresh_intraday_bars(symbol="AAPL", now=now, max_provider_calls=1)
    return now


@pytest.mark.parametrize("timeframe,period", [("daily", DAY), ("weekly", date(2026, 11, 2)), ("monthly", date(2026, 11, 1))])
def test_current_regular_bar_updates_each_display_period_without_mutating_history(db, timeframe, period):
    now = seed_minutes(db)
    seed_history(db, now, [(date(2026, 10, 30), 300), (date(2026, 11, 2), 199),
                           (date(2026, 11, 3), 210), (date(2026, 11, 4), 198)])
    baseline = read_us_daily_ohlcv_chart(db, symbol="AAPL", timeframe=timeframe, now=now)
    with patch.object(db, "commit", side_effect=AssertionError("read must not write")), patch.object(
        USIntradayAcquisitionExecutor, "acquire_bar_observations", side_effect=AssertionError("read must not acquire")
    ):
        result = read_us_daily_ohlcv_chart(db, symbol="AAPL", timeframe=timeframe, now=now, include_intraday_overlay=True)
    chart = USOhlcChartRead.model_validate(result)
    overlay = chart.intraday_overlay
    assert overlay is not None
    assert overlay.point.time == DAY  # original daily contract remains daily
    assert overlay.display_timeframe == timeframe
    assert overlay.display_point.time == period
    assert overlay.display_point.close == pytest.approx(201.09)
    assert overlay.display_point.open == (200 if timeframe == "daily" else 198)
    if timeframe != "daily":
        assert overlay.display_point.high == 211
        assert overlay.display_point.low == 196
        assert overlay.display_point.volume == overlay.point.volume + 3000
    assert overlay.display_missing_trade_dates == []
    assert overlay.finalization == "provisional" and not overlay.decision_usable
    assert result["points"] == baseline["points"]
    assert result["point_count"] == baseline["point_count"]
    assert db.query(USDailyPrice).count() == 4


@pytest.mark.parametrize("day", [date(2026, 10, 8), date(2026, 11, 5)])
def test_daily_overlay_updates_from_new_regular_minutes_across_dst(db, day):
    now = seed_minutes(db, day, count=1)
    before = read_us_daily_ohlcv_chart(db, symbol="AAPL", now=now, include_intraday_overlay=True)
    now = seed_minutes(db, day, count=2)
    after = read_us_daily_ohlcv_chart(db, symbol="AAPL", now=now, include_intraday_overlay=True)
    assert before["intraday_overlay"]["point"]["close"] == 200.5
    assert after["intraday_overlay"]["point"]["close"] == 200.51
    assert after["intraday_overlay"]["trade_date"] == day
    assert after["intraday_overlay"]["event_at"] > before["intraday_overlay"]["event_at"]


@pytest.mark.parametrize("timeframe", ["daily", "weekly", "monthly"])
def test_premarket_and_explicit_history_do_not_create_current_period(db, timeframe):
    now = seed_minutes(db, premarket=True)
    seed_history(db, now, [(date(2026, 11, 4), 198)])
    assert read_us_daily_ohlcv_chart(db, symbol="AAPL", timeframe=timeframe, now=now, include_intraday_overlay=True)["intraday_overlay"] is None
    now = seed_minutes(db)
    with patch("app.us_market.daily_ohlcv_chart.USIntradayMarketPlatform", side_effect=AssertionError("history must not read current bars")):
        assert read_us_daily_ohlcv_chart(db, symbol="AAPL", timeframe=timeframe, to_date=date(2026, 11, 4), now=now, include_intraday_overlay=True)["intraday_overlay"] is None


@pytest.mark.parametrize("timeframe", ["weekly", "monthly"])
@pytest.mark.parametrize("missing_volume", [False, True])
def test_partial_period_never_presents_known_subtotal_as_complete_volume(db, timeframe, missing_volume):
    now = seed_minutes(db, missing_volume=missing_volume)
    seed_history(db, now, [(date(2026, 11, 2), 199), (date(2026, 11, 4), 198)])
    overlay = read_us_daily_ohlcv_chart(db, symbol="AAPL", timeframe=timeframe, now=now, include_intraday_overlay=True)["intraday_overlay"]
    assert overlay is not None
    assert overlay["display_point"]["volume"] is None
    assert overlay["display_missing_trade_dates"] == [date(2026, 11, 3)]
    assert "DISPLAY_PERIOD_HISTORY_INCOMPLETE" in overlay["limitations"]
    assert "DISPLAY_PERIOD_VOLUME_INCOMPLETE" in overlay["limitations"]


@pytest.mark.parametrize("timeframe,day,period", [
    ("weekly", date(2026, 11, 9), date(2026, 11, 9)),
    ("monthly", date(2026, 12, 1), date(2026, 12, 1)),
])
def test_new_period_does_not_inherit_previous_period_ohlc_or_volume(db, timeframe, day, period):
    now = seed_minutes(db, day)
    previous = date(2026, 11, 6) if timeframe == "weekly" else date(2026, 11, 30)
    seed_history(db, now, [(previous, 900)])
    overlay = read_us_daily_ohlcv_chart(db, symbol="AAPL", timeframe=timeframe, now=now, include_intraday_overlay=True)["intraday_overlay"]
    assert overlay is not None
    assert overlay["display_point"] == {**overlay["point"], "time": period}
    assert overlay["display_missing_trade_dates"] == []


@pytest.mark.parametrize("timeframe", ["daily", "weekly", "monthly"])
def test_finalized_daily_replaces_forming_evidence_for_all_periods(db, timeframe):
    now = seed_minutes(db)
    seed_history(db, now, [(date(2026, 11, 4), 198)])
    before = read_us_daily_ohlcv_chart(db, symbol="AAPL", timeframe=timeframe, now=now, include_intraday_overlay=True)
    assert before["intraday_overlay"] is not None
    daily = db.query(USDailyPrice).one()
    daily.trade_date = DAY
    daily.event_at = datetime.combine(DAY, us_session_close_time(DAY), NY)
    receipt = us_historical_daily_receipt_boundary(DAY).astimezone(timezone.utc)
    daily.fetched_at = receipt
    daily.open_price, daily.high_price, daily.low_price, daily.close_price = 204, 206, 203, 205
    db.get(RawFetchResult, daily.raw_result_id).fetched_at = receipt
    db.commit()
    with patch("app.us_market.daily_ohlcv_chart.USIntradayMarketPlatform", side_effect=AssertionError("finalized daily wins")):
        chart = read_us_daily_ohlcv_chart(db, symbol="AAPL", timeframe=timeframe, now=receipt, include_intraday_overlay=True)
    assert chart["intraday_overlay"] is None
    assert chart["points"][-1]["close"] == 205


@pytest.mark.parametrize("day,regular_minutes", [(DAY, 390), (date(2026, 11, 27), 210)])
def test_after_hours_never_enters_regular_forming_candle_including_early_close(db, day, regular_minutes):
    now = seed_minutes(db, day, count=regular_minutes + 15)
    overlay = read_us_daily_ohlcv_chart(db, symbol="AAPL", now=now, include_intraday_overlay=True)["intraday_overlay"]
    assert overlay is not None
    assert overlay["point"]["close"] == pytest.approx(200.5 + (regular_minutes - 1) / 100)
    assert overlay["coverage"]["point_count"] == regular_minutes
    assert overlay["coverage"]["expected_point_count"] == regular_minutes
    # Yahoo's source event timestamp is the bucket start, not a fabricated close receipt.
    assert overlay["event_at"] == datetime.combine(day, us_session_close_time(day), NY) - timedelta(minutes=1)
