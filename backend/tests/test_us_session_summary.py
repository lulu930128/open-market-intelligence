from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.market_data.contracts import InstrumentType, Quantity, QuantityUnit
from app.us_market.market_truth import read_us_market_truth_bundle
from app.us_market.schemas import USIntradayTrendRead
from app.us_market.service import _market_truth_compat_intraday_payload, _us_intraday_snapshot_revision
from app.us_market.session_summary import project_us_session_summary, read_us_session_volume_pace
from test_us_market_truth_snapshot import _bar, _fake_components, _install_fake_components


def fixture_bundle(monkeypatch, *, count=390, volume=100, missing_index=None, scope="regular"):
    quote, intraday, daily = _fake_components()
    start = datetime(2026, 8, 31, 13, 30, tzinfo=timezone.utc)
    bars = tuple(_bar(
        observation_id=f"summary-{i}", start_at=start + timedelta(minutes=i),
        end_at=start + timedelta(minutes=i + 1), close=str(200 + i),
    ).model_copy(update={"volume": None if i == missing_index or volume is None else Quantity(value=Decimal(volume), unit=QuantityUnit.SHARE),
                         "volume_status": "missing" if volume is None or i == missing_index else "observed"}) for i in range(count))
    daily = daily.model_copy(update={"bars": tuple(bar.model_copy(update={
        "volume": Quantity(value=Decimal(50000), unit=QuantityUnit.SHARE), "volume_status": "observed",
    }) for bar in daily.bars)})
    intraday = intraday.model_copy(update={"bars": bars})
    _install_fake_components(monkeypatch, (quote, intraday, daily))
    bundle = read_us_market_truth_bundle(
        object(), symbol="AAPL", evaluated_at=datetime(2026, 9, 1, 1, tzinfo=timezone.utc), requested_scope=scope,
    )
    return bundle, intraday, daily


def test_complete_summary_shares_estimates_prior_session_and_no_fabricated_depth(monkeypatch):
    bundle, _, daily = fixture_bundle(monkeypatch)
    result = project_us_session_summary(snapshot=bundle.snapshot, series=bundle.series, daily=daily, pace=None)
    metrics = result.metrics
    assert metrics["open"].value == 200
    assert metrics["high"].value == 589
    assert metrics["low"].value == 200
    assert metrics["reference"].value == 198
    assert metrics["volume"].value == 39000
    assert metrics["volume"].unit == "shares"
    assert metrics["volume"].status == "available"
    assert metrics["turnover"].value == sum(range(200, 590)) * 100
    assert metrics["turnover"].estimated is True
    assert metrics["average"].value == pytest.approx(394.5)
    assert metrics["range_pct"].value == pytest.approx(389 / 198 * 100)
    assert metrics["vwap_distance_pct"].value == pytest.approx((589 / 394.5 - 1) * 100)
    assert metrics["previous_volume"].value == 50000
    assert metrics["previous_volume"].trade_date == date(2026, 8, 28)
    for key in ("last_volume", "bid", "ask", "relative_volume"):
        assert metrics[key].value is None
        assert metrics[key].status == "unavailable"


@pytest.mark.parametrize("volume,missing_index,expected", [(0, None, 0), (None, None, None), (100, 3, 38900)])
def test_missing_volume_never_becomes_zero_or_complete_average(monkeypatch, volume, missing_index, expected):
    bundle, _, daily = fixture_bundle(monkeypatch, volume=volume, missing_index=missing_index)
    metrics = project_us_session_summary(snapshot=bundle.snapshot, series=bundle.series, daily=daily, pace=None).metrics
    assert metrics["volume"].value == expected
    assert metrics["average"].value is None
    assert metrics["vwap_distance_pct"].value is None
    if missing_index is not None:
        assert metrics["volume"].status == "partial"


def test_partial_session_and_exact_previous_day_gate(monkeypatch):
    bundle, _, daily = fixture_bundle(monkeypatch, count=12)
    wrong_daily = daily.model_copy(update={"bars": tuple(bar.model_copy(update={
        "start_at": bar.start_at - timedelta(days=1), "end_at": bar.end_at - timedelta(days=1),
    }) for bar in daily.bars)})
    summary = project_us_session_summary(snapshot=bundle.snapshot, series=bundle.series, daily=wrong_daily, pace=None)
    assert summary.metrics["volume"].status == "partial"
    assert summary.metrics["previous_volume"].value is None
    missing_open = bundle.series.model_copy(update={"regular_points": bundle.series.regular_points[1:]})
    assert project_us_session_summary(snapshot=bundle.snapshot, series=missing_open, daily=daily, pace=None).metrics["open"].value is None


def test_interval_changes_keep_summary_and_summary_changes_invalidate_revision(monkeypatch):
    bundle, _, daily = fixture_bundle(monkeypatch)
    summary = project_us_session_summary(snapshot=bundle.snapshot, series=bundle.series, daily=daily, pace=None)
    bundle = replace(bundle, session_summary=summary)
    results = [_market_truth_compat_intraday_payload(bundle=bundle, session_scope="regular", interval=interval)
               for interval in ("1m", "5m", "15m")]
    for result in results:
        wire = USIntradayTrendRead.model_validate(result).model_dump(mode="json")
        assert wire["session_summary"] == results[0]["session_summary"]
    changed = {**results[0], "session_summary": {**results[0]["session_summary"], "series_revision": "corrected"}}
    assert _us_intraday_snapshot_revision(changed) != results[0]["snapshot_revision"]


def test_index_metrics_are_not_applicable_even_if_legacy_volume_exists(monkeypatch):
    bundle, _, daily = fixture_bundle(monkeypatch)
    instrument = bundle.series.instrument.model_copy(update={"instrument_type": InstrumentType.INDEX})
    summary = project_us_session_summary(
        snapshot=bundle.snapshot.model_copy(update={"instrument": instrument}),
        series=bundle.series.model_copy(update={"instrument": instrument}), daily=daily, pace=None,
    )
    for key in ("volume", "turnover", "average", "previous_volume", "relative_volume", "vwap_distance_pct"):
        assert summary.metrics[key].value is None


def test_regular_relative_volume_uses_existing_bounded_reader(monkeypatch):
    bundle, intraday, daily = fixture_bundle(monkeypatch)
    calls = []
    monkeypatch.setattr("app.us_market.session_summary.USIntradayMarketPlatform.read_volume_sessions",
                        lambda self, **kwargs: calls.append(kwargs) or ())
    pace = read_us_session_volume_pace(object(), series=bundle.series, intraday=intraday, daily=daily)
    assert len(calls) == 1
    assert calls[0]["current_trade_date"] == date(2026, 8, 31)
    assert calls[0]["max_sessions"] == 20
    assert calls[0]["provider"] == intraday.health.selected_provider
    assert pace["same_time_baseline_5d"]["pace_ratio"] is None
    assert pace["same_time_baseline_5d"]["sample_days"] == 0


def test_volume_read_failure_preserves_price_summary(monkeypatch):
    bundle, intraday, daily = fixture_bundle(monkeypatch)
    def fail(self, **kwargs):
        raise ValueError("bad historical volume")
    monkeypatch.setattr("app.us_market.session_summary.USIntradayMarketPlatform.read_volume_sessions", fail)
    pace = read_us_session_volume_pace(object(), series=bundle.series, intraday=intraday, daily=daily)
    summary = project_us_session_summary(snapshot=bundle.snapshot, series=bundle.series, daily=daily, pace=pace)
    assert summary.metrics["high"].value == 589
    assert summary.metrics["relative_volume"].value is None
    assert "US_VOLUME_BASELINE_READ_UNAVAILABLE" in summary.metrics["relative_volume"].limitations


def test_summary_integration_is_opt_in_and_read_only(monkeypatch):
    fixture_bundle(monkeypatch)
    calls = []
    monkeypatch.setattr("app.us_market.session_summary.USIntradayMarketPlatform.read_volume_sessions",
                        lambda self, **kwargs: calls.append(kwargs) or ())
    kwargs = dict(symbol="AAPL", evaluated_at=datetime(2026, 9, 1, 1, tzinfo=timezone.utc))
    assert read_us_market_truth_bundle(object(), **kwargs).session_summary is None
    assert calls == []
    assert read_us_market_truth_bundle(object(), include_session_summary=True, **kwargs).session_summary is not None
    assert len(calls) == 1


@pytest.mark.parametrize("sample_days,status", [(0, "unavailable"), (3, "partial"), (5, "available")])
def test_relative_volume_sample_quality_and_identity(monkeypatch, sample_days, status):
    bundle, _, daily = fixture_bundle(monkeypatch)
    pace = {"trade_date": "2026-08-31", "same_time_baseline_5d": {
        "pace_ratio": 0.97 if sample_days else None, "sample_days": sample_days,
    }}
    summary = project_us_session_summary(snapshot=bundle.snapshot, series=bundle.series, daily=daily, pace=pace)
    assert summary.metrics["relative_volume"].status == status
    assert summary.metrics["relative_volume"].sample_days == sample_days
    pace["trade_date"] = "2026-08-28"
    assert project_us_session_summary(snapshot=bundle.snapshot, series=bundle.series, daily=daily, pace=pace).metrics["relative_volume"].value is None


def test_extended_average_resets_and_regular_baseline_is_not_reused(monkeypatch):
    from app.market_data.contracts import MarketSession
    bundle, _, daily = fixture_bundle(monkeypatch)
    last = bundle.series.regular_points[-1]
    extended = tuple(last.model_copy(update={
        "session": MarketSession.POST_CLOSE,
        "start_at": last.start_at + timedelta(minutes=i + 2),
        "end_at": last.end_at + timedelta(minutes=i + 2),
        "open_price": Decimal(700 + i * 10), "high_price": Decimal(700 + i * 10),
        "low_price": Decimal(700 + i * 10), "close_price": Decimal(700 + i * 10),
    }) for i in range(2))
    for scope in ("all", "extended"):
        series = bundle.series.model_copy(update={"after_hours_points": extended, "requested_scope": scope})
        summary = project_us_session_summary(snapshot=bundle.snapshot, series=series, daily=daily, pace={
            "trade_date": "2026-08-31", "same_time_baseline_5d": {"pace_ratio": 0.97, "sample_days": 5},
        })
        assert summary.metrics["average"].value == 705
        assert summary.metrics["average"].scope == "post_close_session_1m_bars"
        assert summary.metrics["volume"].value == (39200 if scope == "all" else 200)
        assert summary.metrics["relative_volume"].value is None


def test_empty_and_partial_provider_preserve_missing_and_freshness(monkeypatch):
    from app.market_data.contracts import EvidenceFreshness
    bundle, _, daily = fixture_bundle(monkeypatch)
    snapshot = bundle.snapshot.model_copy(update={"health": bundle.snapshot.health.model_copy(update={
        "intraday": bundle.snapshot.health.intraday.model_copy(update={"freshness": EvidenceFreshness.STALE}),
    })})
    series = bundle.series.model_copy(update={"limitations": ("PARTIAL_US_MARKET_VOLUME",)})
    summary = project_us_session_summary(snapshot=snapshot, series=series, daily=daily, pace=None)
    assert summary.metrics["volume"].status == "partial"
    assert summary.metrics["average"].status == "partial"
    assert summary.metrics["high"].freshness == "stale"
    empty = series.model_copy(update={"regular_points": (), "continuity": "missing"})
    summary = project_us_session_summary(snapshot=snapshot, series=empty, daily=daily, pace=None)
    for key in ("volume", "turnover", "average", "high", "low", "range_pct"):
        assert summary.metrics[key].value is None
